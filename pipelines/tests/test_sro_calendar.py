from datetime import date
from pathlib import Path

import pytest

from trackside_pipelines.sro_calendar import (
    CalendarParseError,
    match_circuit,
    parse_calendar,
    season_ids,
)

FIXTURE = (Path(__file__).parent / "fixtures" / "sro_calendar.html").read_text(encoding="utf-8")
BASE = "https://example.test/calendar"


def test_season_ids_come_from_the_selector():
    assert season_ids(FIXTURE) == {2027: "12", 2026: "11"}


def test_parses_event_rows_and_skips_non_events():
    events = parse_calendar(FIXTURE, BASE)
    assert [e.venue_name for e in events] == ["Sonoma Raceway", "Circuit of The Americas"]

    sonoma = events[0]
    assert sonoma.source_event_id == "121"
    assert sonoma.slug == "sonoma-raceway"
    assert sonoma.round == 1
    assert (sonoma.start_date, sonoma.end_date) == (date(2027, 4, 2), date(2027, 4, 4))
    assert sonoma.source_url == "https://example.test/event/121/sonoma-raceway"


def test_missing_end_date_and_round_fall_back():
    cota = parse_calendar(FIXTURE, BASE)[1]
    assert cota.end_date == cota.start_date == date(2027, 5, 7)
    assert cota.round is None


def test_changed_layout_raises_instead_of_returning_nothing():
    with pytest.raises(CalendarParseError):
        parse_calendar("<html><body><p>Redesigned</p></body></html>", BASE)
    with pytest.raises(CalendarParseError):
        season_ids("<html></html>")


def test_match_circuit_uses_names_and_aliases_case_insensitively():
    circuits = [("cota", "Circuit of The Americas", ["COTA"]), ("barber", "Barber Motorsports Park", [])]
    assert match_circuit("circuit of the americas", circuits) == "cota"
    assert match_circuit("cota", circuits) == "cota"
    assert match_circuit("Laguna Seca", circuits) is None
