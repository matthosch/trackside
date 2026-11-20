import pytest

from trackside_pipelines import timing

# Real column layout, invented rows.
LAP_HEADER = (
    "NUMBER;DRIVER_NUMBER;LAP_NUMBER;LAP_TIME;LAP_IMPROVEMENT;CROSSING_FINISH_LINE_IN_PIT;S1;S1_IMPROVEMENT;"
    "S2;S2_IMPROVEMENT;S3;S3_IMPROVEMENT;KPH;ELAPSED;HOUR;S1_LARGE;S2_LARGE;S3_LARGE;TOP_SPEED;DRIVER_NAME;"
    "PIT_TIME;CLASS;GROUP;TEAM;MANUFACTURER;FLAG_AT_FL;"
)
LAPS = "\n".join([
    LAP_HEADER,
    "023;1;1;1:25.100;0;;30.000;0;30.000;0;25.100;0;160.0;1:25.100;12:01:00.000;;;;;Ann Driver;;GTD;;Team A;Make A;GF;",
    "023;1;2;1:20.250;1;B;29.000;0;27.000;0;24.250;0;170.0;2:45.350;12:02:20.250;;;;;Ann Driver;;GTD;;Team A;Make A;GF;",
    "12;2;1;1:21.000;0;;29.500;0;27.000;0;24.500;0;168.0;1:21.000;12:01:00.000;;;;;Bo Driver;;GTD PRO;;Team B;Make B;FCY;",
    "31;1;1;1:12.000;0;;25.000;0;25.000;0;22.000;0;190.0;1:12.000;12:01:00.000;;;;;Prototype;;GTP;;Team C;Make C;GF;",
    ";;;;;;;;;;;;;;;;;;;;;;;;;;",
])
RESULTS = "\n".join([
    "POSITION;NUMBER;STATUS;LAPS;TEAM;CLASS;VEHICLE;",
    "1;023;Classified;2;Team A;GTD;Make A GT3;",
    "2;12;Classified;1;Team B;GTD PRO;Make B GT3 EVO;",
])


def encode(text: str) -> bytes:
    return ("﻿" + text).encode("utf-8")  # the files carry a UTF-8 BOM


@pytest.mark.parametrize(
    "value, expected",
    [("2:13.827", 133827), ("27.475", 27475), ("0:27.475", 27475), ("1:02:03.5", 3723500), ("", None), ("-", None)],
)
def test_parse_time(value, expected):
    assert timing.parse_time_ms(value) == expected


def test_parse_laps_filters_classes_and_normalises():
    laps = timing.parse_laps(encode(LAPS), frozenset({"GTD", "GTDPRO"}))
    assert [(lap.car_number, lap.lap_number, lap.class_) for lap in laps] == [
        ("023", 1, "GTD"), ("023", 2, "GTD"), ("12", 1, "GTDPRO"),
    ]
    in_lap = laps[1]
    assert in_lap.in_pit and in_lap.lap_time_ms == 80250 and in_lap.s3_ms == 24250
    assert laps[2].flag == "FCY"


def test_parse_laps_keeps_every_class_when_unfiltered():
    assert len(timing.parse_laps(encode(LAPS))) == 4


def test_results_numbers_match_lap_numbers():
    entries = {e.car_number: e for e in timing.parse_results(encode(RESULTS))}
    assert entries["023"].vehicle == "Make A GT3"
    assert entries["12"].class_ == "GTDPRO"


def test_leading_zeros_are_part_of_the_number():
    # IMSA runs #023 and #23 as different cars, sometimes in the same race.
    assert timing.car_number(" 023 ") == "023"
    assert timing.car_number("023") != timing.car_number("23")


def test_results_can_be_filtered_by_class():
    entries = timing.parse_results(encode(RESULTS), frozenset({"GTD"}))
    assert [e.car_number for e in entries] == ["023"]


def test_missing_columns_raise_a_schema_error():
    renamed = LAPS.replace("FLAG_AT_FL", "FLAG")
    with pytest.raises(timing.SchemaError, match="FLAG_AT_FL"):
        timing.parse_laps(encode(renamed))
    with pytest.raises(timing.SchemaError):
        timing.parse_results(b"")
