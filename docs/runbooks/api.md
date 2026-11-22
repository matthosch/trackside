# Runbook: the API is down, failing, or slow

Covers `ApiDown`, `ApiHighErrorRatio`, and `ApiSlowRequests`.

## What it means

The Go API (`api`) serves every page of the app: the calendar, stays, and the pace
panel. It reads Postgres through Toxiproxy (`toxiproxy:5433` -> `db:5432`), which
passes traffic straight through unless a fault scenario is active.

| Alert | Fires when | Users see |
|---|---|---|
| `ApiDown` | Prometheus cannot scrape the API for 2 minutes | Every page fails to load |
| `ApiHighErrorRatio` | Over 5% of requests return 5xx for 5 minutes | Pages fail intermittently |
| `ApiSlowRequests` | p95 latency of `/api/*` routes is over 500 ms for 10 minutes | Slow pages; the pace panel worst |

## Triage

1. Is the process up, and did it restart recently?
   ```promql
   up{job="api"}
   changes(process_start_time_seconds{job="api"}[1h])
   ```
2. Which routes are failing or slow?
   ```promql
   sum by (route, status) (rate(http_requests_total{job="api"}[5m]))
   histogram_quantile(0.95, sum by (le, route) (rate(http_request_duration_seconds_bucket{job="api"}[5m])))
   ```
3. What does the API log? Every request is a JSON line with its route, status, and
   duration; errors carry the cause.
   ```logql
   {service="api"} | json | level="ERROR"
   {service="api"} | json | duration_ms > 500
   ```
4. Is Postgres healthy, and is the link to it clean?
   ```bash
   docker compose ps db toxiproxy
   curl -s http://127.0.0.1:8474/proxies/api-db/toxics
   ```
   An empty list (`[]`) means no fault is injected.

## Common causes

| Evidence | Likely cause | Action |
|---|---|---|
| `up` is 0, container exited | The API crashed or was stopped | `docker compose logs api`; `docker compose up -d api` |
| Errors mention `connection refused` or `dial tcp` | Postgres or Toxiproxy is down | `docker compose up -d db toxiproxy` |
| Every route slow by the same amount; `/healthz` slow too | Latency between API and Postgres (a Toxiproxy toxic, or the host is overloaded) | Check the toxics list above; `python faults/inject.py clear` removes injected faults |
| Only the pace routes slow | A mart grew or lost an index | `EXPLAIN ANALYZE` the slow query as the read-only role |
| 5xx only on one route after a deploy | A code change | Roll back to the previous image |

## After fixing

The alerts resolve on their own once the condition clears for one evaluation
(latency needs the 5-minute rate window to roll over first). The triage agent
closes the incident's GitHub issue when Alertmanager reports it resolved.
