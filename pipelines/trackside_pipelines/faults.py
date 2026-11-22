"""Data faults for demos of the alerting and triage path. Runs inside the Airflow
container, where the private raw files are: faults/inject.py on the host calls it.

Each fault edits one downloaded timing file in place (after keeping a backup) and
marks it for reload, so the next timing_archive run loads the damage and the
data-quality checks catch it. `restore` puts every backed-up file back.

    implausible-laps  impossible lap times in the largest race   -> implausible_lap_pct fails
    missing-laps      a race's lap file emptied to its header    -> races_without_laps fails
    changed-layout    a lap file's FLAG_AT_FL column renamed     -> files_failed_to_load fails
"""

import argparse
import logging
import shutil
import sys
from pathlib import Path

import psycopg

from . import settings

log = logging.getLogger("trackside.faults")

BACKUP_SUFFIX = ".fault-backup"

# Which race lap file each fault damages.
TARGETS = {
    "implausible-laps": "ORDER BY laps DESC",
    "missing-laps": "ORDER BY laps ASC",
    "changed-layout": "ORDER BY s.season DESC, laps DESC",
}


def _target(conn: psycopg.Connection, fault: str, exclude: list[int]) -> tuple[int, Path]:
    row = conn.execute(
        f"""SELECT f.id, f.local_path, count(l.*) AS laps
            FROM raw.timing_files f
            JOIN staging.sessions s
              ON (s.source, s.season, s.event_folder, s.series_folder, s.session_folder)
               = (f.source, f.season, f.event_folder, f.series_folder, f.session_folder)
            JOIN staging.laps l ON l.session_id = s.id
            WHERE f.kind = 'laps' AND s.session_type = 'race' AND f.id <> ALL(%s)
            GROUP BY f.id, f.local_path, s.season
            {TARGETS[fault]}
            LIMIT 1""",
        (exclude,),
    ).fetchone()
    if row is None:
        raise SystemExit("no loaded race lap file to damage; run timing_archive first")
    return row[0], Path(row[1])


def _damaged(conn: psycopg.Connection) -> list[tuple[int, Path]]:
    rows = conn.execute("SELECT id, local_path FROM raw.timing_files WHERE local_path IS NOT NULL").fetchall()
    return [(i, Path(p)) for i, p in rows if Path(p + BACKUP_SUFFIX).exists()]


def _mark_for_reload(conn: psycopg.Connection, file_id: int) -> None:
    conn.execute("UPDATE raw.timing_files SET loaded_at = NULL, load_error = NULL WHERE id = %s", (file_id,))


def inject(conn: psycopg.Connection, fault: str) -> Path:
    file_id, path = _target(conn, fault, [i for i, _ in _damaged(conn)])
    backup = Path(str(path) + BACKUP_SUFFIX)
    shutil.copy2(path, backup)

    text = path.read_bytes().decode("utf-8-sig")
    header, *rows = text.splitlines()
    if fault == "implausible-laps":
        columns = [c.strip() for c in header.split(";")]
        lap_time = columns.index("LAP_TIME")
        damaged = []
        for n, row in enumerate(rows):
            cells = row.split(";")
            if n % 3 == 0 and len(cells) > lap_time:
                cells[lap_time] = "0:20.000"
            damaged.append(";".join(cells))
        rows = damaged
    elif fault == "missing-laps":
        rows = []
    elif fault == "changed-layout":
        header = header.replace("FLAG_AT_FL", "FLAG")
    path.write_bytes(("﻿" + "\n".join([header, *rows]) + "\n").encode("utf-8"))

    _mark_for_reload(conn, file_id)
    log.info("injected %s into file %d (%s)", fault, file_id, path.name)
    return path


def restore(conn: psycopg.Connection) -> int:
    damaged = _damaged(conn)
    for file_id, path in damaged:
        backup = Path(str(path) + BACKUP_SUFFIX)
        shutil.copy2(backup, path)
        backup.unlink()
        _mark_for_reload(conn, file_id)
        log.info("restored file %d (%s)", file_id, path.name)
    return len(damaged)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=[*TARGETS, "restore"])
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with settings.connect() as conn:
        if args.action == "restore":
            print(f"restored {restore(conn)} file(s)")
        else:
            print(f"damaged {inject(conn, args.action).name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
