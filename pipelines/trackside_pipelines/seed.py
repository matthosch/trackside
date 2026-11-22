"""One-shot load: migrate, scrape calendars, generate stays.

Stage 1 runs this as a Compose job. In stage 2 the same functions become Airflow tasks.
"""

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

import psycopg

from . import readonly_role, sro_calendar, stays
from .migrate import migrate

log = logging.getLogger("trackside.seed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=int(os.environ.get("SEASON", date.today().year + 1)))
    parser.add_argument("--migrations", type=Path, default=Path(os.environ.get("MIGRATIONS_DIR", "db/migrations")))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        migrate(conn, args.migrations)
        readonly_role.ensure(conn, os.environ.get("READONLY_DB_PASSWORD", "readonly"))

        failures = 0
        for series_id, calendar_url in conn.execute("SELECT id, calendar_url FROM series").fetchall():
            try:
                events = sro_calendar.fetch_season(calendar_url, args.season)
            except Exception:
                log.exception("calendar load failed for %s", series_id)
                failures += 1
                continue
            unmatched = sro_calendar.load(conn, series_id, args.season, events)
            log.info("loaded %d events for %s %d (%d without a circuit)",
                     len(events), series_id, args.season, unmatched)

        stay_count, snapshot_count = stays.load(conn, date.today())
        log.info("wrote %d stays and %d price snapshots", stay_count, snapshot_count)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
