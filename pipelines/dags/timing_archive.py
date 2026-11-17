"""Load lap-by-lap timing archives and build the pace marts.

discover -> download -> load -> refresh_marts -> quality_checks -> report_success

Every step keeps its state in the database, so any step can be retried alone.
Data-quality failures do not fail the run: they are pushed to Prometheus,
which alerts on them separately from pipeline failures.
"""

from datetime import timedelta

import pendulum
from airflow.sdk import dag, get_current_context, task

PIPELINE = "timing_archive"


@dag(
    dag_id=PIPELINE,
    schedule="0 6 * * *",
    start_date=pendulum.datetime(2026, 11, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=5)},
    tags=["trackside", "timing"],
    doc_md=__doc__,
)
def timing_archive():
    @task(execution_timeout=timedelta(minutes=30))
    def discover() -> int:
        from trackside_pipelines import settings, timing_pipeline

        with settings.connect() as conn:
            return timing_pipeline.discover(conn, settings.timing_seasons())

    @task(execution_timeout=timedelta(hours=2))
    def download(_discovered: int) -> dict:
        from trackside_pipelines import settings, timing_pipeline

        with settings.connect() as conn:
            fetched, failed = timing_pipeline.download(conn, settings.raw_dir())
        return {"fetched": fetched, "fetch_failed": failed}

    @task(execution_timeout=timedelta(minutes=30))
    def load(_downloaded: dict) -> dict:
        from trackside_pipelines import settings, timing_pipeline

        with settings.connect() as conn:
            loaded, errors = timing_pipeline.load(conn)
        return {"sessions_loaded": loaded, "sessions_failed": errors}

    @task
    def refresh_marts(_loaded: dict) -> None:
        from trackside_pipelines import settings, timing_pipeline

        with settings.connect() as conn:
            timing_pipeline.refresh_marts(conn)

    @task
    def quality_checks(_refreshed: None) -> dict:
        from trackside_pipelines import metrics, quality, settings

        run_id = get_current_context()["run_id"]
        with settings.connect() as conn:
            results = quality.run(conn, PIPELINE, run_id, quality.TIMING_CHECKS)
        metrics.push_quality(PIPELINE, results)
        return {r.check.name: r.status for r in results}

    @task
    def report_success(discovered: int, downloaded: dict, loaded: dict, _checks: dict) -> None:
        from trackside_pipelines import metrics, settings

        with settings.connect() as conn:
            laps, sessions = conn.execute(
                "SELECT (SELECT count(*) FROM staging.laps), (SELECT count(*) FROM staging.sessions)"
            ).fetchone()
        metrics.push_success(PIPELINE, {"files_discovered": discovered, **downloaded, **loaded,
                                        "laps_total": laps, "sessions_total": sessions})

    discovered = discover()
    downloaded = download(discovered)
    loaded = load(downloaded)
    checks = quality_checks(refresh_marts(loaded))
    report_success(discovered, downloaded, loaded, checks)


timing_archive()
