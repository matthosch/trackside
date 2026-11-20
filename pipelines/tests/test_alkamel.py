from datetime import datetime
from pathlib import Path

from trackside_pipelines import alkamel

PAGE = (Path(__file__).parent / "fixtures" / "alkamel_event.html").read_text(encoding="utf-8")
PAGE_URL = "https://imsa.results.alkamelcloud.com/?season=25_2025&evvent=22_Road+Atlanta"
BASE = "https://imsa.results.alkamelcloud.com/Results/25_2025/22_Road%20Atlanta/01_IMSA%20WeatherTech%20SportsCar%20Championship"
CIRCUITS = [
    ("road-atlanta", "Michelin Raceway Road Atlanta", ["Road Atlanta"]),
    ("cota", "Circuit of The Americas", ["COTA"]),
    ("indianapolis", "Indianapolis Motor Speedway", ["Indianapolis"]),
]


def sessions():
    return {s.session_name: s for s in alkamel.discover_sessions(PAGE, PAGE_URL, alkamel.SOURCES["imsa"])}


def test_only_sessions_of_the_series_in_scope():
    found = sessions()
    assert set(found) == {"Practice 1", "Race"}
    assert all("WeatherTech" in s.series_folder for s in found.values())


def test_sro_skips_sessions_shared_with_other_series():
    # Shared test days list GT World Challenge cars as "163C" next to GT America's
    # "013A", so the same car would show up under two numbers.
    matches = alkamel.SOURCES["sro_america"].series_matches
    assert matches("01_GT World Challenge America powered by AWS")
    assert not matches("07_GT World Challenge America powered by AWS - GT America powered by AWS")
    assert not matches("03_GT America powered by AWS")


def test_session_metadata():
    race = sessions()["Race"]
    assert race.season == 2025
    assert race.event_folder == "22_Road Atlanta"
    assert race.session_type == "race"
    assert race.starts_at == datetime(2025, 10, 11, 12, 10)


def test_race_uses_the_last_hour_and_the_most_final_results():
    race = sessions()["Race"]
    assert race.laps_url == f"{BASE}/202510111210_Race/10_Hour%2010/23_Time%20Cards_Race.CSV"
    assert race.results_url == f"{BASE}/202510111210_Race/10_Hour%2010/03_Results_Race_Official.CSV"


def test_filename_variants_and_suffixes():
    practice = sessions()["Practice 1"]
    assert practice.laps_url.endswith("/23_Time_Cards_Practice%201.csv")
    # A plain results file beats a provisional one.
    assert practice.results_url.endswith("/03_Results_Practice%201.CSV")


def test_season_and_event_options():
    assert alkamel.season_value(PAGE, 2024) == "24_2024"
    assert alkamel.season_value(PAGE, 2019) is None
    assert alkamel.select_options(PAGE, "evvent")[1] == ("22_Road Atlanta", "Road Atlanta")


def test_venue_labels_match_circuits():
    assert alkamel.match_circuit("Road Atlanta", CIRCUITS) == "road-atlanta"
    assert alkamel.match_circuit("Circuit of the Americas (VPRC)", CIRCUITS) == "cota"
    assert alkamel.match_circuit("Indianapolis Motor Speedway RC", CIRCUITS) == "indianapolis"
    assert alkamel.match_circuit("Sebring International Raceway", CIRCUITS) is None


def test_session_types():
    assert alkamel.session_type("Qualify Driver 1") == "qualifying"
    assert alkamel.session_type("Race 2") == "race"
    assert alkamel.session_type("Warm Up") == "practice"
    assert alkamel.session_type("GTWCA Test Session 1") == "test"


def test_listing_url_keeps_the_sites_parameter_names():
    url = alkamel.listing_url(alkamel.SOURCES["sro_america"], "25_2025", "06_Road America")
    assert url == "https://usac.alkamelsystems.com/?series=06_SRO&season=25_2025&evvent=06_Road+America"
