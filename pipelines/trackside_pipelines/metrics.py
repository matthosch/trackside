"""Push batch-job outcomes to the Prometheus Pushgateway.

Batch jobs finish before Prometheus could scrape them, so they push instead:
the Pushgateway's one recommended use. Alert rules live in Prometheus."""

import logging
import os
import time

from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

from .quality import Result

log = logging.getLogger(__name__)

STATUS_CODES = {"pass": 0, "warn": 1, "fail": 2}


def _gateway() -> str | None:
    return os.environ.get("PUSHGATEWAY_URL")


def push_success(pipeline: str, counts: dict[str, float]) -> None:
    """Record a successful run, with whatever counts the run wants to report."""
    gateway = _gateway()
    if not gateway:
        log.info("PUSHGATEWAY_URL not set; skipping metrics push")
        return
    registry = CollectorRegistry()
    Gauge("trackside_pipeline_last_success_timestamp_seconds", "Unix time of the last successful run.",
          ["pipeline"], registry=registry).labels(pipeline).set(time.time())
    gauge = Gauge("trackside_pipeline_count", "Counts reported by the last successful run.",
                  ["pipeline", "name"], registry=registry)
    for name, value in counts.items():
        gauge.labels(pipeline, name).set(value)
    push_to_gateway(gateway, job="trackside_pipeline", grouping_key={"pipeline": pipeline}, registry=registry)


def push_quality(pipeline: str, results: list[Result]) -> None:
    gateway = _gateway()
    if not gateway:
        log.info("PUSHGATEWAY_URL not set; skipping metrics push")
        return
    registry = CollectorRegistry()
    status = Gauge("trackside_dq_check_status", "Data-quality check status: 0 pass, 1 warn, 2 fail.",
                   ["pipeline", "check"], registry=registry)
    value = Gauge("trackside_dq_check_value", "Value measured by the data-quality check.",
                  ["pipeline", "check"], registry=registry)
    for r in results:
        status.labels(pipeline, r.check.name).set(STATUS_CODES[r.status])
        value.labels(pipeline, r.check.name).set(r.value)
    Gauge("trackside_dq_last_run_timestamp_seconds", "Unix time the checks last ran.",
          ["pipeline"], registry=registry).labels(pipeline).set(time.time())
    push_to_gateway(gateway, job="trackside_dq", grouping_key={"pipeline": pipeline}, registry=registry)
