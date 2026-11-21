"""
yearly data files (characterization of P006-S1): get_data_file, read_data_file and
write_data; since P006-S3 with the column names and the date pattern of dataFile
"""

import logging
import os
import pathlib
import stat

import pytest

from gruenbeck import config, storage

FIELDNAMES = config.FieldNames(date="date", value="value")
ISO = "%Y-%m-%d"


# --- path of the yearly file --------------------------------------------------------


def test_data_file_is_prefix_and_year_in_the_data_folder(tmp_path):
    path = storage.get_data_file(tmp_path / "data", "gruenbeck_water_consumption", 2026)

    assert path == tmp_path / "data" / "gruenbeck_water_consumption_2026.csv"
    assert isinstance(path, pathlib.Path)


def test_data_file_of_a_relative_data_folder_stays_relative():
    # the configuration makes dataPath absolute (P006-S3)
    assert storage.get_data_file("./data", "p", 2025) == pathlib.Path("data/p_2025.csv")
    assert storage.get_data_file(pathlib.Path("data"), "p", "2025") == pathlib.Path(
        "data/p_2025.csv"
    )


# --- reading a yearly file ----------------------------------------------------------


def test_missing_file_has_no_values(tmp_path):
    assert storage.read_data_file(tmp_path / "missing.csv", FIELDNAMES, ISO) == {}


def test_numeric_values_become_int_others_stay_text(tmp_path):
    path = tmp_path / "p_2026.csv"
    path.write_text(
        "date,value\n"
        "2026-11-20,103\n"
        "2026-11-21,007\n"
        "2026-11-22,-\n"
        "2026-11-23,\n"
        "2026-11-24,-5\n"
        "2026-11-25,1.5\n"
        "2026-11-26, 9\n",
        encoding="utf-8",
    )

    assert storage.read_data_file(path, FIELDNAMES, ISO) == {
        "2026-11-20": 103,
        "2026-11-21": 7,
        "2026-11-22": "-",
        "2026-11-23": "",
        "2026-11-24": "-5",
        "2026-11-25": "1.5",
        "2026-11-26": " 9",
    }


def test_dates_are_kept_as_text(tmp_path):
    path = tmp_path / "p_2026.csv"
    path.write_text("date,value\n22.11.2026,101\n01.12.2026,7\n", encoding="utf-8")

    result = storage.read_data_file(path, FIELDNAMES, "%d.%m.%Y")

    assert result == {"22.11.2026": 101, "01.12.2026": 7}


@pytest.mark.parametrize("text", ["not a date", "", "2026-11-31", "2026-1-5", "22.11.2026"])
def test_date_that_does_not_match_the_pattern_is_an_error(tmp_path, text):
    path = tmp_path / "p_2026.csv"
    path.write_text(f"date,value\n2026-11-20,1\n{text},2\n", encoding="utf-8")

    with pytest.raises(storage.DataFileError) as err:
        storage.read_data_file(path, FIELDNAMES, ISO)

    assert str(err.value) == (
        f"{path}, line 3: the date {text!r} does not match dataFile.datePattern '%Y-%m-%d'"
    )


def test_short_row_without_date_is_an_error(tmp_path):
    path = tmp_path / "p_2026.csv"
    path.write_text("value,date\n5\n", encoding="utf-8")

    with pytest.raises(storage.DataFileError, match="line 2: the date None does not match"):
        storage.read_data_file(path, FIELDNAMES, ISO)


def test_columns_are_read_by_the_configured_fieldnames(tmp_path):
    path = tmp_path / "p_2026.csv"
    path.write_text("litres,note,day\n101,x,2026-11-22\n", encoding="utf-8")

    result = storage.read_data_file(path, config.FieldNames(date="day", value="litres"), ISO)

    assert result == {"2026-11-22": 101}


def test_missing_column_is_an_error(tmp_path):
    path = tmp_path / "p_2026.csv"
    path.write_text("date,litres\n2026-11-22,101\n", encoding="utf-8")

    with pytest.raises(storage.DataFileError) as err:
        storage.read_data_file(path, config.FieldNames(date="day", value="litres"), ISO)

    assert str(err.value) == (
        f"{path} has no column 'day' of dataFile.fieldnames (columns: date, litres)"
    )


def test_empty_file_has_no_values(tmp_path):
    path = tmp_path / "p_2026.csv"
    path.write_text("", encoding="utf-8")

    assert storage.read_data_file(path, FIELDNAMES, ISO) == {}


def test_repeated_date_keeps_the_last_value(tmp_path):
    path = tmp_path / "p_2026.csv"
    path.write_text("date,value\n2026-11-22,1\n2026-11-21,5\n2026-11-22,2\n", encoding="utf-8")

    assert storage.read_data_file(path, FIELDNAMES, ISO) == {"2026-11-22": 2, "2026-11-21": 5}


def test_file_with_header_only_has_no_values(tmp_path):
    path = tmp_path / "p_2026.csv"
    path.write_text("date,value\n", encoding="utf-8")

    assert storage.read_data_file(path, FIELDNAMES, ISO) == {}


# --- writing a yearly file ----------------------------------------------------------


def test_write_data_writes_header_and_rows_sorted_by_date_text(tmp_path):
    path = tmp_path / "p_2026.csv"

    storage.write_data(
        path, FIELDNAMES, {"2026-11-22": 101, "2026-11-20": "103", "2026-11-21": 102}, ISO
    )

    # csv module default: \r\n line endings
    assert path.read_bytes() == (
        b"date,value\r\n2026-11-20,103\r\n2026-11-21,102\r\n2026-11-22,101\r\n"
    )
    assert list(tmp_path.iterdir()) == [path]


def test_write_data_sorts_by_the_date(tmp_path):
    path = tmp_path / "p_2026.csv"
    data = {"30.11.2026": 1, "01.12.2026": 2, "29.11.2026": 3}

    storage.write_data(path, FIELDNAMES, data, "%d.%m.%Y")

    # up to P006-S3 sorted as text: 01.12.2026 first
    assert path.read_text(encoding="utf-8").splitlines() == [
        "date,value",
        "29.11.2026,3",
        "30.11.2026,1",
        "01.12.2026,2",
    ]


def test_write_data_replaces_the_whole_file(tmp_path):
    path = tmp_path / "p_2026.csv"
    path.write_text("date,value\n2026-11-01,5\n2026-11-02,6\n", encoding="utf-8")

    storage.write_data(path, FIELDNAMES, {"2026-11-03": 7}, ISO)

    assert path.read_text(encoding="utf-8").splitlines() == ["date,value", "2026-11-03,7"]


def test_write_data_without_values_writes_the_header(tmp_path):
    path = tmp_path / "p_2026.csv"

    storage.write_data(path, FIELDNAMES, {}, ISO)

    assert path.read_bytes() == b"date,value\r\n"


def test_write_data_takes_the_values_as_text(tmp_path):
    path = tmp_path / "p_2026.csv"

    data = {"2026-11-01": "-", "2026-11-02": None, "2026-11-03": 1.5, "2026-11-04": "x,y"}

    storage.write_data(path, FIELDNAMES, data, ISO)

    assert path.read_text(encoding="utf-8").splitlines() == [
        "date,value",
        "2026-11-01,-",
        "2026-11-02,",
        "2026-11-03,1.5",
        '2026-11-04,"x,y"',
    ]


def test_write_data_logs_the_data(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger=storage.logger.name)

    storage.write_data(tmp_path / "p_2026.csv", FIELDNAMES, {"2026-11-22": 101}, ISO)

    assert caplog.messages == ["[*] data to write: {'2026-11-22': 101}"]


def test_write_data_keeps_the_mode_of_an_existing_file(tmp_path):
    path = tmp_path / "p_2026.csv"
    path.write_text("date,value\n", encoding="utf-8")
    path.chmod(0o640)

    storage.write_data(path, FIELDNAMES, {"2026-11-22": 101}, ISO)

    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert path.read_text(encoding="utf-8").splitlines()[1] == "2026-11-22,101"


def test_write_data_syncs_the_temporary_file_before_replacing(tmp_path, monkeypatch):
    path = tmp_path / "p_2026.csv"
    path.write_text("date,value\n2026-11-01,1\n", encoding="utf-8")
    steps: list[object] = []
    fsync, replace = os.fsync, os.replace

    def record_fsync(fd):
        steps.append("fsync")
        fsync(fd)

    def record_replace(source, target):
        steps.append(("replace", pathlib.Path(source).name, pathlib.Path(target).name))
        assert path.read_text(encoding="utf-8") == "date,value\n2026-11-01,1\n"
        replace(source, target)

    monkeypatch.setattr(storage.os, "fsync", record_fsync)
    monkeypatch.setattr(storage.os, "replace", record_replace)

    storage.write_data(path, FIELDNAMES, {"2026-11-02": 2}, ISO)

    assert steps == ["fsync", ("replace", ".p_2026.csv.tmp", "p_2026.csv")]
    assert path.read_text(encoding="utf-8").splitlines() == ["date,value", "2026-11-02,2"]


def test_failed_replace_keeps_the_old_file_and_removes_the_temporary_one(tmp_path, monkeypatch):
    path = tmp_path / "p_2026.csv"
    path.write_text("date,value\n2026-11-01,1\n", encoding="utf-8")

    def fail(source, target):
        raise OSError("disk full")

    monkeypatch.setattr(storage.os, "replace", fail)

    with pytest.raises(OSError, match="disk full"):
        storage.write_data(path, FIELDNAMES, {"2026-11-02": 2}, ISO)

    assert path.read_text(encoding="utf-8") == "date,value\n2026-11-01,1\n"
    assert list(tmp_path.iterdir()) == [path]


def test_other_fieldnames_are_the_columns(tmp_path):
    """up to P006-S3 csv.DictWriter took the keys date/value as columns and failed"""
    path = tmp_path / "p_2026.csv"
    path.write_text("day,litres\n2026-11-01,1\n", encoding="utf-8")
    fieldnames = config.FieldNames(date="day", value="litres")

    storage.write_data(path, fieldnames, {"2026-11-01": 1, "2026-11-02": 2}, ISO)

    assert path.read_bytes() == b"day,litres\r\n2026-11-01,1\r\n2026-11-02,2\r\n"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("text", ["2026-11-31", "02.11.2026", "new"])
def test_write_data_with_a_date_that_does_not_match_writes_nothing(tmp_path, text):
    path = tmp_path / "p_2026.csv"
    path.write_text("date,value\n2026-11-01,1\n", encoding="utf-8")

    with pytest.raises(storage.DataFileError) as err:
        storage.write_data(path, FIELDNAMES, {"2026-11-01": 1, text: 2}, ISO)

    assert str(err.value) == f"the date {text!r} does not match dataFile.datePattern '%Y-%m-%d'"
    assert path.read_text(encoding="utf-8") == "date,value\n2026-11-01,1\n"
    assert list(tmp_path.iterdir()) == [path]


def test_write_data_in_a_missing_folder_fails(tmp_path):
    with pytest.raises(FileNotFoundError):
        storage.write_data(tmp_path / "missing" / "p_2026.csv", FIELDNAMES, {"2026-11-01": 1}, ISO)


@pytest.mark.parametrize(
    "fieldnames, date_pattern, data",
    [
        (FIELDNAMES, ISO, {"2026-11-21": 102, "2026-11-22": 101, "2026-11-23": "-"}),
        (config.FieldNames("day", "litres"), "%d.%m.%Y", {"30.11.2026": 1, "01.12.2026": 2}),
    ],
)
def test_written_file_is_read_back(tmp_path, fieldnames, date_pattern, data):
    path = tmp_path / "p_2026.csv"

    storage.write_data(path, fieldnames, data, date_pattern)

    assert storage.read_data_file(path, fieldnames, date_pattern) == data
