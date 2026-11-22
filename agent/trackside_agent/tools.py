"""The agent's investigation tools. Every one only reads: HTTP GETs against
Prometheus, Loki, and Airflow, SELECTs as a read-only database role, and the
runbooks on disk. Nothing here can change the system it is looking at.

Each tool returns plain text sized for a model's context: results are clipped,
and long series are summarised rather than dumped.
"""

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone

import psycopg

from .config import Settings

log = logging.getLogger(__name__)

MAX_CHARS = 6000
MAX_SERIES = 20
MAX_ROWS = 50

HttpGet = Callable[[str, dict[str, str]], bytes]


def http_get(url: str, headers: dict[str, str]) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "trackside-agent/0.1", **headers})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


def clip(text: str, limit: int = MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[clipped: {len(text) - limit} more characters]"


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def _labels(metric: dict[str, str]) -> str:
    return "{" + ", ".join(f'{k}="{v}"' for k, v in sorted(metric.items())) + "}"


def _num(value: str) -> str:
    try:
        return f"{float(value):.6g}"
    except ValueError:
        return value


class Investigator:
    """Read-only access to the stack. `get` is injectable so tests need no network."""

    def __init__(self, settings: Settings, get: HttpGet = http_get, clock: Callable[[], float] = time.time):
        self.s = settings
        self._get = get
        self._clock = clock
        self._airflow_token: str | None = None

    def _json(self, url: str, headers: dict[str, str] | None = None) -> dict:
        return json.loads(self._get(url, headers or {}))

    # Prometheus ---------------------------------------------------------------

    def query_prometheus(self, query: str, minutes: int = 0) -> str:
        """Instant query when minutes is 0; otherwise a range over the last N minutes,
        summarised per series as min, max, last, and a few evenly spaced samples."""
        base = self.s.prometheus_url.rstrip("/")
        if minutes <= 0:
            url = f"{base}/api/v1/query?" + urllib.parse.urlencode({"query": query})
        else:
            end = self._clock()
            step = max(15, minutes * 60 // 60)
            url = f"{base}/api/v1/query_range?" + urllib.parse.urlencode(
                {"query": query, "start": end - minutes * 60, "end": end, "step": step})
        try:
            body = self._json(url)
        except urllib.error.HTTPError as error:
            return f"Prometheus rejected the query ({error.code}): {error.read().decode(errors='replace')[:500]}"
        data = body.get("data", {})
        results = data.get("result", [])
        if not results:
            return "No series matched."
        lines = []
        for series in results[:MAX_SERIES]:
            name = _labels(series.get("metric", {}))
            if "value" in series:
                ts, value = series["value"]
                lines.append(f"{name} = {_num(value)} at {_iso(float(ts))}")
            else:
                values = series.get("values", [])
                nums = [float(v) for _, v in values if v not in ("NaN", "+Inf", "-Inf")]
                picks = values[:: max(1, len(values) // 6)] + values[-1:]
                samples = ", ".join(f"{_iso(float(t))[11:16]} {_num(v)}" for t, v in picks)
                if nums:
                    lines.append(f"{name}: min {min(nums):.6g}, max {max(nums):.6g}, last {nums[-1]:.6g}; "
                                 f"samples: {samples}")
                else:
                    lines.append(f"{name}: no numeric values; samples: {samples}")
        if len(results) > MAX_SERIES:
            lines.append(f"[{len(results) - MAX_SERIES} more series not shown; narrow the query]")
        return clip("\n".join(lines))

    def service_starts(self, hours: int = 24) -> str:
        """When each scraped service last started, and how often it restarted in the
        window. Restarts stand in for deploys until stage 4 records real ones."""
        base = self.s.prometheus_url.rstrip("/") + "/api/v1/query?"

        def by_job(query: str) -> dict[str, float]:
            body = self._json(base + urllib.parse.urlencode({"query": query}))
            return {r["metric"].get("job", "?"): float(r["value"][1]) for r in body["data"]["result"]}

        starts = by_job("process_start_time_seconds")
        restarts = by_job(f"changes(process_start_time_seconds[{int(hours)}h])")
        if not starts:
            return "No service reports a process start time."
        now = self._clock()
        lines = [f"{job}: started {_iso(ts)} ({(now - ts) / 3600:.1f}h ago), "
                 f"{int(restarts.get(job, 0))} restart(s) in the last {hours}h"
                 for job, ts in sorted(starts.items(), key=lambda kv: -kv[1])]
        return "\n".join(lines)

    # Loki ---------------------------------------------------------------------

    def query_loki(self, query: str, minutes: int = 60, limit: int = 40) -> str:
        """Most recent matching log lines first, from every container's stdout."""
        end = self._clock()
        url = self.s.loki_url.rstrip("/") + "/loki/api/v1/query_range?" + urllib.parse.urlencode({
            "query": query, "start": int((end - minutes * 60) * 1e9), "end": int(end * 1e9),
            "limit": min(int(limit), 200), "direction": "backward"})
        try:
            body = self._json(url)
        except urllib.error.HTTPError as error:
            return f"Loki rejected the query ({error.code}): {error.read().decode(errors='replace')[:500]}"
        entries = []
        for stream in body.get("data", {}).get("result", []):
            service = stream.get("stream", {}).get("service", "?")
            for ts, line in stream.get("values", []):
                entries.append((int(ts), service, line))
        if not entries:
            return "No log lines matched."
        entries.sort(reverse=True)
        lines = [f"{_iso(ts / 1e9)} [{service}] {line[:400]}" for ts, service, line in entries[: int(limit)]]
        return clip("\n".join(lines))

    # Airflow ------------------------------------------------------------------

    def _airflow(self, path: str) -> dict:
        base = self.s.airflow_url.rstrip("/")
        if self._airflow_token is None:
            try:
                self._airflow_token = self._json(f"{base}/auth/token").get("access_token", "")
            except (urllib.error.URLError, ValueError):
                self._airflow_token = ""
        headers = {"Authorization": f"Bearer {self._airflow_token}"} if self._airflow_token else {}
        return self._json(f"{base}/api/v2{path}", headers)

    def airflow_runs(self, dag_id: str, limit: int = 5) -> str:
        """Recent runs of a DAG, newest first, with every task's state for runs that
        did not succeed."""
        dag = urllib.parse.quote(dag_id, safe="")
        try:
            runs = self._airflow(f"/dags/{dag}/dagRuns?limit={int(limit)}&order_by=-run_after")["dag_runs"]
        except urllib.error.HTTPError as error:
            return f"Airflow returned {error.code} for DAG {dag_id!r}."
        if not runs:
            return f"No runs for DAG {dag_id!r}."
        lines = []
        for run in runs:
            lines.append(f"{run['dag_run_id']}: {run['state']} (started {run.get('start_date')}, "
                         f"ended {run.get('end_date')})")
            if run["state"] != "success":
                run_id = urllib.parse.quote(run["dag_run_id"], safe="")
                tis = self._airflow(f"/dags/{dag}/dagRuns/{run_id}/taskInstances")["task_instances"]
                for ti in tis:
                    lines.append(f"  - {ti['task_id']}: {ti['state']} (try {ti['try_number']}, "
                                 f"{ti.get('duration') or 0:.0f}s)")
        try:
            errors = self._airflow("/importErrors")["import_errors"]
        except urllib.error.HTTPError:
            errors = []
        lines.append(f"DAG import errors: {len(errors)}")
        lines += [f"  - {e.get('filename')}: {str(e.get('stack_trace', ''))[-300:]}" for e in errors]
        return clip("\n".join(lines))

    def airflow_task_log(self, dag_id: str, run_id: str, task_id: str, try_number: int) -> str:
        """The log of one task attempt: warnings, errors, and exceptions in full, other
        lines only near the end."""
        dag, run, task = (urllib.parse.quote(p, safe="") for p in (dag_id, run_id, task_id))
        path = f"{dag}/dagRuns/{run}/taskInstances/{task}"
        try:
            entries = self._airflow(f"/dags/{path}/logs/{int(try_number)}")["content"]
        except urllib.error.HTTPError as error:
            return f"Airflow returned {error.code} for that task attempt."
        lines = []
        for i, entry in enumerate(entries):
            event = str(entry.get("event", ""))
            if event.startswith("::") or "timestamp" not in entry:
                continue
            level = entry.get("level", "")
            important = level in ("warning", "error", "critical") or "error_detail" in entry
            if not important and i < len(entries) - 15:
                continue
            lines.append(f"{entry.get('timestamp', '')} {level} {entry.get('logger', '')}: {event[:400]}")
            for exc in entry.get("error_detail", []):
                frames = exc.get("frames", [])[-3:]
                where = " <- ".join(f"{f['filename'].rsplit('/', 1)[-1]}:{f['lineno']} {f['name']}" for f in frames)
                lines.append(f"    {exc.get('exc_type')}: {exc.get('exc_value')} at {where}")
        return clip("\n".join(lines) or "The log has no entries.")

    # Database -----------------------------------------------------------------

    def query_database(self, sql: str) -> str:
        """One SELECT (or WITH ... SELECT) as the read-only role, inside a read-only
        transaction with a 5 second timeout. Returns at most 50 rows."""
        statement = sql.strip().rstrip(";").strip()
        if ";" in statement:
            return "Refused: send exactly one statement, without semicolons."
        if not re.match(r"(?is)^(select|with|explain|table|values)\b", statement):
            return "Refused: only SELECT, WITH, EXPLAIN, TABLE, or VALUES statements are allowed."
        try:
            with psycopg.connect(self.s.readonly_database_url, connect_timeout=5) as conn:
                conn.read_only = True
                with conn.cursor() as cur:
                    cur.execute("SET LOCAL statement_timeout = '5s'")
                    cur.execute(statement)
                    if cur.description is None:
                        return "The statement returned no rows."
                    columns = [c.name for c in cur.description]
                    rows = cur.fetchmany(MAX_ROWS + 1)
        except psycopg.Error as error:
            return f"Database error: {str(error).strip()[:500]}"
        if not rows:
            return "\t".join(columns) + "\n(no rows)"
        out = ["\t".join(columns)] + ["\t".join("" if v is None else str(v) for v in row) for row in rows[:MAX_ROWS]]
        if len(rows) > MAX_ROWS:
            out.append(f"[more than {MAX_ROWS} rows; aggregate or add LIMIT]")
        return clip("\n".join(out))

    # Runbooks -----------------------------------------------------------------

    def list_runbooks(self) -> str:
        """Each runbook's file name and title."""
        lines = []
        for path in sorted(self.s.runbooks_dir.glob("*.md")):
            title = path.read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip()
            lines.append(f"{path.name}: {title}")
        return "\n".join(lines) or "No runbooks found."

    def read_runbook(self, name: str) -> str:
        """The full text of one runbook, by file name (e.g. 'pipeline-stale.md')."""
        name = name.rsplit("/", 1)[-1]
        path = self.s.runbooks_dir / name
        if path.suffix != ".md" or path.parent != self.s.runbooks_dir or not path.is_file():
            return f"No runbook named {name!r}. Available:\n{self.list_runbooks()}"
        return clip(path.read_text(encoding="utf-8"), 12000)
