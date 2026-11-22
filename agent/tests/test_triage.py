import json

import anthropic
import httpx2
import pytest

from trackside_agent import triage
from trackside_agent.tools import Investigator

from .conftest import FakeClient, message, text, tool_use

REPORT = {
    "title": "API cannot reach Postgres", "summary": "The API is down.", "likely_cause": "db stopped",
    "confidence": "high", "evidence": [{"source": "Prometheus: up", "finding": "api 0"}],
    "ruled_out": [], "next_steps": ["Start db"], "runbook": "docs/runbooks/api.md",
}


class OfflineInvestigator(Investigator):
    """Fallback reports query Prometheus; answer without a network."""

    def query_prometheus(self, query, minutes=0):
        return 'ALERTS{alertname="ApiDown"} = 1'


@pytest.fixture
def inv(settings):
    return OfflineInvestigator(settings)


def test_a_report_comes_back_with_usage_and_cost(group, settings, inv):
    client = FakeClient([
        message(tool_use(), tool_use("query_loki"), stop_reason="tool_use"),
        message(text(json.dumps(REPORT))),
    ])
    result = triage.investigate(group, settings, inv, month_spend_usd=0, client=client)

    assert (result.mode, result.outcome) == ("agent", "ok")
    assert result.report["title"] == "API cannot reach Postgres"
    assert result.tool_calls == 2
    assert result.usage.input_tokens == 2000
    assert result.usage.cost_usd == pytest.approx((2000 * 4 + 400 * 20) / 1e6)


def test_the_request_is_read_only_cached_and_bounded(group, settings, inv):
    client = FakeClient([message(text(json.dumps(REPORT)))])
    triage.investigate(group, settings, inv, month_spend_usd=0, client=client)
    kw = client.kwargs

    assert kw["model"] == "claude-opus-5-5"
    assert kw["max_iterations"] == settings.max_iterations
    assert kw["cache_control"] == {"type": "ephemeral"}
    assert kw["output_config"]["format"]["schema"] is triage.REPORT_SCHEMA
    assert kw["fallbacks"] == "default"
    assert "ApiDown" in kw["messages"][0]["content"]
    names = {t.name for t in kw["tools"]}
    assert names == {"query_prometheus", "query_loki", "airflow_runs", "airflow_task_log", "query_database",
                     "service_starts", "read_runbook"}


def test_tool_schemas_come_from_the_signatures(inv):
    tools = {t.name: t.to_dict() for t in triage.build_tools(inv)}
    schema = tools["airflow_task_log"]["input_schema"]
    assert schema["required"] == ["dag_id", "run_id", "task_id", "try_number"]
    assert schema["properties"]["try_number"]["type"] == "integer"
    assert "PromQL" in tools["query_prometheus"]["description"]


def test_no_key_means_an_evidence_only_report(group, settings, inv):
    no_key = settings.__class__(**{**settings.__dict__, "anthropic_api_key": None})
    result = triage.investigate(group, no_key, inv, month_spend_usd=0)

    assert (result.mode, result.outcome) == ("fallback", "no_api_key")
    assert "no Anthropic API key" in result.report["summary"]
    assert result.report["runbook"] == "docs/runbooks/api.md"
    assert any("ALERTS" in e["source"] for e in result.report["evidence"])


def test_the_monthly_budget_is_checked_before_calling_claude(group, settings, inv):
    client = FakeClient([])
    result = triage.investigate(group, settings, inv, month_spend_usd=settings.monthly_budget_usd, client=client)
    assert result.outcome == "over_budget"
    assert client.kwargs is None  # Claude was never called


def test_an_expensive_investigation_stops_at_the_incident_budget(group, settings, inv):
    pricey = dict(input_tokens=120_000, output_tokens=10_000, stop_reason="tool_use")  # $0.68 per turn
    client = FakeClient([message(tool_use(), **pricey), message(tool_use(), **pricey),
                         message(text(json.dumps(REPORT)))])
    result = triage.investigate(group, settings, inv, month_spend_usd=0, client=client)

    assert result.outcome == "incident_budget"
    assert result.tool_calls == 2
    assert result.usage.cost_usd >= settings.per_incident_budget_usd  # still recorded


@pytest.mark.parametrize("final, outcome", [
    (message(text("not json")), "bad_output"),
    (message(text('{"title": "x"}')), "bad_output"),
    (message(stop_reason="refusal"), "refusal"),
])
def test_unusable_endings_fall_back(group, settings, inv, final, outcome):
    result = triage.investigate(group, settings, inv, month_spend_usd=0, client=FakeClient([final]))
    assert (result.mode, result.outcome) == ("fallback", outcome)
    assert result.usage.input_tokens == 1000  # spend is still counted


def test_api_errors_fall_back(group, settings, inv):
    class Failing(FakeClient):
        def _runner(self, **kwargs):
            raise anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com"))

    result = triage.investigate(group, settings, inv, month_spend_usd=0, client=Failing([]))
    assert result.outcome == "api_error"
