# Trackside

Follow the GT3 season race by race: see what to watch at each circuit and find a place to
stay near it. Trackside is a portfolio project whose real subject is running that app like a
production service. The full scope and plan are in [docs/scope.md](docs/scope.md).

**Status:** stage 2 of 8. The calendar, sample stays, timing-archive pipeline, pace panel,
API, frontend, and local observability stack work. The triage agent and cloud deployment
are not built yet.

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
| `DataQualityCheckFailing` | A data-quality check fails |
| `AirflowTaskFailures` | Any Airflow task failed in the last hour |
| `AirflowSchedulerDown` | The scheduler stops heartbeating |
| `AirflowDagImportErrors` | A DAG file fails to import |

Runbooks are in [docs/runbooks](docs/runbooks). Alerts show on Prometheus' Alerts page and
the Grafana dashboards; routing to the triage agent arrives in stage 3.

## Layout

| Path | Contents |
|---|---|
| `api/` | Go HTTP API with Prometheus metrics and JSON logs |
| `web/` | React and TypeScript frontend, served by nginx |
| `pipelines/` | Python package, Airflow DAGs, and tests |
| `db/migrations/` | SQL schema, reference data, and marts |
| `observability/` | Prometheus config and alerts, StatsD mapping, Grafana dashboards, Alloy log shipping |
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
- **The seed job's logs** are not in Loki, because it exits before log discovery sees it.
  Use `docker compose logs seed`.
