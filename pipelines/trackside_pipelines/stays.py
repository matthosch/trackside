"""Generate synthetic stays around each circuit and daily price snapshots.

Everything here is made up. Generation is deterministic: the same circuit always
gets the same listings, and the same (stay, event, date) always gets the same
price, so reruns and backfills are idempotent.
"""

import math
import random
from dataclasses import dataclass
from datetime import date, timedelta

import psycopg

from .photos import PHOTOS

STAYS_PER_CIRCUIT = 24

# photo category -> kind -> (sleeps options, base nightly price range in USD, title templates)
_KINDS = {
    "house": {
        "House": ((4, 6, 8), (180, 340), ("Modern house with double garage", "Glass-front house", "House with gated driveway", "Hillside house with carport")),
        "Villa": ((6, 8, 10), (320, 620), ("Villa with pool and garage", "Courtyard villa", "Villa with paddock parking")),
        "Guest house": ((2, 4), (110, 190), ("Guest house behind the main home", "Garage loft", "Pool house")),
        "Apartment": ((2, 3, 4), (90, 160), ("Apartment with secure parking", "Top-floor flat with terrace", "Garden apartment")),
    },
    "hotel": {
        "Hotel suite": ((2, 3, 4), (190, 420), ("Suite with valet parking", "Corner suite, covered parking", "Paddock club suite")),
        "Hotel room": ((1, 2), (95, 180), ("Double room, car park view", "Room with secure parking")),
    },
}


@dataclass(frozen=True)
class Stay:
    id: str
    circuit_id: str
    title: str
    kind: str
    sleeps: int
    distance_km: float
    bearing_deg: int
    base_price_usd: int
    photo_url: str
    photo_page: str
    photo_credit: str


def generate_stays(circuit_id: str, count: int = STAYS_PER_CIRCUIT) -> list[Stay]:
    rng = random.Random(f"stays:{circuit_id}")
    # No photo repeats within a circuit while the pool is large enough.
    photos = rng.sample(PHOTOS, count) if count <= len(PHOTOS) else rng.choices(PHOTOS, k=count)
    stays = []
    for n, photo in enumerate(photos):
        # The photo decides the kind, so a hotel picture never fronts a house.
        kinds = _KINDS[photo.category]
        kind = rng.choice(list(kinds))
        sleeps_options, (low, high), titles = kinds[kind]
        # Skewed toward the circuit: most listings within 15 km, a tail out to 40.
        distance = round(min(40.0, 0.8 + rng.expovariate(1 / 9)), 1)
        base = rng.randint(low, high)
        # Closer listings cost more.
        base = round(base * (1 + 0.35 * math.exp(-distance / 6)))
        stays.append(
            Stay(
                id=f"{circuit_id}-{n + 1:02d}",
                circuit_id=circuit_id,
                title=rng.choice(titles),
                kind=kind,
                sleeps=rng.choice(sleeps_options),
                distance_km=distance,
                bearing_deg=rng.randrange(360),
                base_price_usd=base,
                photo_url=photo.url,
                photo_page=photo.page,
                photo_credit=photo.username,
            )
        )
    return stays


def price_snapshot(stay: Stay, event_id: int, event_start: date, on: date) -> tuple[int, bool]:
    """Nightly price and availability for a stay on race weekend, as seen on `on`."""
    days_out = (event_start - on).days

    # Demand surge: about +140% at race week, fading over the preceding two months.
    surge = 1 + 1.4 * math.exp(-max(days_out, 0) / 18)
    noise = random.Random(f"price:{stay.id}:{event_id}:{on.isoformat()}").uniform(0.96, 1.04)
    price = round(stay.base_price_usd * surge * noise)

    # Each stay books up at a fixed lead time (or never), so availability only
    # ever goes from available to booked as the race approaches.
    booking = random.Random(f"booking:{stay.id}:{event_id}")
    booked_days_out = booking.expovariate(1 / 25) if booking.random() < 0.6 else None
    available = booked_days_out is None or days_out > booked_days_out
    return price, available


def load(conn: psycopg.Connection, today: date, backfill_days: int = 30) -> tuple[int, int]:
    """Upsert stays for every circuit and snapshots for upcoming events.

    Returns (stays written, snapshots written).
    """
    circuit_ids = [row[0] for row in conn.execute("SELECT id FROM circuits ORDER BY id")]
    stays_by_circuit = {cid: generate_stays(cid) for cid in circuit_ids}
    upcoming = conn.execute(
        "SELECT id, circuit_id, start_date FROM events "
        "WHERE circuit_id IS NOT NULL AND end_date >= %s",
        (today,),
    ).fetchall()

    snapshot_rows = []
    for event_id, circuit_id, start_date in upcoming:
        for stay in stays_by_circuit[circuit_id]:
            for offset in range(backfill_days, -1, -1):
                on = today - timedelta(days=offset)
                price, available = price_snapshot(stay, event_id, start_date, on)
                snapshot_rows.append((stay.id, event_id, on, price, available))

    stay_rows = [
        (s.id, s.circuit_id, s.title, s.kind, s.sleeps, s.distance_km, s.bearing_deg, s.base_price_usd,
         s.photo_url, s.photo_page, s.photo_credit)
        for stays in stays_by_circuit.values()
        for s in stays
    ]
    with conn.transaction(), conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO stays (id, circuit_id, title, kind, sleeps, distance_km, bearing_deg, base_price_usd,
                               photo_url, photo_page, photo_credit)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title, kind = EXCLUDED.kind, sleeps = EXCLUDED.sleeps,
                distance_km = EXCLUDED.distance_km, bearing_deg = EXCLUDED.bearing_deg,
                base_price_usd = EXCLUDED.base_price_usd, photo_url = EXCLUDED.photo_url,
                photo_page = EXCLUDED.photo_page, photo_credit = EXCLUDED.photo_credit
            """,
            stay_rows,
        )
        cur.executemany(
            """
            INSERT INTO stay_price_snapshots (stay_id, event_id, snapshot_date, nightly_price_usd, available)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (stay_id, event_id, snapshot_date) DO UPDATE SET
                nightly_price_usd = EXCLUDED.nightly_price_usd, available = EXCLUDED.available
            """,
            snapshot_rows,
        )
    return len(stay_rows), len(snapshot_rows)
