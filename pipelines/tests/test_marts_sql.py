"""SQL transform tests against a real Postgres.

Set TEST_DATABASE_URL to a server where the role may create databases; each run
creates and drops its own database. Skipped when the variable is not set.
"""

import os
import uuid
from datetime import datetime
from pathlib import Path

import psycopg
import pytest

from trackside_pipelines import quality
from trackside_pipelines.migrate import migrate

MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "migrations"
ADMIN_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="TEST_DATABASE_URL not set")


@pytest.fixture(scope="module")
def conn():
    name = f"trackside_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = psycopg.conninfo.make_conninfo(ADMIN_URL, dbname=name)
    try:
        with psycopg.connect(url) as c:
            migrate(c, MIGRATIONS)
            seed(c)
            c.execute("REFRESH MATERIALIZED VIEW marts.lap_quality")
            c.execute("REFRESH MATERIALIZED VIEW marts.circuit_pace")
            c.commit()
            yield c
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def add_session(c, folder, kind):
    return c.execute(
        """INSERT INTO staging.sessions (source, season, circuit_id, event_folder, series_folder,
                                         session_folder, session_name, session_type, starts_at)
           VALUES ('imsa', 2025, 'road-atlanta', '22_Road Atlanta', '01_IMSA WeatherTech', %s, %s, %s, %s)
           RETURNING id""",
        (folder, folder, kind, datetime(2025, 10, 11, 12, 0)),
    ).fetchone()[0]


def add_laps(c, session_id, car, times, flags=None, pits=()):
    for n, t in enumerate(times, start=1):
        c.execute(
            """INSERT INTO staging.laps (session_id, car_number, lap_number, lap_time_ms, in_pit, flag, class)
               VALUES (%s, %s, %s, %s, %s, %s, 'GTD')""",
            (session_id, car, n, t, n in pits, (flags or {}).get(n, "GF")),
        )


def seed(c):
    race = add_session(c, "202510111210_Race", "race")
    for car, vehicle in [("1", "Ferrari 296 GT3"), ("2", "BMW M4 GT3 EVO"), ("3", "Mystery Car GT3")]:
        c.execute("INSERT INTO staging.session_entries VALUES (%s, %s, 'GTD', 'Team', %s)", (race, car, vehicle))

    # Car 1: lap 1 (start), an FCY lap, an in-lap and its out-lap must not count.
    base = [80_000] * 14
    base[0] = 70_000          # lap 1: excluded however fast
    base[4] = 75_000          # FCY lap: excluded
    base[7] = 75_500          # in-lap (pit): excluded
    base[8] = 76_000          # out-lap: excluded
    add_laps(c, race, "1", base, flags={5: "FCY"}, pits=(8,))
    # Car 2: steady and slower, with one timing glitch far faster than possible.
    times = [81_000] * 14
    times[10] = 40_000
    add_laps(c, race, "2", times)
    # Car 3: unmapped vehicle name, too few laps for race pace.
    add_laps(c, race, "3", [82_000] * 4)
    # Car 4: laps with no results entry.
    add_laps(c, race, "4", [83_000] * 3)

    quali = add_session(c, "202510101520_Qualifying", "qualifying")
    c.execute("INSERT INTO staging.session_entries VALUES (%s, '2', 'GTD', 'Team', 'BMW M4 GT3 EVO')", (quali,))
    add_laps(c, quali, "2", [90_000, 79_000, 79_500])
    add_session(c, "202510111800_Race 2", "race")  # no laps at all


def pace(c):
    rows = c.execute(
        "SELECT model, best_lap_ms, race_pace_ms, race_gap_ms, rank, cars FROM marts.circuit_pace ORDER BY rank"
    ).fetchall()
    return {r[0]: r[1:] for r in rows}


def test_excluded_laps_never_count(conn):
    ferrari = pace(conn)["Ferrari 296 GT3"]
    assert ferrari[0] == 80_000   # best lap ignores lap 1, FCY, in- and out-laps
    assert ferrari[1] == 80_000   # race pace is the mean of its 10 fastest valid laps


def test_implausible_laps_are_flagged_and_excluded(conn):
    flagged = conn.execute("SELECT car_number, lap_number FROM marts.lap_quality WHERE implausible").fetchall()
    assert flagged == [("2", 11)]
    bmw = pace(conn)["BMW M4 GT3 Evo"]
    assert bmw[0] == 79_000       # best lap comes from qualifying, not the glitch
    assert bmw[1] == 81_000


def test_models_are_harmonised_ranked_and_gapped(conn):
    rows = pace(conn)
    assert list(rows)[:2] == ["Ferrari 296 GT3", "BMW M4 GT3 Evo"]
    assert rows["BMW M4 GT3 Evo"][2] == 1_000
    # Unknown vehicles keep their raw name and have no race pace with under 5 laps.
    assert rows["Mystery Car GT3"][1] is None


def test_quality_checks_catch_what_was_seeded(conn):
    results = {r.check.name: r for r in quality.run(conn, "test", "run-1", quality.TIMING_CHECKS)}
    assert results["races_without_laps"].value == 1 and results["races_without_laps"].status == "fail"
    assert results["unmapped_vehicles"].value == 1 and results["unmapped_vehicles"].status == "warn"
    assert results["laps_without_entry_pct"].status == "fail"   # car 4: 3 of 48 laps
    assert results["files_not_fetched"].status == "pass"
