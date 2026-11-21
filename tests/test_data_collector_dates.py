import csv
import datetime
import json
import logging

import pytest

from gruenbeck import cli, device, mail

PREFIX = "gruenbeck_water_consumption"
TODAY = datetime.date(2026, 11, 23)
PARAMETERS = [f"D_Y_2_{n}" for n in range(1, 15)]


def day(text):
    return datetime.date.fromisoformat(text)


@pytest.fixture
def mails(monkeypatch):
    """records data and error mails instead of sending them"""
    sent = []
    monkeypatch.setattr(
        mail,
        "send_mail",
        lambda param, data_folder: sent.append(("data", data_folder)),
    )
    monkeypatch.setattr(
        mail,
        "send_mail_text",
        lambda param, subject, text: sent.append(("error", text)),
    )
    return sent


# --- mapping of the parameter name to the day ---------------------------------------


def test_parameter_name_gives_the_day():
    response = {name: str(100 + n) for n, name in enumerate(PARAMETERS, start=1)}

    result = device.add_timestamp_as_key_device_data(response, today=TODAY)

    assert result == {TODAY - datetime.timedelta(days=n): str(100 + n) for n in range(1, 15)}
    assert result[day("2026-11-22")] == "101"  # D_Y_2_1: yesterday
    assert result[day("2026-11-09")] == "114"  # D_Y_2_14: 14 days ago


def test_order_of_the_response_does_not_matter():
    in_order = {name: str(n) for n, name in enumerate(PARAMETERS, start=1)}
    shuffled = {name: in_order[name] for name in [*PARAMETERS[7:], *PARAMETERS[:7]]}
    reversed_order = dict(reversed(list(in_order.items())))

    expected = device.add_timestamp_as_key_device_data(in_order, today=TODAY)

    for response in (shuffled, reversed_order):
        assert device.add_timestamp_as_key_device_data(response, today=TODAY) == expected


def test_days_are_calendar_dates_of_the_current_day():
    before = datetime.date.today()
    result = device.add_timestamp_as_key_device_data({"D_Y_2_1": "93"})
    after = datetime.date.today()

    (key,) = result
    assert type(key) is datetime.date
    assert key in {before - datetime.timedelta(days=1), after - datetime.timedelta(days=1)}


def test_run_time_is_the_local_time_without_time_zone():
    before = datetime.datetime.now()
    now = cli.local_now()
    after = datetime.datetime.now()

    assert type(now) is datetime.datetime
    assert now.tzinfo is None
    assert before <= now <= after


def test_year_change():
    response = {"D_Y_2_1": "1", "D_Y_2_2": "2", "D_Y_2_3": "3", "D_Y_2_14": "14"}

    result = device.add_timestamp_as_key_device_data(response, today=day("2026-01-02"))

    assert result == {
        day("2026-01-01"): "1",
        day("2025-12-31"): "2",
        day("2025-12-30"): "3",
        day("2025-12-19"): "14",
    }


def test_more_than_14_days_ago():
    result = device.add_timestamp_as_key_device_data({"D_Y_2_27": "80"}, today=TODAY)

    assert result == {day("2026-10-27"): "80"}


@pytest.mark.parametrize(
    "name", ["D_Y_1", "D_Y_2_0", "D_Y_2_01", "D_Y_2_x", "D_Y_2_1x", "d_y_2_1", "code"]
)
def test_unknown_parameter_is_an_error(name):
    response = {"D_Y_2_1": "93", name: "33"}

    with pytest.raises(ValueError) as err:
        device.add_timestamp_as_key_device_data(response, today=TODAY)

    assert str(err.value) == (
        f"[-] unknown consumption parameter {name!r}:"
        " expected D_Y_2_<n> (consumption of n days ago)"
    )


# --- dataFile.firstDate ------------------------------------------------------------


def test_first_date_is_optional():
    assert cli.get_first_date({"dataFile": {"prefix": PREFIX}}) is None


def test_first_date_without_data_file_section_is_an_error(mails, caplog):
    with pytest.raises(SystemExit) as exit_info:
        cli.get_first_date({"mail": {}})

    assert exit_info.value.code == 1
    assert "[-] no config parameter: 'dataFile'" in caplog.text
    assert mails == [("error", "[-] no config parameter: 'dataFile'")]


def test_first_date_is_read_as_date():
    config = {"dataFile": {"firstDate": "2026-11-20"}}

    assert cli.get_first_date(config) == day("2026-11-20")


@pytest.mark.parametrize(
    "value",
    ["20.11.2026", "2026-11-31", "2026-1-5", "20261120", "2026-11-20T00:00", "", 20261120, None],
    ids=repr,
)
def test_invalid_first_date_is_a_configuration_error(mails, caplog, value):
    config = {"dataFile": {"firstDate": value}, "mail": {}}

    with pytest.raises(SystemExit) as exit_info:
        cli.get_first_date(config)

    assert exit_info.value.code == 1
    message = f"[-] invalid config parameter dataFile.firstDate {value!r}"
    assert message in caplog.text
    assert mails[0][0] == "error"
    assert mails[0][1].startswith(message)


def test_first_date_filters_earlier_days(caplog):
    caplog.set_level(logging.INFO, logger=cli.logger.name)
    device_data = {
        day("2026-11-22"): "101",
        day("2026-11-20"): "103",
        day("2026-11-19"): "12",
        day("2026-11-18"): "9",
    }

    result = cli.filter_first_date({}, device_data, day("2026-11-20"))

    assert result == {day("2026-11-22"): "101", day("2026-11-20"): "103"}
    assert "[*] 2 values before dataFile.firstDate 2026-11-20 are not written" in (caplog.text)


def test_without_first_date_nothing_is_filtered(caplog):
    caplog.set_level(logging.INFO, logger=cli.logger.name)
    device_data = {day("2025-01-01"): "1", day("2026-11-22"): "101"}

    assert cli.filter_first_date({}, device_data, None) == device_data
    assert cli.filter_first_date({}, device_data, day("2025-01-01")) == device_data
    assert "firstDate" not in caplog.text


def test_all_values_before_first_date_fail_the_run(mails, caplog):
    device_data = {day("2026-11-19"): "9", day("2026-11-18"): "105"}

    with pytest.raises(SystemExit) as exit_info:
        cli.filter_first_date({"mail": {}}, device_data, day("2026-11-20"))

    assert exit_info.value.code == 1
    assert (
        "[-] no data was processed: all 2 values are before dataFile.firstDate 2026-11-20"
    ) in caplog.text


# --- complete run ------------------------------------------------------------------


@pytest.fixture
def run(mails, monkeypatch, tmp_path, parameter_file):
    """
    run main() on `today` at `local_time` with a fake device response
    :return: function(response, today, local_time, device_clock, **data_file); the
        device adds D_C_4_2 = device_clock to the response (None: no device clock).
        Its attribute `requests` lists the parameters of every device request.
    """
    requests = []

    def run_main(response, today=TODAY, local_time="16:00", device_clock="16:00", **data_file):
        config = {
            "dataFile": {
                "datePattern": "%Y-%m-%d",
                "fieldnames": {"date": "date", "value": "value"},
                "prefix": PREFIX,
                **data_file,
            },
            "dataPath": str(tmp_path / "data"),
            "mail": {},
            "parameterFile": str(parameter_file),
            "softWaterSystem": {"host": "device.lan"},
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config))

        def fetch(host, parameters, timeout):
            requests.append(list(parameters))
            clock = {} if device_clock is None else {"D_C_4_2": device_clock}
            return {**clock, **response}

        now = datetime.datetime.combine(today, datetime.time.fromisoformat(local_time))
        monkeypatch.setattr(device, "get_data_from_mux_http", fetch)
        monkeypatch.setattr(cli, "local_now", lambda: now)
        cli.main(str(config_file))

    run_main.requests = requests  # type: ignore[attr-defined]  # read by the tests
    return run_main


def write_year(tmp_path, year, rows):
    path = tmp_path / "data" / f"{PREFIX}_{year}.csv"
    path.parent.mkdir(exist_ok=True)
    with path.open(mode="w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["date", "value"])
        writer.writerows(rows)


def read_year(tmp_path, year):
    path = tmp_path / "data" / f"{PREFIX}_{year}.csv"
    with path.open(newline="", encoding="utf-8") as csv_file:
        return {row["date"]: row["value"] for row in csv.DictReader(csv_file)}


# device memory on 2026-11-23 after setting the clock on 2026-11-19: 2026-11-19 takes
# two places (D_Y_2_4 and D_Y_2_5), so D_Y_2_5 and older are one day older than n
DEVICE_2026_11_23 = {
    "D_Y_2_1": "101",
    "D_Y_2_2": "102",
    "D_Y_2_3": "103",
    "D_Y_2_4": "12",
    "D_Y_2_5": "9",
    "D_Y_2_6": "105",
    "D_Y_2_7": "93",
    "D_Y_2_8": "33",
    "D_Y_2_9": "170",
    "D_Y_2_10": "127",
    "D_Y_2_11": "256",
    "D_Y_2_12": "64",
    "D_Y_2_13": "74",
    "D_Y_2_14": "93",
}
# data file after the migration (scripts/fix_date_offset.py)
MIGRATED_2026 = [
    ("2026-11-13", "256"),
    ("2026-11-14", "127"),
    ("2026-11-15", "170"),
    ("2026-11-16", "33"),
    ("2026-11-17", "93"),
    ("2026-11-18", "105"),
    ("2026-11-19", "21"),
]


def test_run_stores_today_minus_n_in_any_response_order(run, tmp_path, mails):
    response = dict(reversed(list(DEVICE_2026_11_23.items())))

    run(response)

    assert run.requests == [["D_C_4_2", *PARAMETERS]]
    stored = read_year(tmp_path, 2026)
    assert stored["2026-11-22"] == "101"
    assert stored["2026-11-09"] == "93"
    assert len(stored) == 14
    assert mails == [("data", tmp_path / "data")]


def test_run_with_first_date_keeps_the_migrated_values(run, tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="gruenbeck")
    write_year(tmp_path, 2026, MIGRATED_2026)

    run(DEVICE_2026_11_23, firstDate="2026-11-20")

    assert read_year(tmp_path, 2026) == {
        **dict(MIGRATED_2026),
        "2026-11-20": "103",
        "2026-11-21": "102",
        "2026-11-22": "101",
    }
    assert "[*] 11 values before dataFile.firstDate 2026-11-20 are not written" in (caplog.text)


def test_run_over_the_year_change_writes_both_files(run, tmp_path):
    response = {name: str(n) for n, name in enumerate(PARAMETERS, start=1)}

    run(response, today=day("2026-01-03"))

    assert read_year(tmp_path, 2026) == {"2026-01-02": "1", "2026-01-01": "2"}
    stored_2025 = read_year(tmp_path, 2025)
    assert stored_2025["2025-12-31"] == "3"
    assert stored_2025["2025-12-20"] == "14"
    assert len(stored_2025) == 12


def test_run_with_unknown_parameter_fails_without_writing(run, tmp_path, mails):
    response = {**DEVICE_2026_11_23, "D_Y_1": "101"}

    with pytest.raises(SystemExit) as exit_info:
        run(response)

    assert exit_info.value.code == 1
    assert not list((tmp_path / "data").glob("*.csv"))
    assert mails == [
        (
            "error",
            "[-] unknown consumption parameter 'D_Y_1':"
            " expected D_Y_2_<n> (consumption of n days ago)",
        )
    ]


def test_run_with_invalid_first_date_fails_before_asking_the_device(run, mails):
    with pytest.raises(SystemExit) as exit_info:
        run(DEVICE_2026_11_23, firstDate="2026-11-31")

    assert exit_info.value.code == 1
    assert run.requests == []
    assert mails[0][0] == "error"
    assert "dataFile.firstDate '2026-11-31'" in mails[0][1]


# --- device clock: only a warning (P004-S8, S9, S10) --------------------------------


def clock_warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]


@pytest.mark.parametrize(
    "local_time, device_clock",
    [
        ("16:00", "16:00"),  # weekly run, Monday 16:00
        ("00:10", "00:10"),  # the clock does not tell whether the device rolled over
        ("16:00", "15:45"),  # deviation within the tolerance of 15 minutes
        ("16:00", "16:15"),
    ],
)
def test_device_clock_within_tolerance_gives_no_warning(
    run, tmp_path, caplog, local_time, device_clock
):
    run(DEVICE_2026_11_23, local_time=local_time, device_clock=device_clock)

    assert read_year(tmp_path, 2026)["2026-11-22"] == "101"
    assert clock_warnings(caplog) == []


@pytest.mark.parametrize(
    "local_time, device_clock, deviation",
    [
        ("16:00", "15:44", "-0:16"),
        ("16:00", "17:00", "+1:00"),  # no switch to daylight saving time
        ("16:00", "06:15", "-9:45"),  # the device clock before 2026-11-19
        ("06:00", "17:00", "+11:00"),  # 13 h late, looks 11 h early
        ("00:40", "23:40", "-1:00"),
    ],
)
def test_device_clock_off_is_only_a_warning(
    run, tmp_path, caplog, local_time, device_clock, deviation
):
    run(DEVICE_2026_11_23, local_time=local_time, device_clock=device_clock)

    assert read_year(tmp_path, 2026)["2026-11-22"] == "101"
    assert clock_warnings(caplog) == [
        f"[-] the device clock is off (device clock {device_clock}, local time"
        f" {local_time}, deviation {deviation}): set the device clock"
    ]


@pytest.mark.parametrize(
    "device_clock, warning",
    [
        (None, "[-] the device response has no device clock D_C_4_2"),
        ("24:00", "[-] invalid device clock D_C_4_2 '24:00' (expected HH:MM)"),
        ("7:05", "[-] invalid device clock D_C_4_2 '7:05' (expected HH:MM)"),
        ("-", "[-] invalid device clock D_C_4_2 '-' (expected HH:MM)"),
        ("", "[-] invalid device clock D_C_4_2 '' (expected HH:MM)"),
    ],
)
def test_missing_or_invalid_device_clock_is_only_a_warning(
    run, tmp_path, caplog, mails, device_clock, warning
):
    run(DEVICE_2026_11_23, device_clock=device_clock)

    assert read_year(tmp_path, 2026)["2026-11-22"] == "101"
    assert clock_warnings(caplog) == [warning]
    assert [kind for kind, _ in mails] == ["data"]


def test_run_maps_the_days_from_the_local_date_of_the_run(run, tmp_path):
    # 2026-11-24 16:30: yesterday is 2026-11-23
    run(DEVICE_2026_11_23, today=day("2026-11-24"), local_time="16:30", device_clock="16:30")

    stored = read_year(tmp_path, 2026)
    assert stored["2026-11-23"] == "101"
    assert "2026-11-24" not in stored


@pytest.mark.parametrize(
    "device_clock, local_time, deviation",
    [
        ("10:00", "10:00", 0),
        ("01:00", "02:00", -60),
        ("02:15", "12:00", -585),
        ("23:59", "12:00", 719),
        ("12:00", "00:00", 720),  # upper end of (-12 h, +12 h]
        ("00:30", "23:50", 40),
    ],
)
def test_deviation_is_device_minus_local_time_within_half_a_day(
    device_clock, local_time, deviation
):
    now = datetime.datetime.combine(TODAY, datetime.time.fromisoformat(local_time))

    assert device.check_device_clock(device_clock, now) == deviation


# --- comparison with the stored values (P004-S10) -----------------------------------


def memory(value_of, today=TODAY, shift=0):
    """
    device memory D_Y_2_1 ... 14 for `today` from the true values of the days
    :param value_of: function(datetime.date) -> consumption of that day
    :param shift: 1 = the run is before the daily rollover (values one day older)
    """
    return {
        f"D_Y_2_{n}": str(value_of(today - datetime.timedelta(days=n + shift)))
        for n in range(1, 15)
    }


def true_value(day_):
    """consumption of a day, different for every day"""
    return 50 + day_.toordinal() % 97


def stored_rows(first, last):
    rows, current = [], first
    while current <= last:
        rows.append((current.isoformat(), str(true_value(current))))
        current += datetime.timedelta(days=1)
    return rows


def test_overlap_with_the_same_values_is_written(run, tmp_path, mails):
    # the run a week ago stored 2026-11-02 ... 2026-11-15
    write_year(tmp_path, 2026, stored_rows(day("2026-11-02"), day("2026-11-15")))

    run(memory(true_value))

    stored = read_year(tmp_path, 2026)
    assert stored["2026-11-22"] == str(true_value(day("2026-11-22")))
    assert len(stored) == 21
    assert [kind for kind, _ in mails] == ["data"]


def test_run_before_the_rollover_is_one_day_late_and_writes_nothing(run, tmp_path, mails):
    write_year(tmp_path, 2026, stored_rows(day("2026-11-02"), day("2026-11-15")))
    before = (tmp_path / "data" / f"{PREFIX}_2026.csv").read_bytes()

    with pytest.raises(SystemExit) as exit_info:
        run(memory(true_value, shift=1), local_time="06:00", device_clock="06:00")

    assert exit_info.value.code == 1
    assert (tmp_path / "data" / f"{PREFIX}_2026.csv").read_bytes() == before
    assert mails == [
        (
            "error",
            "[-] one day late: the run was probably before the daily rollover of"
            " the device; run again later (the new values of 2026-11-09 ..."
            " 2026-11-15 equal the stored values of the day before; nothing"
            " written)",
        )
    ]


def test_run_before_the_rollover_over_the_year_change_writes_no_file(run, tmp_path, mails):
    write_year(tmp_path, 2025, stored_rows(day("2025-12-20"), day("2025-12-31")))
    write_year(tmp_path, 2026, stored_rows(day("2026-01-01"), day("2026-01-03")))
    files = sorted((tmp_path / "data").glob("*.csv"))
    before = [path.read_bytes() for path in files]

    with pytest.raises(SystemExit):
        run(
            memory(true_value, today=day("2026-01-11"), shift=1),
            today=day("2026-01-11"),
            local_time="07:00",
            device_clock="07:00",
        )

    assert [path.read_bytes() for path in files] == before
    assert mails[0][1].startswith("[-] one day late:")


def test_overlap_with_other_values_writes_nothing_and_names_the_days(run, tmp_path, mails):
    rows = stored_rows(day("2026-11-02"), day("2026-11-15"))
    rows[-1] = ("2026-11-15", "999")
    rows[-3] = ("2026-11-13", "0")
    write_year(tmp_path, 2026, rows)
    new_13 = true_value(day("2026-11-13"))
    new_15 = true_value(day("2026-11-15"))

    with pytest.raises(SystemExit):
        run(memory(true_value))

    assert mails == [
        (
            "error",
            f"[-] the new values differ from the stored ones (2026-11-13: stored"
            f" 0, new {new_13}, 2026-11-15: stored 999, new {new_15}): nothing"
            " written; check the data files and the device",
        )
    ]


def test_overlap_over_the_year_change_is_checked_and_written(run, tmp_path):
    write_year(tmp_path, 2025, stored_rows(day("2025-12-25"), day("2025-12-31")))
    write_year(tmp_path, 2026, stored_rows(day("2026-01-01"), day("2026-01-02")))

    run(memory(true_value, today=day("2026-01-08")), today=day("2026-01-08"))

    assert read_year(tmp_path, 2026)["2026-01-07"] == str(true_value(day("2026-01-07")))
    assert read_year(tmp_path, 2025)["2025-12-25"] == str(true_value(day("2025-12-25")))


def test_values_before_first_date_are_not_compared(run, tmp_path, mails):
    # migrated values up to 2026-11-19; the device memory on 2026-11-23 maps other
    # values to these days (double place of 2026-11-19), but firstDate drops them
    write_year(tmp_path, 2026, MIGRATED_2026)

    run(DEVICE_2026_11_23, firstDate="2026-11-20")

    assert read_year(tmp_path, 2026)["2026-11-19"] == "21"
    assert [kind for kind, _ in mails] == ["data"]


@pytest.fixture
def logging_handlers():
    """removes and closes the handlers that setup_logging() adds"""
    added: list[logging.Handler] = []
    yield added
    for handler in added:
        cli.package_logger.removeHandler(handler)
        handler.close()


def test_log_file_takes_warnings_and_errors_but_no_infos(logging_handlers, tmp_path, capsys):
    log_file = tmp_path / "collector.log"
    logging_handlers += cli.setup_logging(False, log_file)

    cli.logger.info("[*] an info")
    cli.logger.warning("[-] the device clock is off")
    cli.logger.error("[-] an error")

    lines = log_file.read_text().splitlines()
    assert [line.split(" - ", 3)[2:] for line in lines] == [
        ["WARNING", "[-] the device clock is off"],
        ["ERROR", "[-] an error"],
    ]
    assert capsys.readouterr().err == ""


def test_console_logging_with_option_l_starts_at_info(logging_handlers, tmp_path, capsys):
    logging_handlers += cli.setup_logging(True, tmp_path / "collector.log")

    cli.logger.info("[*] an info")

    assert "INFO - [*] an info" in capsys.readouterr().err
    assert (tmp_path / "collector.log").read_text() == ""


# --- merging new and stored values (P006-S1) ----------------------------------------


def stored_lines(tmp_path, year):
    return (tmp_path / "data" / f"{PREFIX}_{year}.csv").read_text(encoding="utf-8").splitlines()


def test_run_keeps_the_other_stored_days_and_sorts_the_file(run, tmp_path, mails):
    write_year(
        tmp_path,
        2026,
        [("2026-12-24", "7"), ("2026-01-05", "5"), ("2026-11-01", "-"), ("2026-11-08", "x")],
    )

    run(memory(true_value))

    lines = stored_lines(tmp_path, 2026)
    assert lines[:4] == ["date,value", "2026-01-05,5", "2026-11-01,-", "2026-11-08,x"]
    assert lines[4:18] == [
        f"{day_.isoformat()},{true_value(day_)}"
        for day_ in (day("2026-11-09") + datetime.timedelta(days=n) for n in range(14))
    ]
    assert lines[18:] == ["2026-12-24,7"]
    assert mails == [("data", tmp_path / "data")]


@pytest.mark.parametrize(
    "device_value, stored", [(" 93 ", "93"), ("007", "7"), ("+5", "5"), ("-5", "-5"), ("0", "0")]
)
def test_run_stores_the_device_values_as_int(run, tmp_path, device_value, stored):
    run({**DEVICE_2026_11_23, "D_Y_2_1": device_value})

    assert read_year(tmp_path, 2026)["2026-11-22"] == stored


@pytest.mark.parametrize(
    "device_value, error",
    [
        ("-", ValueError),
        ("", ValueError),
        ("1.5", ValueError),
        ("x", ValueError),
        (None, TypeError),
    ],
    ids=repr,
)
def test_run_with_a_value_that_is_no_int_fails_without_error_mail(
    run, tmp_path, mails, device_value, error
):
    # outside handle_error(): a traceback instead of an error mail (P006-S9 changes this)
    with pytest.raises(error):
        run({**DEVICE_2026_11_23, "D_Y_2_5": device_value})

    assert not list((tmp_path / "data").glob("*.csv"))
    assert mails == []


def test_run_over_the_year_change_adds_to_the_stored_file_and_starts_the_new_one(run, tmp_path):
    write_year(tmp_path, 2025, stored_rows(day("2025-12-01"), day("2025-12-19")))
    today = day("2026-01-03")

    run(memory(true_value, today=today), today=today)

    assert read_year(tmp_path, 2025) == dict(stored_rows(day("2025-12-01"), day("2025-12-31")))
    assert list(read_year(tmp_path, 2025)) == sorted(read_year(tmp_path, 2025))
    assert read_year(tmp_path, 2026) == dict(stored_rows(day("2026-01-01"), day("2026-01-02")))


def test_run_reads_the_file_of_the_last_year_without_writing_it(run, tmp_path, mails):
    # D_Y_2_14 on 2026-01-15 is 2026-01-01; 2025-12-31 is read for the overlap check
    write_year(tmp_path, 2025, stored_rows(day("2025-12-20"), day("2025-12-31")))
    file_2025 = tmp_path / "data" / f"{PREFIX}_2025.csv"
    before = (file_2025.read_bytes(), file_2025.stat().st_mtime_ns)
    today = day("2026-01-15")

    run(memory(true_value, today=today), today=today)

    assert (file_2025.read_bytes(), file_2025.stat().st_mtime_ns) == before
    assert read_year(tmp_path, 2026) == dict(stored_rows(day("2026-01-01"), day("2026-01-14")))
    assert [kind for kind, _ in mails] == ["data"]


def test_run_before_the_rollover_compares_with_the_last_day_of_the_last_year(run, tmp_path, mails):
    write_year(tmp_path, 2025, stored_rows(day("2025-12-31"), day("2025-12-31")))
    write_year(tmp_path, 2026, stored_rows(day("2026-01-01"), day("2026-01-01")))
    files = sorted((tmp_path / "data").glob("*.csv"))
    before = [path.read_bytes() for path in files]
    today = day("2026-01-15")

    with pytest.raises(SystemExit) as exit_info:
        run(memory(true_value, today=today, shift=1), today=today)

    assert exit_info.value.code == 1
    assert [path.read_bytes() for path in files] == before
    assert mails == [
        (
            "error",
            "[-] one day late: the run was probably before the daily rollover of"
            " the device; run again later (the new values of 2026-01-01 ..."
            " 2026-01-01 equal the stored values of the day before; nothing"
            " written)",
        )
    ]


def test_run_with_a_text_value_stored_for_a_new_day_writes_nothing(run, tmp_path, mails):
    rows = stored_rows(day("2026-11-02"), day("2026-11-15"))
    rows[-1] = ("2026-11-15", "-")
    write_year(tmp_path, 2026, rows)

    with pytest.raises(SystemExit):
        run(memory(true_value))

    assert mails == [
        (
            "error",
            "[-] the new values differ from the stored ones (2026-11-15: stored -,"
            f" new {true_value(day('2026-11-15'))}): nothing written; check the data"
            " files and the device",
        )
    ]


def test_run_with_another_date_pattern_writes_and_compares_in_that_format(run, tmp_path):
    today = day("2026-12-05")
    write_year(
        tmp_path,
        2026,
        [
            (current.strftime("%d.%m.%Y"), str(true_value(current)))
            for current in (day("2026-11-19"), day("2026-11-20"), day("2026-11-21"))
        ],
    )

    run(memory(true_value, today=today), today=today, datePattern="%d.%m.%Y")

    # sorted as text: December before the end of November
    assert list(read_year(tmp_path, 2026)) == [
        "01.12.2026",
        "02.12.2026",
        "03.12.2026",
        "04.12.2026",
        "19.11.2026",
        "20.11.2026",
        "21.11.2026",
        "22.11.2026",
        "23.11.2026",
        "24.11.2026",
        "25.11.2026",
        "26.11.2026",
        "27.11.2026",
        "28.11.2026",
        "29.11.2026",
        "30.11.2026",
    ]
    assert read_year(tmp_path, 2026)["04.12.2026"] == str(true_value(day("2026-12-04")))


def test_run_with_another_date_pattern_detects_differing_values(run, tmp_path, mails):
    today = day("2026-12-05")
    write_year(tmp_path, 2026, [("21.11.2026", "999")])

    with pytest.raises(SystemExit):
        run(memory(true_value, today=today), today=today, datePattern="%d.%m.%Y")

    assert mails[0][1].startswith(
        f"[-] the new values differ from the stored ones (2026-11-21: stored 999,"
        f" new {true_value(day('2026-11-21'))})"
    )
