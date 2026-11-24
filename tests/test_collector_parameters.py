import collections.abc

import pytest

# the fixture device is the fake device, so the module is used as gruenbeck.device
import gruenbeck.device

MEMORY = [f"D_Y_2_{n}" for n in range(1, 15)]


@pytest.fixture
def device(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """fake device; records the parameters of every request"""
    requests: list[list[str]] = []

    def fetch(
        host: str,
        parameters: collections.abc.Iterable[str],
        timeout: float,
        session: object = None,
    ) -> dict[str, str | None]:
        requests.append(list(parameters))
        return {name: "1" for name in parameters}

    monkeypatch.setattr(gruenbeck.device, "get_data_from_mux_http", fetch)
    return requests


def test_only_the_14_day_memory_is_requested(device: list[list[str]]) -> None:
    result = gruenbeck.device.get_device_data("device.lan", 30, 5, 5)

    # plus the device clock for check_device_clock() (P004-S8)
    assert device == [["D_C_4_2", *MEMORY]]
    assert list(result) == ["D_C_4_2", *MEMORY]
