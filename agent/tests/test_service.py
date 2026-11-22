from trackside_agent.alerts import AlertGroup
from trackside_agent.service import Outputs, Service
from trackside_agent.sinks import Discord, GitHubIssues, Outbox
from trackside_agent.store import Incident
from trackside_agent.triage import TriageResult, Usage

from .conftest import webhook

REPORT = {"title": "API cannot reach Postgres", "summary": "Down since 10:00.", "likely_cause": "db stopped",
          "confidence": "high", "evidence": [{"source": "Prometheus: up", "finding": "0"}], "ruled_out": [],
          "next_steps": ["Start the db container"], "runbook": "docs/runbooks/api.md"}


class FakeStore:
    def __init__(self):
        self.open = {}
        self.saved = []
        self.next_id = 1

    def open_incident(self, group):
        if group.group_key in self.open:
            return self.open[group.group_key], False
        incident = Incident(self.next_id, group.group_key, None)
        self.next_id += 1
        self.open[group.group_key] = incident
        return incident, True

    def save_outcome(self, incident, result, ticket_url, chat_sent):
        self.open[incident.group_key] = Incident(incident.id, incident.group_key, ticket_url)
        self.saved.append((incident.id, result.outcome, ticket_url, chat_sent))

    def resolve(self, group_key):
        return self.open.pop(group_key, None)

    def month_spend_usd(self):
        return 0.0


class Recorder:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def __call__(self, method, url, body, headers):
        self.calls.append((method, url, body))
        if self.fail:
            raise OSError("network down")
        return {"html_url": "https://github.com/matthosch/trackside/issues/7"}


def fake_investigate(group, settings, inv, month_spend):
    return TriageResult(report=REPORT, mode="agent", outcome="ok", model="claude-opus-5-5", tool_calls=4,
                        duration_s=30, usage=Usage(input_tokens=10_000, output_tokens=1_000))


def service(settings, github_fail=False):
    gh, dc = Recorder(fail=github_fail), Recorder()
    outputs = Outputs(Outbox(settings.outbox_dir),
                      GitHubIssues("token", "matthosch/trackside", send=gh),
                      Discord("https://discord.com/api/webhooks/1/abc", send=dc))
    store = FakeStore()
    return Service(settings, store, inv=None, outputs=outputs, investigate=fake_investigate), store, gh, dc


def test_a_new_alert_is_triaged_once_and_sent_everywhere(settings):
    svc, store, gh, dc = service(settings)
    group = AlertGroup.from_webhook(webhook())

    assert svc.handle(group) == "triaged:agent:ok"
    assert svc.handle(group) == "already_open"  # repeats of an open incident are ignored

    (method, url, body), = gh.calls
    assert url.endswith("/repos/matthosch/trackside/issues")
    assert body["title"] == "[incident] API cannot reach Postgres"
    assert body["labels"] == ["incident", "severity:page", "alert:ApiDown"]
    assert "docs/runbooks/api.md" in body["body"] and "4 read-only tool calls" in body["body"]
    (_, _, chat), = dc.calls
    assert "issues/7" in chat["content"] and chat["allowed_mentions"] == {"parse": []}
    assert store.saved == [(1, "ok", "https://github.com/matthosch/trackside/issues/7", True)]
    assert (settings.outbox_dir / "incident-0001.md").read_text(encoding="utf-8").startswith("# [incident]")


def test_resolving_closes_the_issue_and_says_so_in_chat(settings):
    svc, _, gh, dc = service(settings)
    svc.handle(AlertGroup.from_webhook(webhook()))
    assert svc.handle(AlertGroup.from_webhook(webhook(status="resolved"))) == "resolved"

    assert [c[0] for c in gh.calls] == ["POST", "POST", "PATCH"]
    assert gh.calls[1][1].endswith("/issues/7/comments")
    assert gh.calls[2][2] == {"state": "closed", "state_reason": "completed"}
    assert dc.calls[-1][2]["content"].startswith("✅ **Resolved:** `ApiDown`")
    assert svc.handle(AlertGroup.from_webhook(webhook(status="resolved"))) == "nothing_open"


def test_a_failing_output_does_not_stop_the_others(settings):
    svc, store, gh, dc = service(settings, github_fail=True)
    svc.handle(AlertGroup.from_webhook(webhook()))
    assert len(dc.calls) == 1  # Discord still told
    assert store.saved == [(1, "ok", None, True)]


def test_webhook_payloads_parse(group):
    assert group.alertname == "ApiDown" and group.severity == "page"
    assert group.runbook == "docs/runbooks/api.md"
    assert "job': 'api'" in group.brief()
