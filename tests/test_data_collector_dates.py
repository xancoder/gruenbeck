import csv
import datetime
import json
import logging

import pytest

PREFIX = "gruenbeck_water_consumption"
TODAY = datetime.date(2026, 11, 23)
PARAMETERS = [f"D_Y_2_{n}" for n in range(1, 15)]


def day(text):
    return datetime.date.fromisoformat(text)


@pytest.fixture
def mails(data_collector, monkeypatch):
    """records data and error mails instead of sending them"""
    sent = []
    monkeypatch.setattr(
        data_collector.datacollector, "send_mail",
        lambda param, data_folder: sent.append(("data", data_folder)),
    )
    monkeypatch.setattr(
        data_collector.datacollector, "send_mail_text",
        lambda param, subject, text: sent.append(("error", text)),
    )
    return sent


# --- mapping of the parameter name to the day ---------------------------------------


def test_parameter_name_gives_the_day(data_collector):
    response = {name: str(100 + n) for n, name in enumerate(PARAMETERS, start=1)}

    result = data_collector.add_timestamp_as_key_device_data(response, today=TODAY)

    assert result == {
        TODAY - datetime.timedelta(days=n): str(100 + n) for n in range(1, 15)
    }
    assert result[day("2026-11-22")] == "101"  # D_Y_2_1: yesterday
    assert result[day("2026-11-09")] == "114"  # D_Y_2_14: 14 days ago


def test_order_of_the_response_does_not_matter(data_collector):
    in_order = {name: str(n) for n, name in enumerate(PARAMETERS, start=1)}
    shuffled = {name: in_order[name] for name in [*PARAMETERS[7:], *PARAMETERS[:7]]}
    reversed_order = dict(reversed(list(in_order.items())))

    expected = data_collector.add_timestamp_as_key_device_data(in_order, today=TODAY)

    for response in (shuffled, reversed_order):
        assert (
            data_collector.add_timestamp_as_key_device_data(response, today=TODAY)
            == expected
        )


def test_days_are_calendar_dates_of_the_current_day(data_collector):
    before = datetime.date.today()
    result = data_collector.add_timestamp_as_key_device_data({"D_Y_2_1": "93"})
    after = datetime.date.today()

    (key,) = result
    assert type(key) is datetime.date
    assert key in {before - datetime.timedelta(days=1), after - datetime.timedelta(days=1)}


def test_year_change(data_collector):
    response = {"D_Y_2_1": "1", "D_Y_2_2": "2", "D_Y_2_3": "3", "D_Y_2_14": "14"}

    result = data_collector.add_timestamp_as_key_device_data(
        response, today=day("2026-01-02")
    )

    assert result == {
        day("2026-01-01"): "1",
        day("2025-12-31"): "2",
        day("2025-12-30"): "3",
        day("2025-12-19"): "14",
    }


def test_more_than_14_days_ago(data_collector):
    result = data_collector.add_timestamp_as_key_device_data(
        {"D_Y_2_27": "80"}, today=TODAY
    )

    assert result == {day("2026-10-27"): "80"}


@pytest.mark.parametrize(
    "name", ["D_Y_1", "D_Y_2_0", "D_Y_2_01", "D_Y_2_x", "D_Y_2_1x", "d_y_2_1", "code"]
)
def test_unknown_parameter_is_an_error(data_collector, name):
    response = {"D_Y_2_1": "93", name: "33"}

    with pytest.raises(ValueError) as err:
        data_collector.add_timestamp_as_key_device_data(response, today=TODAY)

    assert str(err.value) == (
        f"[-] unknown consumption parameter {name!r}:"
        " expected D_Y_2_<n> (consumption of n days ago)"
    )


# --- dataFile.firstDate ------------------------------------------------------------


def test_first_date_is_optional(data_collector):
    assert data_collector.get_first_date({"dataFile": {"prefix": PREFIX}}) is None


def test_first_date_without_data_file_section_is_an_error(
    data_collector, mails, caplog
):
    with pytest.raises(SystemExit) as exit_info:
        data_collector.get_first_date({"mail": {}})

    assert exit_info.value.code == 1
    assert "[-] no config parameter: 'dataFile'" in caplog.text
    assert mails == [("error", "[-] no config parameter: 'dataFile'")]


def test_first_date_is_read_as_date(data_collector):
    config = {"dataFile": {"firstDate": "2026-11-20"}}

    assert data_collector.get_first_date(config) == day("2026-11-20")


@pytest.mark.parametrize(
    "value",
    ["20.11.2026", "2026-11-31", "2026-1-5", "20261120", "2026-11-20T00:00", "",
     20261120, None],
    ids=repr,
)
def test_invalid_first_date_is_a_configuration_error(
    data_collector, mails, caplog, value
):
    config = {"dataFile": {"firstDate": value}, "mail": {}}

    with pytest.raises(SystemExit) as exit_info:
        data_collector.get_first_date(config)

    assert exit_info.value.code == 1
    message = f"[-] invalid config parameter dataFile.firstDate {value!r}"
    assert message in caplog.text
    assert mails[0][0] == "error"
    assert mails[0][1].startswith(message)


def test_first_date_filters_earlier_days(data_collector, caplog):
    caplog.set_level(logging.INFO, logger=data_collector.logger.name)
    device_data = {
        day("2026-11-22"): "101",
        day("2026-11-20"): "103",
        day("2026-11-19"): "12",
        day("2026-11-18"): "9",
    }

    result = data_collector.filter_first_date({}, device_data, day("2026-11-20"))

    assert result == {day("2026-11-22"): "101", day("2026-11-20"): "103"}
    assert "[*] 2 values before dataFile.firstDate 2026-11-20 are not written" in (
        caplog.text
    )


def test_without_first_date_nothing_is_filtered(data_collector, caplog):
    caplog.set_level(logging.INFO, logger=data_collector.logger.name)
    device_data = {day("2025-01-01"): "1", day("2026-11-22"): "101"}

    assert data_collector.filter_first_date({}, device_data, None) == device_data
    assert data_collector.filter_first_date(
        {}, device_data, day("2025-01-01")
    ) == device_data
    assert "firstDate" not in caplog.text


def test_all_values_before_first_date_fail_the_run(data_collector, mails, caplog):
    device_data = {day("2026-11-19"): "9", day("2026-11-18"): "105"}

    with pytest.raises(SystemExit) as exit_info:
        data_collector.filter_first_date({"mail": {}}, device_data, day("2026-11-20"))

    assert exit_info.value.code == 1
    assert (
        "[-] no data was processed: all 2 values are before dataFile.firstDate"
        " 2026-11-20"
    ) in caplog.text


# --- complete run ------------------------------------------------------------------


@pytest.fixture
def run(data_collector, mails, monkeypatch, tmp_path, parameter_file):
    """
    run main() on `today` with a fake device response
    :return: function(response, today, **data_file); its attribute `requests` lists
        the parameters of every device request
    """
    add_dates = data_collector.add_timestamp_as_key_device_data
    requests = []

    def run_main(response, today=TODAY, **data_file):
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
            return dict(response)

        monkeypatch.setattr(data_collector.gruenbeck, "get_data_from_mux_http", fetch)
        monkeypatch.setattr(
            data_collector, "add_timestamp_as_key_device_data",
            lambda device_data: add_dates(device_data, today=today),
        )
        data_collector.main(str(config_file))

    run_main.requests = requests
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
    "D_Y_2_1": "101", "D_Y_2_2": "102", "D_Y_2_3": "103", "D_Y_2_4": "12",
    "D_Y_2_5": "9", "D_Y_2_6": "105", "D_Y_2_7": "93", "D_Y_2_8": "33",
    "D_Y_2_9": "170", "D_Y_2_10": "127", "D_Y_2_11": "256", "D_Y_2_12": "64",
    "D_Y_2_13": "74", "D_Y_2_14": "93",
}
# data file after the migration (scripts/fix_date_offset.py)
MIGRATED_2026 = [
    ("2026-11-13", "256"), ("2026-11-14", "127"), ("2026-11-15", "170"),
    ("2026-11-16", "33"), ("2026-11-17", "93"), ("2026-11-18", "105"),
    ("2026-11-19", "21"),
]


def test_run_stores_today_minus_n_in_any_response_order(run, tmp_path, mails):
    response = dict(reversed(list(DEVICE_2026_11_23.items())))

    run(response)

    assert run.requests == [PARAMETERS]
    stored = read_year(tmp_path, 2026)
    assert stored["2026-11-22"] == "101"
    assert stored["2026-11-09"] == "93"
    assert len(stored) == 14
    assert mails == [("data", tmp_path / "data")]


def test_run_with_first_date_keeps_the_migrated_values(run, tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="data_collector")
    write_year(tmp_path, 2026, MIGRATED_2026)

    run(DEVICE_2026_11_23, firstDate="2026-11-20")

    assert read_year(tmp_path, 2026) == {
        **dict(MIGRATED_2026),
        "2026-11-20": "103",
        "2026-11-21": "102",
        "2026-11-22": "101",
    }
    assert "[*] 11 values before dataFile.firstDate 2026-11-20 are not written" in (
        caplog.text
    )


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
        ("error", "[-] unknown consumption parameter 'D_Y_1':"
                  " expected D_Y_2_<n> (consumption of n days ago)")
    ]


def test_run_with_invalid_first_date_fails_before_asking_the_device(run, mails):
    with pytest.raises(SystemExit) as exit_info:
        run(DEVICE_2026_11_23, firstDate="2026-11-31")

    assert exit_info.value.code == 1
    assert run.requests == []
    assert mails[0][0] == "error"
    assert "dataFile.firstDate '2026-11-31'" in mails[0][1]
