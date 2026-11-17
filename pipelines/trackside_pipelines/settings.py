"""Runtime settings, read from the environment."""

import os
from datetime import date
from pathlib import Path

import psycopg


def connect() -> psycopg.Connection:
    """Autocommit, so each `conn.transaction()` block in a step commits on its own
    and a long step's progress survives a crash or retry."""
    return psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)


def raw_dir() -> Path:
    """Private storage for downloaded timing files. Never served or committed."""
    return Path(os.environ.get("RAW_DATA_DIR", "/data/raw"))


def timing_seasons() -> list[int]:
    """Seasons to load, e.g. TIMING_SEASONS=2024,2025,2026. Defaults to the last three."""
    raw = os.environ.get("TIMING_SEASONS")
    if raw:
        return [int(s) for s in raw.split(",") if s.strip()]
    this_year = date.today().year
    return [this_year - 2, this_year - 1, this_year]


def calendar_season() -> int:
    return int(os.environ.get("SEASON", date.today().year + 1))
