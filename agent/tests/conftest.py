from pathlib import Path
from types import SimpleNamespace

import pytest

from trackside_agent.alerts import AlertGroup
from trackside_agent.config import Settings

RUNBOOKS = Path(__file__).resolve().parents[2] / "docs" / "runbooks"


def webhook(status="firing", alertname="ApiDown", **labels):
    return {
        "version": "4",
        "groupKey": f'{{}}:{{alertname="{alertname}"}}',
        "status": status,
        "receiver": "triage-agent",
        "commonLabels": {"alertname": alertname, "severity": "page", **labels},
        "commonAnnotations": {"summary": "The Trackside API is not answering scrapes.",
                              "runbook": "docs/runbooks/api.md"},
        "alerts": [{
            "status": status,
            "labels": {"alertname": alertname, "severity": "page", "job": "api", **labels},
            "annotations": {"summary": "The Trackside API is not answering scrapes.",
                            "runbook": "docs/runbooks/api.md"},
            "startsAt": "2026-11-19T10:00:00Z",
            "fingerprint": "abc123",
        }],
    }


@pytest.fixture
def group():
    return AlertGroup.from_webhook(webhook())


@pytest.fixture
def settings(tmp_path):
    return Settings(database_url="postgresql://unused", readonly_database_url="postgresql://unused",
                    runbooks_dir=RUNBOOKS, outbox_dir=tmp_path / "outbox", anthropic_api_key="test-key")


def message(*blocks, stop_reason="end_turn", input_tokens=1000, output_tokens=200, model="claude-opus-5-5"):
    """A stand-in for one BetaMessage yielded by the tool runner."""
    return SimpleNamespace(
        content=list(blocks), stop_reason=stop_reason, model=model,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                              cache_read_input_tokens=0, cache_creation_input_tokens=0))


def text(value):
    return SimpleNamespace(type="text", text=value)


def tool_use(name="query_prometheus"):
    return SimpleNamespace(type="tool_use", name=name, id="toolu_1", input={})


class FakeClient:
    """Records the tool runner's arguments and replays scripted messages."""

    def __init__(self, messages):
        self.messages = messages
        self.kwargs = None
        self.beta = SimpleNamespace(messages=SimpleNamespace(tool_runner=self._runner))

    def _runner(self, **kwargs):
        self.kwargs = kwargs
        return iter(self.messages)
