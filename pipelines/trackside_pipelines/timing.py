"""Parse Al Kamel lap and results CSVs into staging rows."""

import csv
import io
import re
from dataclasses import dataclass

LAP_COLUMNS = (
    "NUMBER", "DRIVER_NUMBER", "LAP_NUMBER", "LAP_TIME", "CROSSING_FINISH_LINE_IN_PIT",
    "S1", "S2", "S3", "DRIVER_NAME", "CLASS", "TEAM", "MANUFACTURER", "FLAG_AT_FL",
)
RESULTS_COLUMNS = ("NUMBER", "CLASS", "TEAM", "VEHICLE")

_TIME = re.compile(r"^(?:(?:(\d+):)?(\d+):)?(\d+(?:\.\d+)?)$")


class SchemaError(Exception):
    """A file is missing columns the loader depends on."""


@dataclass(frozen=True)
class Lap:
    car_number: str
    lap_number: int
    driver_number: int | None
    driver_name: str | None
    lap_time_ms: int | None
    s1_ms: int | None
    s2_ms: int | None
    s3_ms: int | None
    in_pit: bool
    flag: str | None
    class_: str
    team: str | None
    manufacturer: str | None


@dataclass(frozen=True)
class Entry:
    car_number: str
    class_: str
    team: str
    vehicle: str


def parse_time_ms(value: str) -> int | None:
    """'2:13.827' -> 133827; '1:02:03.5' -> 3723500; '' -> None."""
    match = _TIME.match(value.strip())
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    total = int(hours or 0) * 3600 + int(minutes or 0) * 60 + float(seconds)
    return round(total * 1000)


def car_number(value: str) -> str:
    """IMSA lap files pad numbers ('021'), results files do not ('21')."""
    return value.strip().lstrip("0") or "0"


def normalise_class(value: str) -> str:
    """'GTD PRO' and 'GTDPRO' are the same class."""
    return re.sub(r"\s+", "", value.strip()).upper()


def _rows(data: bytes, required: tuple[str, ...]) -> list[dict[str, str]]:
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text), delimiter=";")
    try:
        header = [h.strip() for h in next(reader)]
    except StopIteration:
        raise SchemaError("file is empty") from None
    missing = [c for c in required if c not in header]
    if missing:
        raise SchemaError(f"missing columns: {', '.join(missing)}")
    return [
        {h: (row[i].strip() if i < len(row) else "") for i, h in enumerate(header) if h}
        for row in reader
        if any(cell.strip() for cell in row)
    ]


def _int(value: str) -> int | None:
    return int(value) if value.strip().isdigit() else None


def parse_laps(data: bytes, classes: frozenset[str] | None = None) -> list[Lap]:
    laps = []
    for row in _rows(data, LAP_COLUMNS):
        class_ = normalise_class(row["CLASS"])
        lap_number = _int(row["LAP_NUMBER"])
        if lap_number is None or (classes is not None and class_ not in classes):
            continue
        laps.append(
            Lap(
                car_number=car_number(row["NUMBER"]),
                lap_number=lap_number,
                driver_number=_int(row["DRIVER_NUMBER"]),
                driver_name=row["DRIVER_NAME"] or None,
                lap_time_ms=parse_time_ms(row["LAP_TIME"]),
                s1_ms=parse_time_ms(row["S1"]),
                s2_ms=parse_time_ms(row["S2"]),
                s3_ms=parse_time_ms(row["S3"]),
                in_pit=row["CROSSING_FINISH_LINE_IN_PIT"].upper() == "B",
                flag=row["FLAG_AT_FL"] or None,
                class_=class_,
                team=row["TEAM"] or None,
                manufacturer=row["MANUFACTURER"] or None,
            )
        )
    return laps


def parse_results(data: bytes, classes: frozenset[str] | None = None) -> list[Entry]:
    entries = {}
    for row in _rows(data, RESULTS_COLUMNS):
        class_ = normalise_class(row["CLASS"])
        if not row["NUMBER"] or (classes is not None and class_ not in classes):
            continue
        number = car_number(row["NUMBER"])
        entries[number] = Entry(number, class_, row["TEAM"], row["VEHICLE"])
    return list(entries.values())
