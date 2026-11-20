"""Polite HTTP GET: one identifying user agent, a minimum gap between requests,
and a few retries with backoff for transient failures."""

import logging
import threading
import time
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

USER_AGENT = "trackside-pipeline/0.1"
MIN_INTERVAL_SECONDS = 1.0
RETRIES = 3

_lock = threading.Lock()
_last_request = 0.0


def _throttle() -> None:
    global _last_request
    with _lock:
        wait = _last_request + MIN_INTERVAL_SECONDS - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()


def get(url: str, timeout: float = 60, user_agent: str = USER_AGENT) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    for attempt in range(1, RETRIES + 1):
        _throttle()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            # 4xx will not get better by asking again.
            if error.code < 500 or attempt == RETRIES:
                raise
            log.warning("GET %s returned %s, retrying", url, error.code)
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == RETRIES:
                raise
            log.warning("GET %s failed (%s), retrying", url, error)
        time.sleep(2**attempt)
    raise AssertionError("unreachable")
