# Runbook: the triage agent is down or over budget

Covers `TriageAgentDown` and `TriageAgentOverBudget`.

## What it means

Alertmanager sends every alert to the agent (`agent:8090/alerts`). The agent
investigates new incidents with read-only tools, then files a GitHub issue and a
Discord message, and keeps a markdown copy in the `agent-outbox` volume.

- **Down:** alerts still fire and show on Prometheus' Alerts page and in
  Alertmanager (http://localhost:9093), but nobody is told. Alertmanager retries
  delivery, so incidents that start while the agent is down are triaged once it
  is back, if they are still firing.
- **Over budget:** the month's Claude spend reached `AGENT_MONTHLY_BUDGET_USD`.
  The agent keeps working but sends evidence-only reports (the alert, the runbook,
  and everything else firing) until the month rolls over.

## Triage

1. Is it running? `docker compose ps agent`, then `docker compose logs agent`.
   It logs one JSON line per notification and per incident.
2. Is Alertmanager reaching it?
   ```promql
   rate(alertmanager_notifications_failed_total{integration="webhook"}[10m])
   ```
3. What has it spent, and on what?
   ```sql
   SELECT date_trunc('day', started_at) AS day, mode, outcome, count(*), sum(cost_usd)
   FROM ops.agent_runs GROUP BY 1, 2, 3 ORDER BY 1 DESC;
   ```

## Common causes

| Evidence | Likely cause | Action |
|---|---|---|
| Container restarting, `KeyError: 'DATABASE_URL'` | Missing environment | Check `docker-compose.yml` and `.env` |
| Runs end in `api_error` | Bad or missing `ANTHROPIC_API_KEY`, or the API is down | Check the key; the agent falls back to evidence-only reports meanwhile |
| Many runs in a short time | An alert flapping between firing and resolved | Fix the flapping alert or lengthen its `for:` |
| Outcome `incident_budget` | Investigations running long | Lower `AGENT_MAX_ITERATIONS` or tighten the runbook |
| `trackside_agent_output_failures_total` rising | GitHub token expired or Discord webhook deleted | Replace the credential in `.env`, then `docker compose up -d agent` |

## After fixing

Incidents that fired while the agent was down are picked up on Alertmanager's
next notification for the group (within `group_interval`, 5 minutes).
