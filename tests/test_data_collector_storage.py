"""
characterization of the yearly data files of src/data-collector.py (P006-S1):
get_data_file, read_data_file and write_data
"""

import logging
import os
import pathlib
import stat

import pytest

FIELDNAMES = {"date": "date", "value": "value"}


# --- path of the yearly file --------------------------------------------------------


def test_data_file_is_prefix_and_year_in_the_data_folder(data_collector, tmp_path):
    config = {"dataFile": {"prefix": "gruenbeck_water_consumption"}}

    path = data_collector.get_data_file(config, tmp_path / "data", 2026)

    assert path == tmp_path / "data" / "gruenbeck_water_consumption_2026.csv"
    assert isinstance(path, pathlib.Path)


def test_data_file_of_a_relative_data_folder_stays_relative(data_collector):
    config = {"dataFile": {"prefix": "p"}}

    assert data_collector.get_data_file(config, "./data", 2025) == pathlib.Path("data/p_2025.csv")
    assert data_collector.get_data_file(config, pathlib.Path("data"), "2025") == pathlib.Path(
        "data/p_2025.csv"
    )


def test_data_file_without_prefix_raises_key_error(data_collector, tmp_path):
    # not caught by handle_error(): a traceback, no error mail
    with pytest.raises(KeyError):
        data_collector.get_data_file({"dataFile": {}}, tmp_path, 2026)


# --- reading a yearly file ----------------------------------------------------------


def test_missing_file_has_no_values(data_collector, tmp_path):
    assert data_collector.read_data_file(tmp_path / "missing.csv", FIELDNAMES) == {}


def test_numeric_values_become_int_others_stay_text(data_collector, tmp_path):
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

    assert data_collector.read_data_file(path, FIELDNAMES) == {
        "2026-11-20": 103,
        "2026-11-21": 7,
        "2026-11-22": "-",
        "2026-11-23": "",
        "2026-11-24": "-5",
        "2026-11-25": "1.5",
        "2026-11-26": " 9",
    }


def test_dates_are_kept_as_text(data_collector, tmp_path):
    path = tmp_path / "p_2026.csv"
    path.write_text("date,value\n22.11.2026,101\nnot a date,1\n", encoding="utf-8")

    assert data_collector.read_data_file(path, FIELDNAMES) == {"22.11.2026": 101, "not a date": 1}


def test_columns_are_read_by_the_configured_fieldnames(data_collector, tmp_path):
    path = tmp_path / "p_2026.csv"
    path.write_text("litres,note,day\n101,x,2026-11-22\n", encoding="utf-8")

    result = data_collector.read_data_file(path, {"date": "day", "value": "litres"})

    assert result == {"2026-11-22": 101}


def test_missing_column_raises_key_error(data_collector, tmp_path):
    path = tmp_path / "p_2026.csv"
    path.write_text("date,value\n2026-11-22,101\n", encoding="utf-8")

    with pytest.raises(KeyError):
        data_collector.read_data_file(path, {"date": "day", "value": "litres"})


def test_repeated_date_keeps_the_last_value(data_collector, tmp_path):
    path = tmp_path / "p_2026.csv"
    path.write_text("date,value\n2026-11-22,1\n2026-11-21,5\n2026-11-22,2\n", encoding="utf-8")

    assert data_collector.read_data_file(path, FIELDNAMES) == {"2026-11-22": 2, "2026-11-21": 5}


def test_file_with_header_only_has_no_values(data_collector, tmp_path):
    path = tmp_path / "p_2026.csv"
    path.write_text("date,value\n", encoding="utf-8")

    assert data_collector.read_data_file(path, FIELDNAMES) == {}


# --- writing a yearly file ----------------------------------------------------------


def test_write_data_writes_header_and_rows_sorted_by_date_text(data_collector, tmp_path):
    path = tmp_path / "p_2026.csv"

    data_collector.write_data(
        path, FIELDNAMES, {"2026-11-22": 101, "2026-11-20": "103", "2026-11-21": 102}
    )

    # csv module default: \r\n line endings
    assert path.read_bytes() == (
        b"date,value\r\n2026-11-20,103\r\n2026-11-21,102\r\n2026-11-22,101\r\n"
    )
    assert list(tmp_path.iterdir()) == [path]


def test_write_data_sorts_the_text_not_the_date(data_collector, tmp_path):
    path = tmp_path / "p_2026.csv"

    data_collector.write_data(path, FIELDNAMES, {"30.11.2026": 1, "01.12.2026": 2, "29.11.2026": 3})

    assert path.read_text(encoding="utf-8").splitlines() == [
        "date,value",
        "01.12.2026,2",
        "29.11.2026,3",
        "30.11.2026,1",
    ]


def test_write_data_replaces_the_whole_file(data_collector, tmp_path):
    path = tmp_path / "p_2026.csv"
    path.write_text("date,value\n2026-11-01,5\n2026-11-02,6\n", encoding="utf-8")

    data_collector.write_data(path, FIELDNAMES, {"2026-11-03": 7})

    assert path.read_text(encoding="utf-8").splitlines() == ["date,value", "2026-11-03,7"]


def test_write_data_without_values_writes_the_header(data_collector, tmp_path):
    path = tmp_path / "p_2026.csv"

    data_collector.write_data(path, FIELDNAMES, {})

    assert path.read_bytes() == b"date,value\r\n"


def test_write_data_takes_the_values_as_text(data_collector, tmp_path):
    path = tmp_path / "p_2026.csv"

    data_collector.write_data(path, FIELDNAMES, {"a": "-", "b": None, "c": 1.5, "d": "x,y"})

    assert path.read_text(encoding="utf-8").splitlines() == [
        "date,value",
        "a,-",
        "b,",
        "c,1.5",
        'd,"x,y"',
    ]


def test_write_data_logs_the_data(data_collector, tmp_path, caplog):
    caplog.set_level(logging.INFO, logger=data_collector.logger.name)

    data_collector.write_data(tmp_path / "p_2026.csv", FIELDNAMES, {"2026-11-22": 101})

    assert caplog.messages == ["[*] data to write: {'2026-11-22': 101}"]


def test_write_data_keeps_the_mode_of_an_existing_file(data_collector, tmp_path):
    path = tmp_path / "p_2026.csv"
    path.write_text("date,value\n", encoding="utf-8")
    path.chmod(0o640)

    data_collector.write_data(path, FIELDNAMES, {"2026-11-22": 101})

    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert path.read_text(encoding="utf-8").splitlines()[1] == "2026-11-22,101"


def test_write_data_syncs_the_temporary_file_before_replacing(
    data_collector, tmp_path, monkeypatch
):
    path = tmp_path / "p_2026.csv"
    path.write_text("date,value\nold,1\n", encoding="utf-8")
    steps: list[object] = []
    fsync, replace = os.fsync, os.replace

    def record_fsync(fd):
        steps.append("fsync")
        fsync(fd)

    def record_replace(source, target):
        steps.append(("replace", pathlib.Path(source).name, pathlib.Path(target).name))
        assert path.read_text(encoding="utf-8") == "date,value\nold,1\n"
        replace(source, target)

    monkeypatch.setattr(data_collector.os, "fsync", record_fsync)
    monkeypatch.setattr(data_collector.os, "replace", record_replace)

    data_collector.write_data(path, FIELDNAMES, {"new": 2})

    assert steps == ["fsync", ("replace", ".p_2026.csv.tmp", "p_2026.csv")]
    assert path.read_text(encoding="utf-8").splitlines() == ["date,value", "new,2"]


def test_failed_replace_keeps_the_old_file_and_removes_the_temporary_one(
    data_collector, tmp_path, monkeypatch
):
    path = tmp_path / "p_2026.csv"
    path.write_text("date,value\nold,1\n", encoding="utf-8")

    def fail(source, target):
        raise OSError("disk full")

    monkeypatch.setattr(data_collector.os, "replace", fail)

    with pytest.raises(OSError, match="disk full"):
        data_collector.write_data(path, FIELDNAMES, {"new": 2})

    assert path.read_text(encoding="utf-8") == "date,value\nold,1\n"
    assert list(tmp_path.iterdir()) == [path]


def test_other_fieldnames_fail_without_changing_the_file(data_collector, tmp_path):
    """
    csv.DictWriter takes the keys of the fieldnames (date, value) as columns, but the
    rows use the configured names: other names than date/value fail (P006-S3 fixes this)
    """
    path = tmp_path / "p_2026.csv"
    path.write_text("day,litres\nold,1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="dict contains fields not in fieldnames"):
        data_collector.write_data(path, {"date": "day", "value": "litres"}, {"new": 2})

    assert path.read_text(encoding="utf-8") == "day,litres\nold,1\n"
    assert list(tmp_path.iterdir()) == [path]


def test_write_data_in_a_missing_folder_fails(data_collector, tmp_path):
    with pytest.raises(FileNotFoundError):
        data_collector.write_data(tmp_path / "missing" / "p_2026.csv", FIELDNAMES, {"a": 1})


def test_written_file_is_read_back(data_collector, tmp_path):
    path = tmp_path / "p_2026.csv"
    data = {"2026-11-21": 102, "2026-11-22": 101, "2026-11-23": "-"}

    data_collector.write_data(path, FIELDNAMES, data)

    assert data_collector.read_data_file(path, FIELDNAMES) == data
