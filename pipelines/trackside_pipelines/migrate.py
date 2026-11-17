"""Apply SQL migrations in filename order, once each."""

import logging
from pathlib import Path

import psycopg

log = logging.getLogger(__name__)


def migrate(conn: psycopg.Connection, migrations_dir: Path) -> list[str]:
    """Apply any migration not yet recorded. Returns the names applied."""
    with conn.transaction():
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
    done = {row[0] for row in conn.execute("SELECT name FROM schema_migrations")}

    applied = []
    for path in sorted(migrations_dir.glob("*.sql")):
        if path.name in done:
            continue
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
        log.info("applied migration %s", path.name)
        applied.append(path.name)
    return applied
