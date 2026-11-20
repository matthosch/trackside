"""Load and prune steps against a real Postgres: parser-version reprocessing and
scope cleanup. Needs TEST_DATABASE_URL, like test_marts_sql.py."""

import os
import uuid
from pathlib import Path

import psycopg
import pytest

from trackside_pipelines import timing, timing_pipeline
from trackside_pipelines.migrate import migrate

MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "migrations"
ADMIN_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="TEST_DATABASE_URL not set")

LAPS = "\n".join([
    "NUMBER;DRIVER_NUMBER;LAP_NUMBER;LAP_TIME;LAP_IMPROVEMENT;CROSSING_FINISH_LINE_IN_PIT;S1;S1_IMPROVEMENT;"
    "S2;S2_IMPROVEMENT;S3;S3_IMPROVEMENT;KPH;ELAPSED;HOUR;S1_LARGE;S2_LARGE;S3_LARGE;TOP_SPEED;DRIVER_NAME;"
    "PIT_TIME;CLASS;GROUP;TEAM;MANUFACTURER;FLAG_AT_FL;",
    "023;1;1;1:20.000;0;;30.000;0;30.000;0;20.000;0;160.0;1:20.000;12:01:00.000;;;;;Ann;;GTD;;Team A;Make A;GF;",
    "23;1;1;1:21.000;0;;30.000;0;30.000;0;21.000;0;160.0;1:21.000;12:01:00.000;;;;;Bo;;GTD PRO;;Team B;Make B;GF;",
])
RESULTS = "\n".join([
    "POSITION;NUMBER;STATUS;LAPS;TEAM;CLASS;VEHICLE;",
    "1;023;Classified;1;Team A;GTD;Make A GT3;",
    "2;23;Classified;1;Team B;GTD PRO;Make B GT3;",
])
IMSA_SERIES = "01_IMSA WeatherTech SportsCar Championship"


@pytest.fixture
def conn():
    name = f"trackside_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        with psycopg.connect(psycopg.conninfo.make_conninfo(ADMIN_URL, dbname=name), autocommit=True) as c:
            migrate(c, MIGRATIONS)
            yield c
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def add_session(c, tmp_path, source="imsa", series=IMSA_SERIES, laps=LAPS):
    """A staged session with fetched laps and results files on disk."""
    key = (source, 2024, "19_Road Atlanta", series, "202410121210_Race")
    c.execute(
        """INSERT INTO staging.sessions (source, season, event_folder, series_folder, session_folder,
                                         circuit_id, session_name, session_type)
           VALUES (%s, %s, %s, %s, %s, 'road-atlanta', 'Race', 'race')""",
        key,
    )
    for kind, text in (("laps", laps), ("results", RESULTS)):
        path = tmp_path / f"{source}-{kind}.csv"
        path.write_bytes(("﻿" + text).encode())
        c.execute(
            """INSERT INTO raw.timing_files (url, source, season, event_folder, series_folder, session_folder,
                                             circuit_id, kind, local_path, fetched_at)
               VALUES (%s, %s, %s, %s, %s, %s, 'road-atlanta', %s, %s, now())""",
            (f"https://example.test/{source}/{kind}", *key, kind, str(path)),
        )


def cars(c):
    return [r[0] for r in c.execute("SELECT DISTINCT car_number FROM staging.laps ORDER BY 1")]


def test_loads_once_then_waits_for_new_files(conn, tmp_path):
    add_session(conn, tmp_path)
    assert timing_pipeline.load(conn) == (1, 0)
    assert cars(conn) == ["023", "23"]
    assert timing_pipeline.load(conn) == (0, 0)


def test_a_parser_version_bump_reprocesses_loaded_files(conn, tmp_path, monkeypatch):
    add_session(conn, tmp_path)
    timing_pipeline.load(conn)
    # Pretend the rows came from the old parser, which merged #023 into #23.
    conn.execute("DELETE FROM staging.laps WHERE car_number = '023'")
    conn.execute("UPDATE raw.timing_files SET parser_version = %s", (timing.PARSER_VERSION - 1,))

    assert timing_pipeline.load(conn) == (1, 0)
    assert cars(conn) == ["023", "23"]
    versions = {v for (v,) in conn.execute("SELECT parser_version FROM raw.timing_files")}
    assert versions == {timing.PARSER_VERSION}


def test_a_failed_file_waits_for_a_parser_fix(conn, tmp_path, monkeypatch):
    add_session(conn, tmp_path, laps=LAPS.replace("FLAG_AT_FL", "FLAG"))
    assert timing_pipeline.load(conn) == (0, 1)
    assert timing_pipeline.load(conn) == (0, 0)  # same parser: no point retrying

    monkeypatch.setattr(timing, "PARSER_VERSION", timing.PARSER_VERSION + 1)
    assert timing_pipeline.load(conn) == (0, 1)  # a new parser gets another try


def test_prune_drops_what_the_scope_rules_now_reject(conn, tmp_path):
    add_session(conn, tmp_path)
    shared = "07_GT World Challenge America powered by AWS - GT America powered by AWS"
    add_session(conn, tmp_path, source="sro_america", series=shared)
    timing_pipeline.load(conn)

    assert timing_pipeline.prune(conn) == 1
    sources = {s for (s,) in conn.execute("SELECT DISTINCT source FROM raw.timing_files")}
    assert sources == {"imsa"}
    orphans = conn.execute(
        "SELECT count(*) FROM staging.laps l LEFT JOIN staging.sessions s ON s.id = l.session_id WHERE s.id IS NULL"
    ).fetchone()[0]
    assert orphans == 0
    assert cars(conn) == ["023", "23"]
