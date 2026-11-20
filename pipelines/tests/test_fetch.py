import io
import urllib.error

import pytest

from trackside_pipelines import fetch, sro_calendar


class FakeOpener:
    """Stands in for urlopen: raises the queued errors, then serves the body."""

    def __init__(self, errors: list[Exception], body: bytes = b"ok"):
        self.errors = list(errors)
        self.body = body
        self.agents: list[str] = []

    def __call__(self, request, timeout):
        self.agents.append(request.get_header("User-agent"))
        if self.errors:
            raise self.errors.pop(0)
        return io.BytesIO(self.body)


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(fetch.time, "sleep", lambda _: None)


def dns_failure() -> urllib.error.URLError:
    return urllib.error.URLError("[Errno -2] Name or service not known")


def test_calendar_fetch_retries_a_transient_dns_failure(monkeypatch):
    opener = FakeOpener([dns_failure()], body="<html>calendar</html>".encode())
    monkeypatch.setattr(fetch.urllib.request, "urlopen", opener)

    assert sro_calendar.fetch("https://example.test/calendar") == "<html>calendar</html>"
    assert opener.agents == [sro_calendar.USER_AGENT, sro_calendar.USER_AGENT]


def test_gives_up_after_the_last_retry(monkeypatch):
    opener = FakeOpener([dns_failure()] * fetch.RETRIES)
    monkeypatch.setattr(fetch.urllib.request, "urlopen", opener)

    with pytest.raises(urllib.error.URLError):
        fetch.get("https://example.test/")
    assert len(opener.agents) == fetch.RETRIES


def test_client_errors_are_not_retried(monkeypatch):
    not_found = urllib.error.HTTPError("https://example.test/", 404, "Not Found", {}, None)
    opener = FakeOpener([not_found])
    monkeypatch.setattr(fetch.urllib.request, "urlopen", opener)

    with pytest.raises(urllib.error.HTTPError):
        fetch.get("https://example.test/")
    assert len(opener.agents) == 1
