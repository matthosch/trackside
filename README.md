# Trackside

Follow the GT3 season race by race: see what to watch at each circuit and find a place to
stay near it. Trackside is a portfolio project whose real subject is running that app like a
production service. The full scope and plan are in [docs/scope.md](docs/scope.md).

**Status:** stage 3 of 8, in progress. The calendar, sample stays, timing-archive pipeline,
pace panel, API, frontend, local observability stack, alert routing, and the triage agent
work. Claude-backed triage needs an API key in `.env`; until then the agent files
evidence-only reports. Cloud deployment is not built yet.

Stays and prices are generated sample data. Lap-time figures are derived from timing data
published by Al Kamel Systems; raw timing files are kept private and never redistributed.
Trackside is not affiliated with any racing series or timing provider.

## Run it

Requires Docker with about 2 GB of memory free.

```bash
docker compose up -d --build
```

| What | Where |
|---|---|
| App | http://localhost:8080 |
| API | http://localhost:8000/api/events |
| Airflow (no login, local only) | http://localhost:8081 |
| Grafana (anonymous read-only) | http://localhost:3000 |
| Prometheus | http://localhost:9090 |
| Alertmanager | http://localhost:9093 |

On start, the `seed` job applies migrations and loads the calendar and stays. Airflow then
runs both pipelines once and daily after that:

| DAG | Schedule (UTC) | What it does |
|---|---|---|
| `calendar_and_stays` | 05:00 | Re-scrapes the race calendar and takes today's stay price snapshot |
| `timing_archive` | 06:00 | Finds new session files on the timing archives, downloads them, loads laps into Postgres, refreshes the pace marts, and runs data-quality checks |

The first `timing_archive` run downloads about 200 files (roughly 35 MB) at one request per
second, so it takes several minutes.

## How the timing pipeline works

```
Al Kamel archives ──discover──▶ raw.timing_files (manifest)
                  ──download──▶ private volume (raw files)
                  ──load──────▶ staging.sessions / session_entries / laps
                  ──refresh───▶ marts.lap_quality ─▶ marts.circuit_pace ─▶ API ─▶ "What to watch"
                  ──quality───▶ ops.dq_results ─▶ Pushgateway ─▶ Prometheus alerts
```

- **Sources:** IMSA WeatherTech (GTD and GTD Pro) for 2024–2026 and GT World Challenge
  America for 2025–2026, only at circuits on the Trackside calendar.
- **Idempotent steps:** every step keeps its state in the database, so any step can be
  retried alone and reruns pick up where the last one stopped.
- **Self-healing backfills:** each loaded file is stamped with the parser version
  (`PARSER_VERSION` in `timing.py`). Bumping it after a parser fix makes the next run
  reprocess every older file from the private raw copies, without downloading anything again.
  Discovery also prunes staged data that the current scope rules reject. Fixes ship as
  code, never as hand-written data migrations.
- **Pace:** a lap counts only if it was green-flag, not a pit in- or out-lap, not lap 1, and
  not implausibly fast. Race pace is the mean of the 10 fastest valid race laps. The panel
  ranks drivers (on their own laps) and teams (each car, all its drivers) within their class,
  and car models across the field. The SQL is in `db/migrations/005_timing_marts.sql` and
  `007_driver_and_entry_marts.sql`.
- **Data quality:** seven checks run after each load (`pipelines/trackside_pipelines/quality.py`).
  A failing check does not fail the run; it fires the `DataQualityCheckFailing` alert, so
  data problems and pipeline outages stay distinguishable.

## Alerts

| Alert | Fires when |
|---|---|
| `ApiDown`, `ApiHighErrorRatio`, `ApiSlowRequests` | The API is down, erroring, or slow |
| `PipelineStale` | A pipeline has not succeeded for 30 hours |
| `PipelineMetricsMissing` | A pipeline's last-success metric is absent, so staleness cannot be judged |
| `DataQualityCheckFailing` | A data-quality check fails |
| `AirflowTaskFailures` | Any Airflow task failed in the last hour |
| `AirflowSchedulerDown` | The scheduler stops heartbeating |
| `AirflowDagImportErrors` | A DAG file fails to import |

| `TriageAgentDown`, `TriageAgentOverBudget` | The agent is unreachable, or has used its monthly Claude budget |

Runbooks are in [docs/runbooks](docs/runbooks). Alertmanager sends every alert to the triage
agent, grouped per alert, pipeline, and data-quality check.

## Triage agent

```
Prometheus ─▶ Alertmanager ─▶ agent ─▶ Claude + read-only tools ─▶ report
                                 │                                    ├─▶ GitHub issue (closed on resolve)
                                 └── ops.incidents, ops.agent_runs    ├─▶ Discord message
                                                                      └─▶ outbox (markdown copy)
```

When an alert group starts firing, the agent (`agent/`) opens an incident, investigates
with Claude (`claude-opus-5-5`) and seven tools, and files what it found: summary, likely
cause with a confidence, evidence with the query behind each finding, what it ruled out,
next steps for a human, and the runbook. When Alertmanager reports the group resolved, it
comments on and closes the issue.

- **Strictly read-only.** The tools are PromQL and LogQL queries, Airflow run and task-log
  reads, runbook reads, and SQL as `trackside_readonly`, a role with SELECT-only grants,
  read-only transactions, and a 5-second statement timeout, so Postgres refuses writes even
  if the agent tried. The agent writes only its own bookkeeping tables.
- **Bounded spend.** A monthly budget (`AGENT_MONTHLY_BUDGET_USD`, default $5) is checked
  before each investigation, a per-incident budget ($1) after every turn, and turns are
  capped at 15. Every run's tokens and cost are recorded in `ops.agent_runs` and exported as
  metrics. The system prompt and tools are cached across incidents.
- **Degrades, never goes silent.** With no API key, over budget, or on an API error, refusal,
  or unusable output, the agent still files an evidence-only report: the alert, its runbook,
  and everything else firing. A failing output (GitHub down, say) never blocks the others.
- **Public-safe reports.** Issues are public, so the prompt forbids lap-level rows and raw
  file contents; reports cite counts and aggregates.

To turn on each part, set it in `.env` and run `docker compose up -d agent`:

| Setting | Enables |
|---|---|
| `ANTHROPIC_API_KEY` | Claude investigations |
| `GITHUB_TOKEN`, `GITHUB_REPO` | Issues on the repository (fine-grained token, Issues read and write) |
| `DISCORD_WEBHOOK_URL` | A message per incident and per resolution |

### Fault injection

`faults/inject.py` breaks the local stack on purpose so the whole path can be watched:

| Scenario | What it does | Alert |
|---|---|---|
| `api-latency` | Adds latency between the API and Postgres (Toxiproxy) and sends traffic | `ApiSlowRequests` |
| `api-errors` | Cuts the API's database link and sends traffic | `ApiHighErrorRatio` |
| `api-down` | Stops the API container | `ApiDown` |
| `implausible-laps` | Writes impossible lap times into the largest race file and reloads it | `DataQualityCheckFailing` |
| `missing-laps` | Empties one race's lap file and reloads it | `DataQualityCheckFailing` |
| `changed-layout` | Renames a column in a lap file, as if the provider changed format | `DataQualityCheckFailing` |

```bash
python faults/inject.py implausible-laps
python faults/inject.py clear
```

`clear` undoes every scenario. Faults for Balance of Performance bulletins and the lap
stream arrive with stages 5 and 6.

## Layout

| Path | Contents |
|---|---|
| `api/` | Go HTTP API with Prometheus metrics and JSON logs |
| `web/` | React and TypeScript frontend, served by nginx |
| `pipelines/` | Python package, Airflow DAGs, and tests |
| `agent/` | Alert triage agent: webhook service, read-only tools, Claude loop, outputs |
| `faults/` | Fault-injection scenarios for the local stack |
| `db/migrations/` | SQL schema, reference data, and marts |
| `observability/` | Prometheus config and alerts, Alertmanager routing, Toxiproxy, StatsD mapping, Grafana dashboards, Alloy log shipping |
| `docs/` | Scope, runbooks, and a draft data-permission request |
| `landing/` | Static landing page |

## Tests

```bash
cd api && go test ./...
```

```bash
cd pipelines && python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]" && .venv/Scripts/python -m pytest
```

The SQL transform tests need a Postgres they can create databases on. With the Compose
stack running:

```bash
cd pipelines && TEST_DATABASE_URL="postgresql://trackside:trackside@127.0.0.1:5432/postgres" .venv/Scripts/python -m pytest tests/test_marts_sql.py
```

Use `127.0.0.1`, not `localhost`: on Windows, `localhost` tries IPv6 first and stalls.

```bash
cd agent && python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]" && .venv/Scripts/python -m pytest
```

The agent's tests fake Claude, HTTP, and every output, so they need no key or network; its
store tests use `TEST_DATABASE_URL` like the SQL tests above.

```bash
cd web && npm install && npm run build
```

## Known gaps

- **GT World Challenge America 2024 and earlier** use a different file format on the archive
  (`6 - Laps CSV.csv`, no session timestamps) and are not loaded yet.
- **IMSA's own calendar** blocks automated fetches, so only GT World Challenge America rounds
  are on the calendar. IMSA timing data still feeds the pace panel at shared circuits.
- **Airflow has no login.** Every visitor is an admin, which is acceptable only on localhost.
  Real authentication is needed before stage 4 puts it online.
- **Raw timing files** sit in a local Docker volume until stage 4 moves them to a private bucket.
- **`TriageAgentDown` reaches no one:** Alertmanager can only deliver it to the agent that is
  down. It shows on Prometheus' Alerts page until a second route (direct to Discord) is added.
- **"Recent deploys"** are service restarts from Prometheus until stage 4 records real deploys.
- **The seed job's logs** are not in Loki, because it exits before log discovery sees it.
  Use `docker compose logs seed`.
