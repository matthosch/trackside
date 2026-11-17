"""Discover session files on Al Kamel timing archives.

Both hosts render a server-side listing page per event with links shaped like
    Results/[06_SRO/]{YY_YYYY}/{NN_Event}/{NN_Series}/{YYYYMMDDHHMM_Session}/[{NN_Hour N}/]{file}
Filenames are inconsistent (case, spaces vs underscores, Official/Provisional
suffixes), so files are found by pattern and ranked, never constructed.
"""

import html
import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class Source:
    id: str
    base_url: str
    extra_params: dict[str, str]
    series_matches: Callable[[str], bool]
    # Classes to keep from the lap files; None keeps every class.
    classes: frozenset[str] | None


SOURCES = {
    "imsa": Source(
        id="imsa",
        base_url="https://imsa.results.alkamelcloud.com/",
        extra_params={},
        series_matches=lambda folder: "WeatherTech" in folder,
        classes=frozenset({"GTD", "GTDPRO"}),
    ),
    "sro_america": Source(
        id="sro_america",
        base_url="https://usac.alkamelsystems.com/",
        extra_params={"series": "06_SRO"},
        series_matches=lambda folder: "GT World Challenge America" in folder,
        # Shared sessions can carry GT America (SRO3, GT2), GT4, and one-make cars.
        classes=frozenset({"PRO", "PRO-AM", "AM"}),
    ),
}


@dataclass(frozen=True)
class SessionFiles:
    source: str
    season: int
    event_folder: str
    series_folder: str
    session_folder: str
    session_name: str
    session_type: str
    starts_at: datetime | None
    laps_url: str | None
    results_url: str | None


_SEASON_FOLDER = re.compile(r"^\d\d_(\d{4})$")
_SESSION_FOLDER = re.compile(r"^(\d{12})_(.+)$")
_HOUR_FOLDER = re.compile(r"^\d\d_Hour (\d+)$", re.I)
_LAPS_FILE = re.compile(r"^23_(Time[ _]Cards|AnalysisEnduranceWithSections)", re.I)
_RESULTS_FILE = re.compile(r"^03_.*Results", re.I)


def listing_url(source: Source, season_value: str | None = None, event_value: str | None = None) -> str:
    params = dict(source.extra_params)
    if season_value:
        params["season"] = season_value
    if event_value:
        params["evvent"] = event_value  # sic: the site's own parameter name
    return source.base_url + ("?" + urllib.parse.urlencode(params) if params else "")


def select_options(page: str, name: str) -> list[tuple[str, str]]:
    """(value, label) pairs of a <select> on a listing page."""
    soup = BeautifulSoup(page, "html.parser")
    select = soup.find("select", attrs={"name": name})
    if select is None:
        return []
    return [(o.get("value", ""), o.get_text(strip=True)) for o in select.find_all("option")]


def season_value(page: str, season: int) -> str | None:
    for value, _ in select_options(page, "season"):
        if value.endswith(f"_{season}"):
            return value
    return None


def normalise_venue(label: str) -> str:
    """'Circuit of the Americas (VPRC)' -> 'circuit of the americas'."""
    label = re.sub(r"\s*\([^)]*\)\s*$", "", label)
    label = re.sub(r"\s+RC$", "", label)  # road course suffix on oval venues
    return label.strip().casefold()


def match_circuit(label: str, circuits: list[tuple[str, str, list[str]]]) -> str | None:
    wanted = normalise_venue(label)
    for circuit_id, name, aliases in circuits:
        if wanted in {name.casefold(), *(a.casefold() for a in aliases)}:
            return circuit_id
    return None


def session_type(name: str) -> str:
    lowered = name.casefold()
    if "race" in lowered:
        return "race"
    if "qualif" in lowered:
        return "qualifying"
    if "practice" in lowered or "warm" in lowered:
        return "practice"
    if "test" in lowered:
        return "test"
    return "other"


def _status_rank(filename: str) -> int:
    lowered = filename.casefold()
    if "unofficial" in lowered:
        return 4
    if "provisional" in lowered:
        return 3
    if "amended" in lowered:
        return 2
    if "official" in lowered:
        return 0
    return 1


def _pick(candidates: list[tuple[int, str, str]]) -> str | None:
    """candidates: (hour, filename, url). Latest hour wins, then the most final status."""
    if not candidates:
        return None
    return min(candidates, key=lambda c: (-c[0], _status_rank(c[1])))[2]


def discover_sessions(page: str, page_url: str, source: Source) -> list[SessionFiles]:
    """All in-scope sessions on one event listing page, with their chosen files."""
    found: dict[tuple, dict] = {}
    soup = BeautifulSoup(page, "html.parser")
    for link in soup.find_all("a", href=True):
        href = html.unescape(link["href"])
        if not href.startswith("Results/"):
            continue
        parts = [urllib.parse.unquote(p) for p in href.split("/")[1:]]
        season_index = next((i for i, p in enumerate(parts) if _SEASON_FOLDER.match(p)), None)
        if season_index is None:
            continue
        parts = parts[season_index:]
        if len(parts) < 5:
            continue
        season_folder, event_folder, series_folder, session_folder, *rest = parts
        session_match = _SESSION_FOLDER.match(session_folder)
        if not source.series_matches(series_folder) or not session_match:
            continue

        *subfolders, filename = rest
        hour = 10**6  # files at the session root are the final set
        if subfolders:
            hour_match = _HOUR_FOLDER.match(subfolders[0])
            if len(subfolders) > 1 or not hour_match:
                continue  # starting grids, nested test sessions, and the like
            hour = int(hour_match.group(1))
        if not filename.casefold().endswith(".csv"):
            continue

        key = (season_folder, event_folder, series_folder, session_folder)
        entry = found.setdefault(key, {"laps": [], "results": []})
        url = urllib.parse.urljoin(page_url, href.replace(" ", "%20"))
        if _LAPS_FILE.match(filename):
            entry["laps"].append((hour, filename, url))
        elif _RESULTS_FILE.match(filename):
            entry["results"].append((hour, filename, url))

    sessions = []
    for (season_folder, event_folder, series_folder, session_folder), files in sorted(found.items()):
        stamp, name = _SESSION_FOLDER.match(session_folder).groups()
        sessions.append(
            SessionFiles(
                source=source.id,
                season=int(_SEASON_FOLDER.match(season_folder).group(1)),
                event_folder=event_folder,
                series_folder=series_folder,
                session_folder=session_folder,
                session_name=name,
                session_type=session_type(name),
                starts_at=datetime.strptime(stamp, "%Y%m%d%H%M"),
                laps_url=_pick(files["laps"]),
                results_url=_pick(files["results"]),
            )
        )
    return sessions
