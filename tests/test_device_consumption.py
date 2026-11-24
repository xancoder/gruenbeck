"""
the values of the 14-day memory: what read_consumption() accepts before anything is
written (P006-S9)
"""

import datetime
import logging

import pytest

from gruenbeck import device

TODAY = datetime.date(2026, 11, 23)


def day(text: str) -> datetime.date:
    return datetime.date.fromisoformat(text)


def test_whole_numbers_are_the_consumption_of_the_day() -> None:
    result = device.read_consumption({"D_Y_2_1": "101", "D_Y_2_2": "0", "D_Y_2_14": "93"}, TODAY)

    assert result == {day("2026-11-22"): 101, day("2026-11-21"): 0, day("2026-11-09"): 93}
    assert all(type(value) is int for value in result.values())


def test_the_order_of_the_response_does_not_matter() -> None:
    in_order = {f"D_Y_2_{n}": str(n) for n in range(1, 15)}
    reversed_order = dict(reversed(list(in_order.items())))

    assert device.read_consumption(reversed_order, TODAY) == device.read_consumption(
        in_order, TODAY
    )


@pytest.mark.parametrize(
    "text, liters", [(" 93 ", 93), ("\n93\n", 93), ("007", 7), ("0", 0), ("1000000", 1000000)]
)
def test_blanks_and_leading_zeros_do_not_matter(text: str, liters: int) -> None:
    assert device.read_consumption({"D_Y_2_1": text}, TODAY) == {day("2026-11-22"): liters}


def test_a_place_without_value_is_left_out_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="gruenbeck")

    result = device.read_consumption({"D_Y_2_1": "5", "D_Y_2_2": "-", "D_Y_2_3": " - "}, TODAY)

    assert result == {day("2026-11-22"): 5}
    assert [(r.name, r.levelname, r.getMessage()) for r in caplog.records] == [
        ("gruenbeck.device", "WARNING", "no value for D_Y_2_2 (2026-11-21): not written"),
        ("gruenbeck.device", "WARNING", "no value for D_Y_2_3 (2026-11-20): not written"),
    ]


def test_valid_values_are_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="gruenbeck")

    device.read_consumption({"D_Y_2_1": "5"}, TODAY)

    assert caplog.records == []


@pytest.mark.parametrize(
    "value",
    ["", " ", "x", "1.5", "1,5", "-5", "+5", "1e3", "1_000", "--", "٣", "0x10", "NaN", None],
    ids=repr,
)
def test_any_other_value_is_an_error(value: str | None) -> None:
    with pytest.raises(device.DeviceError) as err:
        device.read_consumption({"D_Y_2_1": "5", "D_Y_2_4": value}, TODAY)

    assert str(err.value) == (
        "invalid consumption values (expected a whole number 0 or greater, or '-'):"
        f" D_Y_2_4 (2026-11-19) {value!r}"
    )


def test_every_invalid_value_is_named() -> None:
    response = {"D_Y_2_1": "x", "D_Y_2_2": "7", "D_Y_2_3": None, "D_Y_2_4": "-", "D_Y_2_5": "-1"}

    with pytest.raises(device.DeviceError) as err:
        device.read_consumption(response, TODAY)

    assert str(err.value) == (
        "invalid consumption values (expected a whole number 0 or greater, or '-'):"
        " D_Y_2_1 (2026-11-22) 'x'; D_Y_2_3 (2026-11-20) None; D_Y_2_5 (2026-11-18) '-1'"
    )


def test_only_places_without_value_are_an_error() -> None:
    response = {f"D_Y_2_{n}": "-" for n in range(1, 15)}

    with pytest.raises(device.DeviceError) as err:
        device.read_consumption(response, TODAY)

    assert str(err.value) == "the device has no consumption value: all 14 values are '-'"


def test_a_response_without_values_is_an_error() -> None:
    with pytest.raises(device.DeviceError, match="all 0 values"):
        device.read_consumption({}, TODAY)


def test_unknown_parameter_is_an_error() -> None:
    with pytest.raises(device.DeviceError) as err:
        device.read_consumption({"D_Y_2_1": "5", "D_Y_1": "-"}, TODAY)

    assert str(err.value) == (
        "unknown consumption parameter 'D_Y_1': expected D_Y_2_<n> (consumption of n days ago)"
    )
