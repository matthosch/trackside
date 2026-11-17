"""Data-quality checks. Each is one SQL query returning a single number,
judged against warn and fail thresholds. Results are stored in ops.dq_results
and pushed to Prometheus, which owns the alerting."""

from dataclasses import dataclass

import psycopg


@dataclass(frozen=True)
class Check:
    name: str
    description: str
    sql: str
    warn_above: float | None
    fail_above: float | None


@dataclass(frozen=True)
class Result:
    check: Check
    value: float
    status: str  # pass | warn | fail


TIMING_CHECKS = [
    Check(
        "files_not_fetched",
        "Discovered files that could not be downloaded",
        "SELECT count(*) FROM raw.timing_files WHERE fetched_at IS NULL",
        warn_above=None, fail_above=0,
    ),
    Check(
        "files_failed_to_load",
        "Downloaded files whose contents could not be parsed (e.g. changed columns)",
        "SELECT count(*) FROM raw.timing_files WHERE load_error IS NOT NULL",
        warn_above=None, fail_above=0,
    ),
    Check(
        "races_without_laps",
        "Race sessions with no lap data",
        """SELECT count(*) FROM staging.sessions s
           WHERE s.session_type = 'race'
             AND NOT EXISTS (SELECT 1 FROM staging.laps l WHERE l.session_id = s.id)""",
        warn_above=None, fail_above=0,
    ),
    Check(
        "implausible_lap_pct",
        "Percent of laps with no time or faster than 85% of the session median",
        """SELECT coalesce(100.0 * count(*) FILTER (WHERE implausible) / nullif(count(*), 0), 0)
           FROM marts.lap_quality""",
        warn_above=0.5, fail_above=2,
    ),
    Check(
        "laps_without_entry_pct",
        "Percent of laps whose car has no results entry, so no car model",
        """SELECT coalesce(100.0 * count(*) FILTER (WHERE e.car_number IS NULL) / nullif(count(*), 0), 0)
           FROM staging.laps l
           LEFT JOIN staging.session_entries e ON e.session_id = l.session_id AND e.car_number = l.car_number""",
        warn_above=0, fail_above=2,
    ),
    Check(
        "unmapped_vehicles",
        "Vehicle names with no car model pattern, shown under their raw name",
        "SELECT count(*) FROM marts.vehicle_models WHERE NOT mapped",
        warn_above=0, fail_above=None,
    ),
    Check(
        "upcoming_circuits_without_pace",
        "Upcoming calendar circuits with no pace data to show",
        """SELECT count(DISTINCT e.circuit_id) FROM events e
           WHERE e.end_date >= current_date AND e.circuit_id IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM marts.circuit_pace p WHERE p.circuit_id = e.circuit_id)""",
        warn_above=0, fail_above=None,
    ),
]


def judge(check: Check, value: float) -> str:
    if check.fail_above is not None and value > check.fail_above:
        return "fail"
    if check.warn_above is not None and value > check.warn_above:
        return "warn"
    return "pass"


def run(conn: psycopg.Connection, pipeline: str, run_id: str, checks: list[Check]) -> list[Result]:
    results = []
    with conn.transaction():
        for check in checks:
            value = float(conn.execute(check.sql).fetchone()[0])
            status = judge(check, value)
            conn.execute(
                """
                INSERT INTO ops.dq_results (run_id, pipeline, check_name, status, value, warn_above, fail_above, detail)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (run_id, pipeline, check.name, status, value, check.warn_above, check.fail_above, check.description),
            )
            results.append(Result(check, value, status))
    return results
