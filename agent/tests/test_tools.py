import json
import urllib.parse

import pytest

from trackside_agent.tools import Investigator, clip

NOW = 1_795_000_000.0


class FakeHttp:
    """Answers GETs by path prefix and records every URL requested."""

    def __init__(self, routes):
        self.routes = routes
        self.urls = []

    def __call__(self, url, headers):
        self.urls.append((url, headers))
        path = urllib.parse.urlparse(url).path
        for prefix, body in self.routes.items():
            if path.startswith(prefix):
                return json.dumps(body).encode()
        raise AssertionError(f"unexpected GET {url}")


def investigator(settings, routes):
    http = FakeHttp(routes)
    return Investigator(settings, get=http, clock=lambda: NOW), http


def test_instant_prometheus_query(settings):
    inv, http = investigator(settings, {"/api/v1/query": {"data": {"result": [
        {"metric": {"job": "api", "__name__": "up"}, "value": [NOW, "0"]}]}}})
    out = inv.query_prometheus("up")
    assert out == '{__name__="up", job="api"} = 0 at 2026-11-18 11:06:40Z'
    assert "query=up" in http.urls[0][0]


def test_range_query_is_summarised(settings):
    values = [[NOW - 600 + i * 15, str(i)] for i in range(41)]
    inv, http = investigator(settings, {"/api/v1/query_range": {"data": {"result": [
        {"metric": {"job": "api"}, "values": values}]}}})
    out = inv.query_prometheus("rate(x[5m])", minutes=10)
    assert out.startswith('{job="api"}: min 0, max 40, last 40; samples:')
    assert out.count(",") < 15  # a handful of samples, not all 41
    query = urllib.parse.parse_qs(urllib.parse.urlparse(http.urls[0][0]).query)
    assert float(query["start"][0]) == NOW - 600


def test_empty_results_say_so(settings):
    inv, _ = investigator(settings, {"/api/v1/query": {"data": {"result": []}}})
    assert inv.query_prometheus("nothing") == "No series matched."


def test_loki_lines_are_newest_first_with_their_service(settings):
    inv, _ = investigator(settings, {"/loki/api/v1/query_range": {"data": {"result": [
        {"stream": {"service": "api"}, "values": [[str(int(NOW * 1e9) - 10**9), "older"],
                                                    [str(int(NOW * 1e9)), "newer"]]}]}}})
    out = inv.query_loki('{service="api"}', minutes=5)
    assert out.splitlines()[0].endswith("[api] newer")
    assert out.splitlines()[1].endswith("[api] older")


def test_airflow_runs_show_tasks_only_for_runs_that_did_not_succeed(settings):
    inv, http = investigator(settings, {
        "/auth/token": {"access_token": "tok"},
        "/api/v2/dags/timing_archive/dagRuns/manual__1/taskInstances": {"task_instances": [
            {"task_id": "load", "state": "failed", "try_number": 3, "duration": 12.5}]},
        "/api/v2/dags/timing_archive/dagRuns": {"dag_runs": [
            {"dag_run_id": "manual__1", "state": "failed", "start_date": "a", "end_date": "b"},
            {"dag_run_id": "manual__0", "state": "success", "start_date": "c", "end_date": "d"}]},
        "/api/v2/importErrors": {"import_errors": []},
    })
    out = inv.airflow_runs("timing_archive")
    assert "manual__1: failed" in out and "  - load: failed (try 3, 12s)" in out
    assert out.count("  - ") == 1
    assert http.urls[1][1] == {"Authorization": "Bearer tok"}


def test_task_logs_keep_exceptions_and_drop_noise(settings):
    entries = [{"event": "::group::x"}] + [
        {"timestamp": f"t{i}", "level": "info", "logger": "task", "event": f"line {i}"} for i in range(30)
    ] + [{"timestamp": "t99", "level": "error", "logger": "task", "event": "Task failed with exception",
          "error_detail": [{"exc_type": "URLError", "exc_value": "Name or service not known",
                            "frames": [{"filename": "/x/sro_calendar.py", "lineno": 42, "name": "fetch"}]}]}]
    inv, _ = investigator(settings, {"/auth/token": {"access_token": ""},
                                     "/api/v2/dags/": {"content": entries}})
    out = inv.airflow_task_log("calendar_and_stays", "scheduled__2026-11-18T05:00:00+00:00", "refresh_calendar", 3)
    assert "line 0" not in out and "line 29" in out
    assert "URLError: Name or service not known at sro_calendar.py:42 fetch" in out


@pytest.mark.parametrize("sql", [
    "SELECT 1; DROP TABLE staging.laps",
    "DELETE FROM staging.laps",
    "update ops.incidents set status = 'resolved'",
    "SET default_transaction_read_only = off",
])
def test_database_tool_refuses_anything_but_one_read(settings, sql):
    inv, _ = investigator(settings, {})
    assert inv.query_database(sql).startswith("Refused")


def test_runbooks_cannot_escape_their_folder(settings):
    inv, _ = investigator(settings, {})
    assert "Runbook: a pipeline is stale" in inv.read_runbook("pipeline-stale.md")
    assert inv.read_runbook("docs/runbooks/pipeline-stale.md").startswith("# Runbook")
    assert inv.read_runbook("../../.env").startswith("No runbook named")
    assert "pipeline-stale.md" in inv.list_runbooks()


def test_service_starts_are_dates_with_restart_counts(settings):
    inv, http = investigator(settings, {"/api/v1/query": {"data": {"result": [
        {"metric": {"job": "api"}, "value": [NOW, str(NOW - 7200)]}]}}})
    out = inv.service_starts(24)
    assert out.startswith("api: started 2026-11-18 09:06:40Z (2.0h ago),")


def test_clip_marks_what_it_dropped():
    assert clip("x" * 10, 4) == "xxxx\n[clipped: 6 more characters]"
