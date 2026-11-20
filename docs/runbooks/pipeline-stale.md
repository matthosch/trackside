# Runbook: a pipeline is stale or failing

Covers `PipelineStale`, `PipelineMetricsMissing`, `AirflowTaskFailures`, `AirflowSchedulerDown`,
and `AirflowDagImportErrors`.

## What it means

The `calendar_and_stays` and `timing_archive` DAGs each run once a day. Every
successful run pushes `trackside_pipeline_last_success_timestamp_seconds` to the
Pushgateway. More than 30 hours without one means a run was missed or failed.

Users see stale data, not an outage: the calendar and stays stop updating, or
new race sessions do not appear in the pace panel.

## Triage

1. Is the scheduler alive? Check `AirflowSchedulerDown`, or:
   ```bash
   docker compose ps airflow-scheduler airflow-dag-processor airflow-apiserver
   ```
   If it is down, restart it with `docker compose up -d airflow-scheduler` and read
   its logs in Grafana (`{service="airflow-scheduler"}`).

2. Do the DAG files import? A broken import silently stops a pipeline.
   ```bash
   docker compose exec airflow-scheduler airflow dags list-import-errors
   ```

3. Which task failed? Open Airflow at http://localhost:8081, select the DAG, and
   read the failed task's log. Or:
   ```bash
   docker compose exec airflow-scheduler airflow dags list-runs timing_archive
   ```

## Common causes

| Symptom in the task log | Likely cause | Action |
|---|---|---|
| `HTTPError 403` or `429` in `discover` or `download` | The archive host is refusing or rate-limiting us | Wait a day; do not lower the request interval. If it persists, check whether the site's terms changed. |
| `CalendarParseError` in `refresh_calendar` | The series site changed its calendar layout | Update `sro_calendar.py` and its fixture, then rerun. |
| Connection refused to `db` | The app database is down | Fix the database first; the pipeline needs no change. |
| Task killed with no Python error | Out of memory on the host | Check host memory; long-race time cards are the largest files. |
| `URLError: Name or service not known`, or a task failed for missed heartbeats with long gaps in its log | The host slept (a laptop) and DNS was not back on wake | Fetches retry three times with backoff; if all three fail, clear the task once the network is back. |
| `PipelineMetricsMissing`, no failed task | The Pushgateway lost its stored metrics, or the pipeline has never succeeded | Check `docker compose logs pushgateway` for persistence errors, then trigger the pipeline to push a fresh timestamp. |

## After fixing

Clear the failed task in the Airflow UI (or trigger a new run). Every step keeps
its state in the database, so a rerun resumes where the last one stopped. The
alert resolves after the next successful run pushes a fresh timestamp.
