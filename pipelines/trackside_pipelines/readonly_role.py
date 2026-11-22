"""The database role the triage agent's SQL tool connects as.

It can read every schema and write nothing. Postgres enforces that three ways:
SELECT-only grants, read-only transactions by default, and a short statement
timeout. The agent adds a fourth (one statement per call, inside a READ ONLY
transaction), but the database does not rely on the agent behaving.
"""

import psycopg
from psycopg import sql

ROLE = "trackside_readonly"
SCHEMAS = ("public", "raw", "staging", "marts", "ops")


def ensure(conn: psycopg.Connection, password: str) -> None:
    """Create or update the role and its grants. Safe to run on every seed."""
    role = sql.Identifier(ROLE)
    with conn.transaction():
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ROLE,)).fetchone()
        verb = "ALTER" if exists else "CREATE"
        conn.execute(sql.SQL(verb + " ROLE {} LOGIN PASSWORD {}").format(role, sql.Literal(password)))
        conn.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(role))
        conn.execute(sql.SQL("ALTER ROLE {} SET statement_timeout = '5s'").format(role))
        conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(conn.info.dbname), role))
        for schema in SCHEMAS:
            s = sql.Identifier(schema)
            conn.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(s, role))
            # ALL TABLES covers views and materialized views too.
            conn.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(s, role))
            conn.execute(sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT SELECT ON TABLES TO {}").format(s, role))
