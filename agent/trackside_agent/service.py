"""Handle Alertmanager notifications: open or resolve incidents, investigate new
ones, and send the results to every configured output."""

import logging
import time
from dataclasses import dataclass

from prometheus_client import Counter, Gauge, Histogram

from . import render, triage
from .alerts import AlertGroup
from .config import Settings
from .sinks import Discord, GitHubIssues, Outbox
from .store import Store
from .tools import Investigator

log = logging.getLogger(__name__)

RUNS = Counter("trackside_agent_runs_total", "Investigations, by mode and outcome.", ["mode", "outcome"])
RUN_SECONDS = Histogram("trackside_agent_run_duration_seconds", "Time to investigate one incident.",
                        buckets=(5, 15, 30, 60, 120, 300, 600))
TOKENS = Counter("trackside_agent_tokens_total", "Claude tokens used, by kind.", ["kind"])
COST = Counter("trackside_agent_cost_usd_total", "Claude spend in US dollars.")
MONTH_SPEND = Gauge("trackside_agent_month_spend_usd", "Claude spend so far this calendar month.")
MONTH_BUDGET = Gauge("trackside_agent_month_budget_usd", "Monthly Claude budget.")
NOTIFICATIONS = Counter("trackside_agent_notifications_total", "Alertmanager notifications handled.",
                        ["status", "action"])
OUTPUT_FAILURES = Counter("trackside_agent_output_failures_total", "Failed deliveries, by output.", ["output"])


@dataclass
class Outputs:
    outbox: Outbox
    github: GitHubIssues | None = None
    discord: Discord | None = None

    @classmethod
    def from_settings(cls, s: Settings) -> "Outputs":
        github = GitHubIssues(s.github_token, s.github_repo) if s.github_token and s.github_repo else None
        discord = Discord(s.discord_webhook_url) if s.discord_webhook_url else None
        return cls(Outbox(s.outbox_dir), github, discord)


class Service:
    def __init__(self, settings: Settings, store: Store, inv: Investigator, outputs: Outputs, investigate=None):
        self.s = settings
        self.store = store
        self.inv = inv
        self.outputs = outputs
        self._investigate = investigate or triage.investigate
        MONTH_BUDGET.set(settings.monthly_budget_usd)

    def refresh_spend(self) -> float:
        spend = self.store.month_spend_usd()
        MONTH_SPEND.set(spend)
        return spend

    def handle(self, group: AlertGroup) -> str:
        """Process one notification. Returns what was done, for logs and tests."""
        if group.status == "resolved":
            action = self._resolve(group)
        else:
            action = self._fire(group)
        NOTIFICATIONS.labels(group.status, action).inc()
        log.info("notification handled", extra={"alertname": group.alertname, "status": group.status,
                                                "action": action})
        return action

    def _fire(self, group: AlertGroup) -> str:
        incident, created = self.store.open_incident(group)
        if not created:
            return "already_open"

        started = time.monotonic()
        result = self._investigate(group, self.s, self.inv, self.refresh_spend())
        RUN_SECONDS.observe(time.monotonic() - started)
        RUNS.labels(result.mode, result.outcome).inc()
        u = result.usage
        for kind, value in (("input", u.input_tokens), ("output", u.output_tokens),
                            ("cache_read", u.cache_read_tokens), ("cache_write", u.cache_write_tokens)):
            TOKENS.labels(kind).inc(value)
        COST.inc(u.cost_usd)

        title = render.issue_title(result.report)
        body = render.issue_body(group, result, self.s)
        path = self.outputs.outbox.write(incident.id, title, body)

        ticket_url = None
        if self.outputs.github:
            try:
                labels = ["incident", f"severity:{group.severity}", f"alert:{group.alertname}"]
                ticket_url = self.outputs.github.create(title, body, labels)
            except Exception:  # noqa: BLE001 - one failed output must not stop the rest
                OUTPUT_FAILURES.labels("github").inc()
                log.exception("could not create GitHub issue")

        chat_sent = False
        if self.outputs.discord:
            try:
                self.outputs.discord.post(render.chat_message(group, result, ticket_url))
                chat_sent = True
            except Exception:  # noqa: BLE001
                OUTPUT_FAILURES.labels("discord").inc()
                log.exception("could not post to Discord")

        self.store.save_outcome(incident, result, ticket_url, chat_sent)
        self.refresh_spend()
        log.info("incident triaged", extra={"incident": incident.id, "mode": result.mode, "outcome": result.outcome,
                                            "tool_calls": result.tool_calls, "cost_usd": round(u.cost_usd, 4),
                                            "ticket": ticket_url, "outbox": str(path)})
        return f"triaged:{result.mode}:{result.outcome}"

    def _resolve(self, group: AlertGroup) -> str:
        incident = self.store.resolve(group.group_key)
        if incident is None:
            return "nothing_open"
        note = "Resolved: Alertmanager reports every alert in this group as resolved."
        self.outputs.outbox.append(incident.id, f"---\n{note}")
        if self.outputs.github and incident.ticket_url:
            try:
                self.outputs.github.resolve(incident.ticket_url, note)
            except Exception:  # noqa: BLE001
                OUTPUT_FAILURES.labels("github").inc()
                log.exception("could not close GitHub issue")
        if self.outputs.discord:
            try:
                self.outputs.discord.post(render.resolved_message(group.alertname, incident.ticket_url))
            except Exception:  # noqa: BLE001
                OUTPUT_FAILURES.labels("discord").inc()
                log.exception("could not post to Discord")
        return "resolved"
