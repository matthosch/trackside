# Trackside

Follow the GT3 season race by race: see what to watch at each circuit and find a place to
stay near it. Trackside is a portfolio project whose real subject is running that app like a
production service. The full scope and plan are in [docs/scope.md](docs/scope.md).

**Status:** stage 1 of 8. The calendar, synthetic stays, API, frontend, and local
observability stack work. The timing pipeline, triage agent, and cloud deployment are not
built yet.

Stays and prices are generated sample data. Trackside is not affiliated with any racing
series or timing provider.

## Run it

Requires Docker.

```bash
docker compose up -d --build
```

| What | Where |
|---|---|
| App | http://localhost:8080 |
| API | http://localhost:8000/api/events |
| Grafana (anonymous read-only) | http://localhost:3000 |
| Prometheus | http://localhost:9090 |

The `seed` job runs once on start: it applies migrations, scrapes the 2027 GT World Challenge
America calendar, and generates stays with 30 days of price history. Run it again to refresh
the calendar and add today's prices:

```bash
docker compose run --rm seed
```

## Layout

| Path | Contents |
|---|---|
| `api/` | Go HTTP API with Prometheus metrics and JSON logs |
| `web/` | React and TypeScript frontend, served by nginx |
| `pipelines/` | Python: calendar scraper, stay generator, migration runner |
| `db/migrations/` | SQL schema and reference data |
| `observability/` | Prometheus scrape config and alert rules, Grafana dashboard, Alloy log shipping to Loki |
| `landing/` | Static landing page |
| `docs/` | Scope and supporting documents |

## Tests

```bash
cd api && go test ./...
```

```bash
cd pipelines && python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]" && .venv/Scripts/python -m pytest
```

```bash
cd web && npm install && npm run build
```

## Known gaps in stage 1

- Only GT World Challenge America is on the calendar. IMSA's site blocks automated fetches,
  so its calendar needs a different source.
- The seed job exits within seconds, before log discovery sees its container, so its logs are
  not in Loki. Use `docker compose logs seed`.
- Alert rules are evaluated by Prometheus but not routed anywhere until stage 3.
