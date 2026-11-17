from datetime import date, timedelta

from trackside_pipelines.photos import PHOTOS
from trackside_pipelines.stays import STAYS_PER_CIRCUIT, generate_stays, price_snapshot

RACE = date(2027, 4, 2)
HOTEL_URLS = {p.url for p in PHOTOS if p.category == "hotel"}


def test_generation_is_deterministic_per_circuit():
    assert generate_stays("sonoma") == generate_stays("sonoma")
    assert generate_stays("sonoma") != generate_stays("cota")


def test_stays_have_unique_ids_and_sane_values():
    stays = generate_stays("sonoma")
    assert len({s.id for s in stays}) == len(stays) == STAYS_PER_CIRCUIT
    for stay in stays:
        assert 0 < stay.distance_km <= 40
        assert 0 <= stay.bearing_deg < 360
        assert stay.base_price_usd > 0 and stay.sleeps > 0


def test_each_stay_in_a_circuit_has_its_own_credited_photo():
    stays = generate_stays("sonoma")
    assert len({s.photo_url for s in stays}) == len(stays)
    for stay in stays:
        assert stay.photo_url.startswith("https://images.unsplash.com/photo-")
        assert stay.photo_page.startswith("https://unsplash.com/photos/")
        assert stay.photo_credit
        assert ("Hotel" in stay.kind) == (stay.photo_url in HOTEL_URLS)


def test_price_rises_toward_race_weekend():
    stay = generate_stays("sonoma")[0]
    far, _ = price_snapshot(stay, 1, RACE, RACE - timedelta(days=120))
    near, _ = price_snapshot(stay, 1, RACE, RACE - timedelta(days=2))
    assert near > far * 1.8


def test_snapshot_is_repeatable():
    stay = generate_stays("sonoma")[0]
    on = RACE - timedelta(days=30)
    assert price_snapshot(stay, 1, RACE, on) == price_snapshot(stay, 1, RACE, on)


def test_a_booked_stay_never_becomes_available_again():
    for stay in generate_stays("sonoma"):
        seen_booked = False
        for days_out in range(150, -1, -1):
            _, available = price_snapshot(stay, 1, RACE, RACE - timedelta(days=days_out))
            assert not (seen_booked and available)
            seen_booked = seen_booked or not available
