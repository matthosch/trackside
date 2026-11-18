"""The timing-archive pipeline steps. Each step reads and writes state in the
database, so steps can be retried or rerun independently.

    discover -> download -> load -> refresh_marts -> data-quality checks
"""

import hashlib
import logging
import urllib.parse
from datetime import date
from pathlib import Path

import psycopg

from . import alkamel, fetch, timing

log = logging.getLogger(__name__)


def discover(conn: psycopg.Connection, seasons: list[int], today: date | None = None) -> int:
    """Record every in-scope session file on the archives. Returns new files found.

    Past seasons are settled: an event already in the manifest is not listed again.
    The current season is always relisted, since sessions keep appearing.
    """
    today = today or date.today()
    circuits = conn.execute("SELECT id, name, aliases FROM circuits").fetchall()
    settled = {
        (source, season, event)
        for source, season, event in conn.execute(
            "SELECT DISTINCT source, season, event_folder FROM raw.timing_files WHERE season < %s",
            (today.year,),
        )
    }
    new_files = 0
    for source in alkamel.SOURCES.values():
        home = fetch.get(alkamel.listing_url(source)).decode("utf-8", errors="replace")
        for season in seasons:
            season_value = alkamel.season_value(home, season)
            if season_value is None:
                log.warning("%s has no season %d", source.id, season)
                continue
            season_page = fetch.get(alkamel.listing_url(source, season_value)).decode("utf-8", errors="replace")
            for event_value, label in alkamel.select_options(season_page, "evvent"):
                circuit_id = alkamel.match_circuit(label, circuits)
                if circuit_id is None or (source.id, season, event_value) in settled:
                    continue
                url = alkamel.listing_url(source, season_value, event_value)
                page = fetch.get(url).decode("utf-8", errors="replace")
                sessions = alkamel.discover_sessions(page, url, source)
                new_files += _record(conn, sessions, circuit_id)
                log.info("%s %d %s: %d sessions", source.id, season, event_value, len(sessions))
    return new_files


def _record(conn: psycopg.Connection, sessions: list[alkamel.SessionFiles], circuit_id: str) -> int:
    added = 0
    with conn.transaction():
        for s in sessions:
            conn.execute(
                """
                INSERT INTO staging.sessions (source, season, circuit_id, event_folder, series_folder,
                                              session_folder, session_name, session_type, starts_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source, season, event_folder, series_folder, session_folder) DO NOTHING
                """,
                (s.source, s.season, circuit_id, s.event_folder, s.series_folder, s.session_folder,
                 s.session_name, s.session_type, s.starts_at),
            )
            for kind, url in (("laps", s.laps_url), ("results", s.results_url)):
                if url is None:
                    continue
                # A more final file (e.g. Official replacing Provisional) supersedes the old one.
                cur = conn.execute(
                    """
                    INSERT INTO raw.timing_files (url, source, season, event_folder, circuit_id,
                                                  series_folder, session_folder, kind)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (url) DO NOTHING
                    """,
                    (url, s.source, s.season, s.event_folder, circuit_id, s.series_folder,
                     s.session_folder, kind),
                )
                added += cur.rowcount
    return added


def _local_path(raw_dir: Path, url: str) -> Path:
    parsed = urllib.parse.urlparse(url)
    parts = [urllib.parse.unquote(p) for p in parsed.path.split("/") if p]
    safe = ["".join(c if c.isalnum() or c in " ._-()" else "_" for c in p) for p in parts]
    return raw_dir.joinpath(parsed.netloc, *safe)


def download(conn: psycopg.Connection, raw_dir: Path, limit: int | None = None) -> tuple[int, int]:
    """Fetch files not yet on disk. Returns (fetched, failed)."""
    pending = conn.execute(
        "SELECT id, url FROM raw.timing_files WHERE fetched_at IS NULL ORDER BY season DESC, id LIMIT %s",
        (limit,),
    ).fetchall()
    fetched = failed = 0
    for file_id, url in pending:
        try:
            data = fetch.get(url)
        except Exception as error:  # noqa: BLE001 - recorded, and counted by a data-quality check
            log.warning("could not fetch %s: %s", url, error)
            failed += 1
            continue
        path = _local_path(raw_dir, url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        with conn.transaction():
            conn.execute(
                """
                UPDATE raw.timing_files
                SET local_path = %s, sha256 = %s, bytes = %s, fetched_at = now(),
                    loaded_at = NULL, load_error = NULL
                WHERE id = %s
                """,
                (str(path), hashlib.sha256(data).hexdigest(), len(data), file_id),
            )
        fetched += 1
    return fetched, failed


def load(conn: psycopg.Connection) -> tuple[int, int]:
    """Parse fetched files into staging for every session with something new.

    A session is reloaded whole (laps and entries) from its most final files.
    Returns (sessions loaded, sessions with errors).
    """
    sessions = conn.execute(
        """
        SELECT s.id, s.source, s.season, s.event_folder, s.series_folder, s.session_folder
        FROM staging.sessions s
        WHERE EXISTS (
            SELECT 1 FROM raw.timing_files f
            WHERE (f.source, f.season, f.event_folder, f.series_folder, f.session_folder)
                = (s.source, s.season, s.event_folder, s.series_folder, s.session_folder)
              AND f.fetched_at IS NOT NULL AND f.loaded_at IS NULL AND f.load_error IS NULL
        )
        ORDER BY s.id
        """
    ).fetchall()
    loaded = errors = 0
    for session_id, source, season, event, series, session in sessions:
        files = conn.execute(
            """
            SELECT DISTINCT ON (kind) id, kind, local_path FROM raw.timing_files
            WHERE (source, season, event_folder, series_folder, session_folder) = (%s, %s, %s, %s, %s)
              AND fetched_at IS NOT NULL
            ORDER BY kind, discovered_at DESC, id DESC
            """,
            (source, season, event, series, session),
        ).fetchall()
        by_kind = {kind: (file_id, path) for file_id, kind, path in files}
        classes = alkamel.SOURCES[source].classes
        try:
            laps = entries = []
            if "laps" in by_kind:
                laps = timing.parse_laps(Path(by_kind["laps"][1]).read_bytes(), classes)
            if "results" in by_kind:
                entries = timing.parse_results(Path(by_kind["results"][1]).read_bytes(), classes)
        except (timing.SchemaError, OSError) as error:
            log.warning("session %s failed to parse: %s", session_id, error)
            with conn.transaction():
                for file_id, _ in by_kind.values():
                    conn.execute("UPDATE raw.timing_files SET load_error = %s WHERE id = %s", (str(error), file_id))
            errors += 1
            continue

        with conn.transaction(), conn.cursor() as cur:
            cur.execute("DELETE FROM staging.laps WHERE session_id = %s", (session_id,))
            cur.execute("DELETE FROM staging.session_entries WHERE session_id = %s", (session_id,))
            with cur.copy(
                "COPY staging.laps (session_id, car_number, lap_number, driver_number, driver_name, lap_time_ms,"
                " s1_ms, s2_ms, s3_ms, in_pit, flag, class, team, manufacturer) FROM STDIN"
            ) as copy:
                seen = set()
                for lap in laps:
                    if (lap.car_number, lap.lap_number) in seen:
                        continue  # the odd duplicated row in long-race files
                    seen.add((lap.car_number, lap.lap_number))
                    copy.write_row((session_id, lap.car_number, lap.lap_number, lap.driver_number, lap.driver_name,
                                    lap.lap_time_ms, lap.s1_ms, lap.s2_ms, lap.s3_ms, lap.in_pit, lap.flag,
                                    lap.class_, lap.team, lap.manufacturer))
            with cur.copy("COPY staging.session_entries (session_id, car_number, class, team, vehicle) FROM STDIN") as copy:
                for e in entries:
                    copy.write_row((session_id, e.car_number, e.class_, e.team, e.vehicle))
            cur.execute(
                "UPDATE raw.timing_files SET loaded_at = now() WHERE id = ANY(%s)",
                ([file_id for file_id, _ in by_kind.values()],),
            )
        loaded += 1
    return loaded, errors


def refresh_marts(conn: psycopg.Connection) -> None:
    with conn.transaction():
        conn.execute("REFRESH MATERIALIZED VIEW marts.lap_quality")
        conn.execute("REFRESH MATERIALIZED VIEW marts.circuit_pace")
        conn.execute("REFRESH MATERIALIZED VIEW marts.driver_pace")
        conn.execute("REFRESH MATERIALIZED VIEW marts.entry_pace")
