"""Investigate one alert group with Claude and the read-only tools.

Cost is bounded three ways: a monthly budget checked before each run, a
per-incident budget checked after every turn, and a cap on turns. When Claude
cannot run (no key, over budget, API error, refusal, unusable output) the agent
falls back to an evidence-only report built without a model, so every incident
still gets a ticket with the alert, the runbook, and what else is firing.
"""

import json
import logging
import time
from dataclasses import dataclass, field

import anthropic
from anthropic import beta_tool

from .alerts import AlertGroup
from .config import Settings
from .tools import Investigator

log = logging.getLogger(__name__)

# Claude Opus 5.5, USD per million tokens. Cache writes use the 5-minute rate.
PRICES = {"input": 4.00, "output": 20.00, "cache_read": 0.20, "cache_write": 5.00}

SYSTEM_PROMPT = """\
You are the on-call triage agent for Trackside, a portfolio web app that shows GT3
race calendars, lap-time rankings derived from timing archives, and sample places to
stay near each circuit. An alert has fired. Investigate it and write the incident
report an on-call engineer will read first.

The system:
- api: Go HTTP API (Prometheus job "api"), reads Postgres through a TCP proxy.
- web: React frontend served by nginx.
- db: Postgres 17. Schemas: public (series, circuits, events, stays,
  stay_price_snapshots), raw (timing_files manifest), staging (sessions,
  session_entries, laps), marts (lap_quality, circuit_pace, driver_pace,
  entry_pace), ops (dq_results, incidents, agent_runs).
- Airflow 3 with two daily DAGs: calendar_and_stays (05:00 UTC) and
  timing_archive (06:00 UTC: discover -> download -> load -> refresh_marts ->
  quality_checks -> report_success). Data-quality results land in ops.dq_results
  and are pushed to Prometheus as trackside_dq_check_status (0 pass, 1 warn,
  2 fail); a failing check does not fail the DAG.
- Prometheus scrapes api, pushgateway (pipeline outcomes), airflow (via
  statsd-exporter), agent, alertmanager. Loki holds every container's stdout,
  labelled {service="<compose service>"}.

How to work:
- Start from the runbook the alert names; it lists the usual causes.
- Gather evidence before concluding: confirm the symptom, then test the likely
  causes the runbook lists against metrics, logs, task state, or data.
- Prefer a few targeted queries over many broad ones. Stop when the evidence
  points clearly at a cause, or when the remaining hypotheses cannot be tested
  with your tools.
- Your tools only read. You cannot restart, rerun, or change anything, so do not
  claim to have. Recommend actions for a human instead.
- Distinguish what you observed from what you infer, and say how confident you
  are. "Unknown" with good evidence of what was ruled out is a useful answer.
- Times are UTC.

The report becomes a public GitHub issue. Never include lap-by-lap rows, individual
lap times, or the contents of raw timing files (that data is licensed and private);
cite counts and aggregates instead. Never include credentials or tokens.

When you are done, reply with only the report as JSON in the required format."""

REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "One line naming the problem, not the alert."},
        "summary": {"type": "string", "description": "Two or three sentences: what is wrong, since when, impact."},
        "likely_cause": {"type": "string"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Tool and query, e.g. 'Prometheus: up{job=\"api\"}'."},
                    "finding": {"type": "string"},
                },
                "required": ["source", "finding"],
                "additionalProperties": False,
            },
        },
        "ruled_out": {"type": "array", "items": {"type": "string"}},
        "next_steps": {"type": "array", "items": {"type": "string"},
                       "description": "Actions for a human, most useful first."},
        "runbook": {"type": "string", "description": "Path of the runbook that applies."},
    },
    "required": ["title", "summary", "likely_cause", "confidence", "evidence", "ruled_out", "next_steps", "runbook"],
    "additionalProperties": False,
}


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def add(self, usage) -> None:
        self.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        self.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.cache_write_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0

    @property
    def cost_usd(self) -> float:
        return (self.input_tokens * PRICES["input"] + self.output_tokens * PRICES["output"]
                + self.cache_read_tokens * PRICES["cache_read"]
                + self.cache_write_tokens * PRICES["cache_write"]) / 1_000_000


@dataclass
class TriageResult:
    report: dict
    mode: str                      # agent | fallback
    outcome: str                   # ok | no_api_key | over_budget | incident_budget | api_error | refusal | bad_output
    model: str | None = None
    tool_calls: int = 0
    duration_s: float = 0.0
    usage: Usage = field(default_factory=Usage)


def build_tools(inv: Investigator) -> list:
    """Wrap the investigator's methods as tools for the SDK's tool runner."""

    @beta_tool
    def query_prometheus(query: str, minutes: int = 0) -> str:
        """Run a PromQL query. Instant when minutes is 0, otherwise over the last N
        minutes, summarised per series (min, max, last, samples).

        Args:
            query: PromQL expression, e.g. 'up' or 'rate(http_requests_total[5m])'.
            minutes: Range length in minutes; 0 for an instant query.
        """
        return inv.query_prometheus(query, minutes)

    @beta_tool
    def query_loki(query: str, minutes: int = 60, limit: int = 40) -> str:
        """Search container logs with LogQL, newest first.

        Args:
            query: LogQL, e.g. '{service="api"} |= "error"' or '{service=~"airflow.*"}'.
            minutes: How far back to search.
            limit: Maximum lines to return (up to 200).
        """
        return inv.query_loki(query, minutes, limit)

    @beta_tool
    def airflow_runs(dag_id: str, limit: int = 5) -> str:
        """Recent runs of an Airflow DAG with task states for runs that did not
        succeed, plus any DAG import errors.

        Args:
            dag_id: 'timing_archive' or 'calendar_and_stays'.
            limit: Number of recent runs.
        """
        return inv.airflow_runs(dag_id, limit)

    @beta_tool
    def airflow_task_log(dag_id: str, run_id: str, task_id: str, try_number: int) -> str:
        """Log of one Airflow task attempt, with exceptions and their stack frames.

        Args:
            dag_id: The DAG.
            run_id: The run, as airflow_runs prints it.
            task_id: The task.
            try_number: The attempt, as airflow_runs prints it.
        """
        return inv.airflow_task_log(dag_id, run_id, task_id, try_number)

    @beta_tool
    def query_database(sql: str) -> str:
        """Run one read-only SELECT against the app database (max 50 rows, 5 s timeout).

        Args:
            sql: A single SELECT or WITH query. Aggregate rather than listing lap rows.
        """
        return inv.query_database(sql)

    @beta_tool
    def service_starts(hours: int = 24) -> str:
        """When each scraped service last started and how often it restarted.

        Args:
            hours: Window for counting restarts.
        """
        return inv.service_starts(hours)

    @beta_tool
    def read_runbook(name: str) -> str:
        """Read a runbook by file name, e.g. 'api.md'. Unknown names list the available ones.

        Args:
            name: Runbook file name.
        """
        return inv.read_runbook(name)

    return [query_prometheus, query_loki, airflow_runs, airflow_task_log, query_database,
            service_starts, read_runbook]


def fallback_report(group: AlertGroup, inv: Investigator, reason: str) -> dict:
    """An evidence-only report, built without a model."""
    evidence = [{"source": "Alertmanager", "finding": group.brief()}]
    try:
        firing = inv.query_prometheus('ALERTS{alertstate="firing"}')
        evidence.append({"source": 'Prometheus: ALERTS{alertstate="firing"}', "finding": firing})
    except Exception as error:  # noqa: BLE001 - a fallback must not fail
        evidence.append({"source": "Prometheus", "finding": f"Unreachable: {error}"})
    return {
        "title": f"{group.alertname}: {group.summary}",
        "summary": f"{group.summary} The triage agent did not investigate: {reason}.",
        "likely_cause": "Not investigated.",
        "confidence": "low",
        "evidence": evidence,
        "ruled_out": [],
        "next_steps": [f"Follow the runbook: {group.runbook}" if group.runbook else "No runbook is linked; triage by hand."],
        "runbook": group.runbook or "",
    }


FALLBACK_REASONS = {
    "no_api_key": "no Anthropic API key is configured",
    "over_budget": "this month's agent budget is used up",
    "incident_budget": "the investigation reached its per-incident budget before finishing",
    "api_error": "the Claude API returned an error",
    "refusal": "the model declined the request",
    "bad_output": "the model's report could not be parsed",
}


def investigate(group: AlertGroup, settings: Settings, inv: Investigator, month_spend_usd: float,
                client: anthropic.Anthropic | None = None) -> TriageResult:
    started = time.monotonic()

    def fallback(outcome: str, **kwargs) -> TriageResult:
        return TriageResult(report=fallback_report(group, inv, FALLBACK_REASONS[outcome]), mode="fallback",
                            outcome=outcome, duration_s=time.monotonic() - started, **kwargs)

    if not settings.anthropic_api_key and client is None:
        return fallback("no_api_key")
    if month_spend_usd >= settings.monthly_budget_usd:
        return fallback("over_budget")

    client = client or anthropic.Anthropic(api_key=settings.anthropic_api_key)
    usage, tool_calls, final, model = Usage(), 0, None, settings.model
    try:
        runner = client.beta.messages.tool_runner(
            model=settings.model,
            max_tokens=16000,
            max_iterations=settings.max_iterations,
            system=SYSTEM_PROMPT,
            tools=build_tools(inv),
            messages=[{"role": "user", "content": group.brief()}],
            output_config={"effort": settings.effort, "format": {"type": "json_schema", "schema": REPORT_SCHEMA}},
            # The system prompt and tools are identical for every incident.
            cache_control={"type": "ephemeral"},
            # A safety-classifier decline is retried on a fallback model instead of ending the run.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        for message in runner:
            usage.add(message.usage)
            model = message.model
            tool_calls += sum(1 for b in message.content if b.type == "tool_use")
            final = message
            if usage.cost_usd >= settings.per_incident_budget_usd and message.stop_reason == "tool_use":
                log.warning("incident budget reached after %d tool calls", tool_calls)
                return fallback("incident_budget", model=model, tool_calls=tool_calls, usage=usage)
    except anthropic.APIError as error:
        log.error("Claude API error: %s", error)
        return fallback("api_error", model=model, tool_calls=tool_calls, usage=usage)

    common = {"model": model, "tool_calls": tool_calls, "usage": usage}
    if final is None:
        return fallback("bad_output", **common)
    if final.stop_reason == "refusal":
        return fallback("refusal", **common)
    text = next((b.text for b in final.content if b.type == "text"), "")
    try:
        report = json.loads(text)
        if not isinstance(report, dict) or not {"title", "summary", "evidence"} <= report.keys():
            raise ValueError("missing fields")
    except ValueError:
        log.error("unusable report (stop_reason %s): %.300s", final.stop_reason, text)
        return fallback("bad_output", **common)
    return TriageResult(report=report, mode="agent", outcome="ok", duration_s=time.monotonic() - started, **common)
