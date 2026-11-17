"""Refresh the race calendar and take today's sample-stay price snapshot.

The calendar is re-scraped daily because provisional dates move.
"""

from datetime import date, timedelta

import pendulum
from airflow.sdk import dag, task

PIPELINE = "calendar_and_stays"


@dag(
    dag_id=PIPELINE,
    schedule="0 5 * * *",
    start_date=pendulum.datetime(2026, 11, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=5)},
    tags=["trackside", "calendar"],
    doc_md=__doc__,
)
def calendar_and_stays():
    @task
    def refresh_calendar() -> dict:
        from trackside_pipelines import settings, sro_calendar

        season = settings.calendar_season()
        counts = {"events": 0, "events_without_circuit": 0}
        with settings.connect() as conn:
            for series_id, url in conn.execute("SELECT id, calendar_url FROM series").fetchall():
                events = sro_calendar.fetch_season(url, season)
                counts["events_without_circuit"] += sro_calendar.load(conn, series_id, season, events)
                counts["events"] += len(events)
        return counts

    @task
    def snapshot_stays(_calendar: dict) -> dict:
        from trackside_pipelines import settings, stays

        with settings.connect() as conn:
            stay_count, snapshot_count = stays.load(conn, date.today(), backfill_days=0)
        return {"stays": stay_count, "price_snapshots": snapshot_count}

    @task
    def report_success(calendar: dict, snapshots: dict) -> None:
        from trackside_pipelines import metrics

        metrics.push_success(PIPELINE, {**calendar, **snapshots})

    calendar = refresh_calendar()
    report_success(calendar, snapshot_stays(calendar))


calendar_and_stays()
