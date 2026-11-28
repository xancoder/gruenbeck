"""gruenbeck-log-rollover: log of the daily rollover of the device values"""

import collections.abc
import csv
import datetime
import json
import pathlib
import typing

import pytest
import requests

from gruenbeck import device, rollover

CET = datetime.timezone(datetime.timedelta(hours=1))
START = datetime.datetime(2026, 11, 18, 9, 30, tzinfo=CET)


class FakeClock:
    """replaces now() and sleep(); a request takes `request_seconds`"""

    def __init__(self, request_seconds: float = 0.0) -> None:
        self.current = START
        self.request_seconds = request_seconds
        self.sleeps: list[float] = []

    def now(self) -> datetime.datetime:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.current += datetime.timedelta(seconds=seconds)


Response = dict[str, str] | Exception


class FakeFetch:
    """fake fetch: returns or raises the given responses in order; `calls` records them"""

    def __init__(self, clock: FakeClock, responses: collections.abc.Sequence[Response]) -> None:
        self.clock = clock
        self.responses = responses
        self.calls: list[tuple[str, list[str], float]] = []

    def __call__(
        self, host: str, parameters: collections.abc.Iterable[str], timeout: float
    ) -> dict[str, str]:
        self.calls.append((host, list(parameters), timeout))
        self.clock.current += datetime.timedelta(seconds=self.clock.request_seconds)
        response = self.responses[len(self.calls) - 1]
        if isinstance(response, Exception):
            raise response
        return response


def values(d1: str, d2: str, d3: str = "170", clock: str = "01:05") -> dict[str, str]:
    return {"D_C_4_2": clock, "D_Y_2_1": d1, "D_Y_2_2": d2, "D_Y_2_3": d3}


def run(
    tmp_path: pathlib.Path,
    responses: collections.abc.Sequence[Response],
    interval: float = 300,
    hours: float | None = None,
    clock: FakeClock | None = None,
) -> tuple[int, list[dict[str, str]], FakeFetch, FakeClock]:
    clock = clock or FakeClock()
    if hours is None:
        hours = (len(responses) - 1) * interval / 3600
    fetch = FakeFetch(clock, responses)
    output = tmp_path / "log" / "device_rollover.csv"
    # like main(): continue the comparison of an earlier run in the same file
    count = rollover.run(
        "device.lan",
        12.5,
        output,
        interval,
        hours,
        fetch=fetch,
        now=clock.now,
        sleep=clock.sleep,
        previous_row=rollover.last_complete_row(output),
    )
    return count, read_rows(output), fetch, clock


def read_rows(output: pathlib.Path) -> list[dict[str, str]]:
    with output.open(newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


def test_row_format_with_local_time_offset_and_device_values(tmp_path: pathlib.Path) -> None:
    count, rows, fetch, _ = run(tmp_path, [values("93", "33")])

    assert count == 1
    assert rows == [
        {
            "time": "2026-11-18T09:30:00+01:00",
            "device_clock": "01:05",
            "D_Y_2_1": "93",
            "D_Y_2_2": "33",
            "D_Y_2_3": "170",
            "status": "ok",
            "message": "",
        }
    ]
    assert fetch.calls == [("device.lan", ["D_C_4_2", "D_Y_2_1", "D_Y_2_2", "D_Y_2_3"], 12.5)]


def test_header_is_written_only_once_across_runs(tmp_path: pathlib.Path) -> None:
    run(tmp_path, [values("93", "33")])
    run(tmp_path, [values("93", "33")])

    lines = (tmp_path / "log" / "device_rollover.csv").read_text().splitlines()
    assert lines[0] == ",".join(rollover.FIELDNAMES)
    assert len(lines) == 3
    assert lines.count(lines[0]) == 1


def test_failed_request_is_logged_and_logging_continues(tmp_path: pathlib.Path) -> None:
    responses: list[Response] = [
        requests.exceptions.ConnectionError("Remote end closed connection"),
        ValueError("[-] device response contains no values"),
        values("93", "33"),
    ]
    count, rows, _, _ = run(tmp_path, responses)

    assert count == 3
    assert [row["status"] for row in rows] == ["error", "error", "ok"]
    assert rows[0]["message"] == "ConnectionError: Remote end closed connection"
    assert rows[1]["message"] == "ValueError: [-] device response contains no values"
    assert rows[0]["D_Y_2_1"] == ""


def test_rollover_is_detected_when_values_move_on(tmp_path: pathlib.Path) -> None:
    responses: list[Response] = [values("93", "33"), values("93", "33"), values("41", "93", "33")]
    _, rows, _, _ = run(tmp_path, responses)

    assert [row["status"] for row in rows] == ["ok", "ok", "rollover"]
    assert rows[2]["message"] == "D_Y_2_1 93 -> 41, D_Y_2_2 33 -> 93"


def test_incomplete_response_is_no_rollover(tmp_path: pathlib.Path) -> None:
    responses: list[Response] = [
        values("93", "33"),
        {"D_C_4_2": "01:10", "D_Y_2_1": "93"},
        values("-", "33"),
        requests.exceptions.Timeout("timed out"),
        values("93", "33"),
        values("41", "93", "33"),
    ]
    _, rows, _, _ = run(tmp_path, responses)

    assert [row["status"] for row in rows] == [
        "ok",
        "error",
        "error",
        "error",
        "ok",
        "rollover",
    ]
    assert rows[1]["message"] == "incomplete response: D_Y_2_2, D_Y_2_3"
    assert rows[2]["message"] == "incomplete response: D_Y_2_1"
    assert rows[1]["device_clock"] == "01:10"


def test_first_complete_response_after_errors_is_no_rollover(tmp_path: pathlib.Path) -> None:
    responses: list[Response] = [requests.exceptions.ConnectionError("refused"), values("93", "33")]
    _, rows, _, _ = run(tmp_path, responses)

    assert [row["status"] for row in rows] == ["error", "ok"]


def test_run_ends_after_hours_and_keeps_the_schedule(tmp_path: pathlib.Path) -> None:
    clock = FakeClock(request_seconds=20)
    responses: list[Response] = [values("93", "33")] * 10
    count, rows, _, clock = run(tmp_path, responses, interval=600, hours=1, clock=clock)

    # polls at 0, 10, ..., 60 minutes: slow requests do not shift the schedule
    assert count == 7
    assert clock.sleeps == [580] * 6
    assert rows[-1]["time"] == "2026-11-18T10:30:20+01:00"


def test_keyboard_interrupt_stops_cleanly(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"softWaterSystem": {"host": "device.lan"}}))

    def interrupted(*args: object, **kwargs: object) -> typing.NoReturn:
        raise KeyboardInterrupt

    monkeypatch.setattr(rollover, "run", interrupted)

    assert rollover.main(["-c", str(config)]) == 0
    assert "[*] stopped" in capsys.readouterr().out


def test_main_passes_device_config_and_options_to_run(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"softWaterSystem": {"host": "device.lan", "timeout": 7}}))
    seen: dict[str, typing.Any] = {}

    def fake_run(
        host: str,
        timeout: float,
        output: pathlib.Path,
        interval: float,
        hours: float,
        previous_row: dict[str, str] | None,
    ) -> int:
        seen.update(
            host=host,
            timeout=timeout,
            output=output,
            interval=interval,
            hours=hours,
            previous_row=previous_row,
        )
        return 0

    monkeypatch.setattr(rollover, "run", fake_run)
    output = tmp_path / "out.csv"
    argv = ["-c", str(config), "--interval", "60", "--hours", "2", "--output", str(output)]

    assert rollover.main(argv) == 0
    assert seen == {
        "host": "device.lan",
        "timeout": 7.0,
        "output": output,
        "interval": 60.0,
        "hours": 2.0,
        "previous_row": None,
    }


def test_main_continues_from_last_complete_row(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"softWaterSystem": {"host": "device.lan"}}))
    output = tmp_path / "out.csv"
    run(tmp_path, [values("105", "93")])
    (tmp_path / "log" / "device_rollover.csv").rename(output)
    seen: dict[str, typing.Any] = {}

    def fake_run(*args: object, previous_row: dict[str, str] | None) -> int:
        seen.update(row=previous_row)
        return 0

    monkeypatch.setattr(rollover, "run", fake_run)

    assert rollover.main(["-c", str(config), "--output", str(output)]) == 0
    assert seen["row"]["D_Y_2_1"] == "105"
    assert "comparing with the last complete row of 2026-11-18T09:30:00+01:00" in (
        capsys.readouterr().out
    )


def test_rollover_between_two_runs_is_detected(tmp_path: pathlib.Path) -> None:
    run(tmp_path, [values("105", "93")])
    _, rows, _, _ = run(tmp_path, [values("9", "105", "93"), values("9", "105", "93")])

    assert [row["status"] for row in rows] == ["ok", "rollover", "ok"]
    assert rows[1]["message"] == (
        "D_Y_2_1 105 -> 9, D_Y_2_2 93 -> 105 (since 2026-11-18T09:30:00+01:00)"
    )


def test_no_rollover_between_two_runs_with_same_values(tmp_path: pathlib.Path) -> None:
    run(tmp_path, [values("105", "93")])
    _, rows, _, _ = run(tmp_path, [values("105", "93")])

    assert [row["status"] for row in rows] == ["ok", "ok"]


def test_errors_at_the_end_of_the_earlier_run_are_skipped(tmp_path: pathlib.Path) -> None:
    run(tmp_path, [values("105", "93"), requests.exceptions.ConnectionError("refused")])
    responses: list[Response] = [
        ValueError("[-] device response contains no values"),
        values("9", "105", "93"),
        values("41", "9", "105"),
    ]
    _, rows, _, _ = run(tmp_path, responses)

    statuses = [row["status"] for row in rows]
    assert statuses == ["ok", "error", "error", "rollover", "rollover"]
    assert rows[3]["message"].endswith("(since 2026-11-18T09:30:00+01:00)")
    # later rollovers in the same run compare with the previous poll only
    assert "since" not in rows[4]["message"]


def test_empty_file_gets_a_header(tmp_path: pathlib.Path) -> None:
    output = tmp_path / "log" / "device_rollover.csv"
    output.parent.mkdir()
    output.touch()

    assert rollover.last_complete_row(output) is None
    _, rows, _, _ = run(tmp_path, [values("93", "33")])
    assert [row["status"] for row in rows] == ["ok"]


def test_foreign_file_is_not_appended_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"softWaterSystem": {"host": "device.lan"}}))
    output = tmp_path / "gruenbeck_water_consumption_2026.csv"
    output.write_text("date,value\n2026-11-16,170\n")

    def unexpected(*args: object, **kwargs: object) -> typing.NoReturn:
        raise AssertionError("run must not start")

    monkeypatch.setattr(rollover, "run", unexpected)

    assert rollover.main(["-c", str(config), "--output", str(output)]) == 1
    assert "[-] not appending:" in capsys.readouterr().err
    assert output.read_text() == "date,value\n2026-11-16,170\n"


def test_default_timeout_comes_from_gruenbeck(tmp_path: pathlib.Path) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"softWaterSystem": {"host": "device.lan"}}))

    assert rollover.read_device_config(str(config)) == (
        "device.lan",
        float(device.DEFAULT_TIMEOUT),
    )


@pytest.mark.parametrize(
    ("config", "message"),
    [
        (None, "[-] no configuration: [Errno 2] No such file or directory: "),
        ({}, "[-] invalid configuration: no config parameter: 'softWaterSystem'"),
        (
            {"softWaterSystem": "device.lan"},
            "[-] invalid configuration: invalid config parameter softWaterSystem 'device.lan':"
            " expected an object",
        ),
        (
            {"softWaterSystem": {}},
            "[-] invalid configuration: no config parameter: 'softWaterSystem.host'",
        ),
        (
            {"softWaterSystem": {"host": ["a"]}},
            "[-] invalid configuration: invalid config parameter softWaterSystem.host ['a']:"
            " expected a non-empty text",
        ),
        (
            {"softWaterSystem": {"host": "h", "timeout": 0}},
            "[-] invalid configuration: invalid config parameter softWaterSystem.timeout 0:"
            " must be a number greater than 0",
        ),
        (
            {"softWaterSystem": {"host": "h", "timeout": "x"}},
            "[-] invalid configuration: invalid config parameter softWaterSystem.timeout 'x':"
            " could not convert string to float: 'x'",
        ),
        (
            {"softWaterSystem": {"timeout": 0}},
            "[-] invalid configuration: no config parameter: 'softWaterSystem.host';"
            " invalid config parameter softWaterSystem.timeout 0: must be a number greater than 0",
        ),
        ([], "[-] invalid configuration: configuration file "),
    ],
)
def test_invalid_configuration_exits_with_1(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    config: typing.Any,
    message: str,
) -> None:
    config_file = tmp_path / "config.json"
    if config is not None:
        config_file.write_text(json.dumps(config))

    def unexpected(*args: object, **kwargs: object) -> typing.NoReturn:
        raise AssertionError("the device must not be asked")

    monkeypatch.setattr(rollover, "run", unexpected)

    assert rollover.main(["-c", str(config_file)]) == 1
    captured = capsys.readouterr()
    # one line on stderr, no traceback, nothing on stdout
    assert captured.err.startswith(message)
    assert captured.err.count("\n") == 1
    assert "Traceback" not in captured.err
    assert captured.out == ""


def test_other_sections_of_the_configuration_are_not_needed(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"softWaterSystem": {"host": "device.lan"}, "mail": 5}))
    monkeypatch.setattr(rollover, "run", lambda *args, **kwargs: 0)

    assert rollover.main(["-c", str(config)]) == 0
    assert capsys.readouterr().err == ""


def test_clock_parameter_is_the_one_of_the_data_collector() -> None:
    assert rollover.CLOCK_PARAMETER == device.DEVICE_CLOCK_PARAMETER


@pytest.mark.parametrize("option", ["--interval", "--hours"])
@pytest.mark.parametrize("value", ["0", "-5"])
def test_interval_and_hours_must_be_positive(option: str, value: str) -> None:
    with pytest.raises(SystemExit):
        rollover.parse_args([option, value])
