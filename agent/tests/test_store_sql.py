"""Incident bookkeeping against a real Postgres. Needs TEST_DATABASE_URL, a server
where the role may create databases; skipped otherwise."""

import os
import uuid
from pathlib import Path

import psycopg
import pytest

from trackside_agent.alerts import AlertGroup
from trackside_agent.store import Store
from trackside_agent.triage import TriageResult, Usage

from .conftest import webhook

MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "migrations"
ADMIN_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="TEST_DATABASE_URL not set")


@pytest.fixture
def store():
    name = f"trackside_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = psycopg.conninfo.make_conninfo(ADMIN_URL, dbname=name)
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            for path in sorted(MIGRATIONS.glob("*.sql")):
                conn.execute(path.read_text(encoding="utf-8"))
        yield Store(url)
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def result(cost_tokens=1_000_000):
    return TriageResult(report={"title": "t"}, mode="agent", outcome="ok", model="claude-opus-5-5",
                        usage=Usage(input_tokens=cost_tokens))


def test_one_open_incident_per_group_and_a_new_one_after_it_resolves(store):
    group = AlertGroup.from_webhook(webhook())
    first, created = store.open_incident(group)
    again, created_again = store.open_incident(group)
    assert created and not created_again and again.id == first.id

    store.save_outcome(first, result(), "https://github.com/o/r/issues/1", chat_sent=True)
    resolved = store.resolve(group.group_key)
    assert resolved.ticket_url == "https://github.com/o/r/issues/1"
    assert store.resolve(group.group_key) is None

    reopened, created = store.open_incident(group)
    assert created and reopened.id != first.id


def test_month_spend_sums_this_months_runs(store):
    incident, _ = store.open_incident(AlertGroup.from_webhook(webhook()))
    store.save_outcome(incident, result(1_000_000), None, False)   # $4.00
    store.save_outcome(incident, result(250_000), None, False)     # $1.00
    assert store.month_spend_usd() == pytest.approx(5.0)
