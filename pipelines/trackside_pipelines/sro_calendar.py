"""Scrape a season calendar from an SRO series site.

SRO series sites share one template: `/calendar?filter_season_id={id}` renders the
season as HTML. The season id is site-specific, so it is read from the season
selector on the page instead of being assumed.
"""

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urljoin

import psycopg
from bs4 import BeautifulSoup, Tag

from . import fetch as http

log = logging.getLogger(__name__)

USER_AGENT = "trackside-calendar/0.1"
_EVENT_HREF = re.compile(r"/event/(\d+)/([^/?#]+)")
_ROUND = re.compile(r"Round\s+(\d+)", re.I)


class CalendarParseError(Exception):
    """The page did not have the structure this parser expects."""


@dataclass(frozen=True)
class CalendarEvent:
    source_event_id: str
    slug: str
    venue_name: str
    round: int | None
    start_date: date
    end_date: date
    source_url: str


def fetch(url: str, timeout: float = 30) -> str:
    # Shares the timing pipeline's throttle and retries: one DNS blip after a
    # laptop wakes used to fail the whole calendar refresh.
    return http.get(url, timeout=timeout, user_agent=USER_AGENT).decode("utf-8", errors="replace")


def season_ids(html: str) -> dict[int, str]:
    """Map season year to the site's own season id, from the season selector."""
    soup = BeautifulSoup(html, "html.parser")
    ids = {}
    for option in soup.select("select#filter_season_id option"):
        label = option.get_text(strip=True)
        if label.isdigit():
            ids[int(label)] = option["value"]
    if not ids:
        raise CalendarParseError("season selector not found")
    return ids


def _parse_date(container: Tag | None) -> date | None:
    if container is None:
        return None
    parts = [
        container.select_one(f".calendar__date-{part}")
        for part in ("number", "month", "year")
    ]
    if any(p is None for p in parts):
        return None
    text = " ".join(p.get_text(strip=True) for p in parts)
    return datetime.strptime(text, "%d %b %Y").date()


def parse_calendar(html: str, base_url: str) -> list[CalendarEvent]:
    soup = BeautifulSoup(html, "html.parser")
    events = []
    for item in soup.select("li.calendar__list-item"):
        header = item.select_one(".calendar__race-header")
        link = item.find("a", href=_EVENT_HREF)
        start = _parse_date(item.select_one(".calendar__date-start"))
        if header is None or link is None or start is None:
            continue
        end = _parse_date(item.select_one(".calendar__date-end")) or start
        source_event_id, slug = _EVENT_HREF.search(link["href"]).groups()
        round_match = _ROUND.search(
            " ".join(t.get_text(" ", strip=True) for t in item.select(".calendar__race-text"))
        )
        events.append(
            CalendarEvent(
                source_event_id=source_event_id,
                slug=slug,
                venue_name=header.get_text(strip=True),
                round=int(round_match.group(1)) if round_match else None,
                start_date=start,
                end_date=end,
                source_url=urljoin(base_url, link["href"]),
            )
        )
    if not events:
        raise CalendarParseError("no events found on calendar page")
    return events


def fetch_season(calendar_url: str, season: int) -> list[CalendarEvent]:
    ids = season_ids(fetch(calendar_url))
    if season not in ids:
        raise CalendarParseError(f"season {season} not offered; site has {sorted(ids)}")
    html = fetch(f"{calendar_url}?filter_season_id={ids[season]}")
    return parse_calendar(html, calendar_url)


def match_circuit(venue_name: str, circuits: list[tuple[str, str, list[str]]]) -> str | None:
    """Return the id of the circuit whose name or alias equals the venue name."""
    wanted = venue_name.casefold()
    for circuit_id, name, aliases in circuits:
        if wanted in {name.casefold(), *(a.casefold() for a in aliases)}:
            return circuit_id
    return None


def load(conn: psycopg.Connection, series_id: str, season: int, events: list[CalendarEvent]) -> int:
    """Upsert events. Returns how many venues did not match a known circuit."""
    circuits = conn.execute("SELECT id, name, aliases FROM circuits").fetchall()
    unmatched = 0
    with conn.transaction():
        for event in events:
            circuit_id = match_circuit(event.venue_name, circuits)
            if circuit_id is None:
                unmatched += 1
                log.warning("no circuit for venue %r (%s)", event.venue_name, event.source_url)
            conn.execute(
                """
                INSERT INTO events (series_id, season, round, source_event_id, slug, venue_name,
                                    circuit_id, start_date, end_date, source_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (series_id, season, source_event_id) DO UPDATE SET
                    round = EXCLUDED.round,
                    slug = EXCLUDED.slug,
                    venue_name = EXCLUDED.venue_name,
                    circuit_id = EXCLUDED.circuit_id,
                    start_date = EXCLUDED.start_date,
                    end_date = EXCLUDED.end_date,
                    source_url = EXCLUDED.source_url,
                    last_seen_at = now()
                """,
                (
                    series_id, season, event.round, event.source_event_id, event.slug,
                    event.venue_name, circuit_id, event.start_date, event.end_date,
                    event.source_url,
                ),
            )
    return unmatched
