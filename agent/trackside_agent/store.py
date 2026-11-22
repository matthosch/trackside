"""The agent's own records in ops.incidents and ops.agent_runs. This is the only
place the agent writes to the database, and only to these two tables."""

from dataclasses import dataclass

import psycopg
from psycopg.types.json import Jsonb

from .alerts import AlertGroup
from .triage import TriageResult


@dataclass(frozen=True)
class Incident:
    id: int
    group_key: str
    ticket_url: str | None


class Store:
    def __init__(self, database_url: str):
        self.url = database_url

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.url, autocommit=True, connect_timeout=5)

    def open_incident(self, group: AlertGroup) -> tuple[Incident, bool]:
        """The group's open incident, creating it if there is none. Returns (incident, created)."""
        with self._connect() as conn:
            row = conn.execute(
                """INSERT INTO ops.incidents (group_key, alertname, labels)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (group_key) WHERE status = 'firing' DO NOTHING
                   RETURNING id, ticket_url""",
                (group.group_key, group.alertname, Jsonb(group.common_labels)),
            ).fetchone()
            if row:
                return Incident(row[0], group.group_key, row[1]), True
            row = conn.execute(
                "SELECT id, ticket_url FROM ops.incidents WHERE group_key = %s AND status = 'firing'",
                (group.group_key,),
            ).fetchone()
            return Incident(row[0], group.group_key, row[1]), False

    def save_outcome(self, incident: Incident, result: TriageResult, ticket_url: str | None, chat_sent: bool) -> None:
        u = result.usage
        with self._connect() as conn, conn.transaction():
            conn.execute(
                "UPDATE ops.incidents SET report = %s, ticket_url = %s, chat_sent = %s WHERE id = %s",
                (Jsonb(result.report), ticket_url, chat_sent, incident.id),
            )
            conn.execute(
                """INSERT INTO ops.agent_runs (incident_id, duration_s, mode, outcome, model, tool_calls,
                       input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cost_usd)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (incident.id, result.duration_s, result.mode, result.outcome, result.model, result.tool_calls,
                 u.input_tokens, u.output_tokens, u.cache_read_tokens, u.cache_write_tokens, round(u.cost_usd, 4)),
            )

    def resolve(self, group_key: str) -> Incident | None:
        with self._connect() as conn:
            row = conn.execute(
                """UPDATE ops.incidents SET status = 'resolved', resolved_at = now()
                   WHERE group_key = %s AND status = 'firing'
                   RETURNING id, ticket_url""",
                (group_key,),
            ).fetchone()
        return Incident(row[0], group_key, row[1]) if row else None

    def month_spend_usd(self) -> float:
        with self._connect() as conn:
            (spend,) = conn.execute(
                "SELECT coalesce(sum(cost_usd), 0) FROM ops.agent_runs WHERE started_at >= date_trunc('month', now())"
            ).fetchone()
        return float(spend)
