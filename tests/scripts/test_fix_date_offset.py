import ast
import csv
import datetime
import importlib.util
import json
import os
import pathlib
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "fix_date_offset.py"

spec = importlib.util.spec_from_file_location("fix_date_offset", SCRIPT)
fix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fix)

PREFIX = "gruenbeck_water_consumption"
CET = datetime.timezone(datetime.timedelta(hours=1))
NOW = datetime.datetime(2026, 11, 20, 10, 15, 0, tzinfo=CET)
STAMP = "20261120T101500"

# the last run of the old data collector (2026-11-16) and the missing days
STORED_2026 = [("2026-11-14", "256"), ("2026-11-15", "127"), ("2026-11-16", "170")]
SET_GAP = ["--set", "2026-11-16=33", "--set", "2026-11-17=93",
           "--set", "2026-11-18=105", "--set", "2026-11-19=21"]


def write_config(tmp_path, data_path=None, name="config.json", **data_file):
    config = {
        "dataPath": str(data_path or tmp_path / "data"),
        "dataFile": {
            "datePattern": "%Y-%m-%d",
            "fieldnames": {"date": "date", "value": "value"},
            "prefix": PREFIX,
            **data_file,
        },
    }
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config))
    return path


def data_file(tmp_path, year):
    return tmp_path / "data" / f"{PREFIX}_{year}.csv"


def write_year(tmp_path, year, rows, header=("date", "value")):
    """yearly file as the data collector writes it (csv module, CRLF)"""
    path = data_file(tmp_path, year)
    path.parent.mkdir(exist_ok=True)
    with path.open(mode="w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def read_year(tmp_path, year):
    with data_file(tmp_path, year).open(newline="", encoding="utf-8") as csv_file:
        rows = list(csv.reader(csv_file))
    assert rows[0] == ["date", "value"]
    return [tuple(row) for row in rows[1:]]


def snapshot(tmp_path):
    """every file in the data folder with its content"""
    folder = tmp_path / "data"
    return {path.name: path.read_bytes() for path in sorted(folder.iterdir())}


def migrate(tmp_path, *args, config=None):
    config = config or write_config(tmp_path)
    return fix.main(["-c", str(config), *args], now=lambda: NOW)


def marker(tmp_path):
    return json.loads((tmp_path / "data" / fix.MARKER_NAME).read_text())


def test_script_is_executable():
    assert os.access(SCRIPT, os.X_OK)


def test_script_is_valid_python_3_11():
    # the Raspberry Pi has Python 3.11 outside the uv environment
    ast.parse(SCRIPT.read_text(encoding="utf-8"), feature_version=(3, 11))


def test_runs_with_the_standard_library_only(tmp_path):
    write_year(tmp_path, 2026, STORED_2026)
    config = write_config(tmp_path)

    # -S: no site-packages, so third-party packages like requests are missing
    result = subprocess.run(
        [sys.executable, "-S", str(SCRIPT), "-c", str(config)],
        capture_output=True, text=True, cwd=tmp_path, check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "[*] dry run: nothing written" in result.stdout


def test_dry_run_lists_every_change_per_file_and_writes_nothing(tmp_path, capsys):
    write_year(tmp_path, 2026, STORED_2026)
    before = snapshot(tmp_path)

    assert migrate(tmp_path, *SET_GAP) == 0

    assert snapshot(tmp_path) == before
    out = capsys.readouterr().out.splitlines()
    assert f"[*] {PREFIX}_2026.csv: 3 values -> 7 values" in out
    lines = [line.split() for line in out if line.startswith("    ")]
    assert lines == [
        ["2026-11-13", "-", "->", "256", "from", "2026-11-14"],
        ["2026-11-14", "256", "->", "127", "from", "2026-11-15"],
        ["2026-11-15", "127", "->", "170", "from", "2026-11-16"],
        ["2026-11-16", "170", "->", "33", "--set"],
        ["2026-11-17", "-", "->", "93", "--set"],
        ["2026-11-18", "-", "->", "105", "--set"],
        ["2026-11-19", "-", "->", "21", "--set"],
    ]
    assert out[-1] == "[*] dry run: nothing written; add --apply to write the changes"


def test_apply_moves_every_value_one_day_back_and_adds_set_values(tmp_path, capsys):
    write_year(tmp_path, 2026, STORED_2026)

    assert migrate(tmp_path, *SET_GAP, "--apply") == 0

    assert read_year(tmp_path, 2026) == [
        ("2026-11-13", "256"),
        ("2026-11-14", "127"),
        ("2026-11-15", "170"),
        ("2026-11-16", "33"),
        ("2026-11-17", "93"),
        ("2026-11-18", "105"),
        ("2026-11-19", "21"),
    ]
    assert "[!]" not in capsys.readouterr().out


def test_values_are_moved_unchanged_also_non_numeric(tmp_path):
    write_year(tmp_path, 2026, [
        ("2026-03-01", "n/a"), ("2026-03-02", ""), ("2026-03-03", "007"),
        ("2026-03-04", "1,5"), ("2026-03-05", "64"),
    ])

    assert migrate(tmp_path, "--apply") == 0

    assert read_year(tmp_path, 2026) == [
        ("2026-02-28", "n/a"), ("2026-03-01", ""), ("2026-03-02", "007"),
        ("2026-03-03", "1,5"), ("2026-03-04", "64"),
    ]


def test_value_of_first_january_moves_into_new_previous_year_file(tmp_path, capsys):
    write_year(tmp_path, 2026, [("2026-01-01", "54"), ("2026-01-02", "60")])

    assert migrate(tmp_path, "--apply") == 0

    assert read_year(tmp_path, 2025) == [("2025-12-31", "54")]
    assert read_year(tmp_path, 2026) == [("2026-01-01", "60")]
    out = capsys.readouterr().out
    assert f"[*] {PREFIX}_2025.csv: new file, 1 value" in out
    assert f"[*] {PREFIX}_2026.csv: 2 values -> 1 value" in out
    # nothing to back up for the new file
    assert f"{PREFIX}_2025.csv.{STAMP}.bak" not in snapshot(tmp_path)


def test_value_of_first_january_joins_existing_previous_year_file(tmp_path):
    write_year(tmp_path, 2025, [("2025-12-30", "40"), ("2025-12-31", "41")])
    write_year(tmp_path, 2026, [("2026-01-01", "54"), ("2026-01-02", "60")])

    assert migrate(tmp_path, "--apply") == 0

    assert read_year(tmp_path, 2025) == [
        ("2025-12-29", "40"), ("2025-12-30", "41"), ("2025-12-31", "54"),
    ]
    assert read_year(tmp_path, 2026) == [("2026-01-01", "60")]


def test_set_with_gap_is_reported(tmp_path, capsys):
    write_year(tmp_path, 2026, STORED_2026)

    assert migrate(tmp_path, "--set", "2026-11-16=33", "--set", "2026-11-19=21") == 0

    out = capsys.readouterr().out.splitlines()
    assert "[!] no value for 2026-11-17 ... 2026-11-18 (2 days)" in out


def test_days_up_to_the_clock_change_without_value_are_reported(tmp_path, capsys):
    write_year(tmp_path, 2026, STORED_2026)

    assert migrate(tmp_path, "--set", "2026-11-16=33", "--set", "2026-11-17=93") == 0

    out = capsys.readouterr().out.splitlines()
    assert [line for line in out if line.startswith("[!]")] == [
        "[!] no value for 2026-11-18 ... 2026-11-19 (2 days)"
    ]


def test_without_set_the_days_after_the_last_run_are_reported(tmp_path, capsys):
    write_year(tmp_path, 2026, STORED_2026)

    assert migrate(tmp_path, "--apply") == 0

    assert read_year(tmp_path, 2026)[-1] == ("2026-11-15", "170")
    out = capsys.readouterr().out.splitlines()
    assert "[!] no value for 2026-11-16 ... 2026-11-19 (4 days)" in out


def test_set_conflicting_with_a_moved_value_aborts_without_changes(tmp_path, capsys):
    write_year(tmp_path, 2026, STORED_2026)
    before = snapshot(tmp_path)

    assert migrate(tmp_path, "--set", "2026-11-15=99", "--apply") == 1

    assert snapshot(tmp_path) == before
    err = capsys.readouterr().err
    assert (
        "conflict with a moved value: --set 2026-11-15=99,"
        " but 2026-11-15 has 170 (from 2026-11-16)"
    ) in err
    assert "[-] nothing changed" in err


def test_set_equal_to_the_moved_value_is_accepted(tmp_path, capsys):
    write_year(tmp_path, 2026, STORED_2026)

    assert migrate(tmp_path, "--set", "2026-11-15=170", "--apply") == 0

    assert read_year(tmp_path, 2026)[-1] == ("2026-11-15", "170")
    assert "from 2026-11-16 (= --set)" in capsys.readouterr().out


@pytest.mark.parametrize(
    "youngest", ["2026-11-19", "2026-11-23", "2027-01-04"]
)
def test_aborts_if_the_old_collector_wrote_after_the_clock_change(
    tmp_path, capsys, youngest
):
    write_year(tmp_path, 2026, STORED_2026)
    if youngest.startswith("2026"):
        write_year(tmp_path, 2026, [*STORED_2026, (youngest, "88")])
    else:
        write_year(tmp_path, 2027, [(youngest, "88")])
    before = snapshot(tmp_path)

    assert migrate(tmp_path, *SET_GAP, "--apply") == 1

    assert snapshot(tmp_path) == before
    err = capsys.readouterr().err
    assert f"the youngest stored date is {youngest}, on or after 2026-11-19" in err


def test_second_apply_is_refused(tmp_path, capsys):
    write_year(tmp_path, 2026, STORED_2026)
    assert migrate(tmp_path, "--set", "2026-11-16=33", "--apply") == 0
    after_first = snapshot(tmp_path)
    capsys.readouterr()

    assert migrate(tmp_path, "--set", "2026-11-16=33", "--apply") == 1
    # a dry run would show a second move, so it is refused as well
    assert migrate(tmp_path) == 1

    assert snapshot(tmp_path) == after_first
    err = capsys.readouterr().err
    assert "the migration was already applied and must run only once" in err
    assert f"(status done, started {NOW.isoformat()})" in err


def test_apply_backs_up_every_changed_file_with_timestamp(tmp_path, capsys):
    path_2025 = write_year(tmp_path, 2025, [("2025-12-31", "41")])
    path_2026 = write_year(tmp_path, 2026, [("2026-01-01", "54"), *STORED_2026])
    originals = {path.name: path.read_bytes() for path in (path_2025, path_2026)}

    assert migrate(tmp_path, "--apply") == 0

    files = snapshot(tmp_path)
    for name, content in originals.items():
        assert files[f"{name}.{STAMP}.bak"] == content
    # backups are not attached to the data mail (*.csv) or read by the analysis
    assert sorted(name for name in files if name.endswith(".csv")) == [
        f"{PREFIX}_2025.csv", f"{PREFIX}_2026.csv",
    ]
    assert f"[*] backup {PREFIX}_2026.csv.{STAMP}.bak" in capsys.readouterr().out


def test_marker_records_date_and_parameters_of_the_run(tmp_path):
    write_year(tmp_path, 2026, STORED_2026)
    config = write_config(tmp_path)

    assert migrate(tmp_path, *SET_GAP, "--apply", config=config) == 0

    assert marker(tmp_path) == {
        "script": "fix_date_offset.py",
        "status": "done",
        "started": "2026-11-20T10:15:00+01:00",
        "finished": "2026-11-20T10:15:00+01:00",
        "clockChangeDate": "2026-11-19",
        "shiftDays": -1,
        "configFile": str(config),
        "dataPath": str(tmp_path / "data"),
        "set": {
            "2026-11-16": "33", "2026-11-17": "93",
            "2026-11-18": "105", "2026-11-19": "21",
        },
        "files": [f"{PREFIX}_2026.csv"],
        "backups": [f"{PREFIX}_2026.csv.{STAMP}.bak"],
    }


def test_failed_apply_leaves_a_marker_that_blocks_another_run(
    tmp_path, capsys, monkeypatch
):
    write_year(tmp_path, 2025, [("2025-12-31", "41")])
    path_2026 = write_year(tmp_path, 2026, [("2026-01-01", "54"), *STORED_2026])
    original_2026 = path_2026.read_bytes()
    replace = os.replace
    calls = []

    def fail_on_second_data_file(src, dst):
        # 1: marker (in progress), 2: file 2025, 3: file 2026
        calls.append(dst)
        if len(calls) == 3:
            raise OSError("No space left on device")
        replace(src, dst)

    monkeypatch.setattr(fix.os, "replace", fail_on_second_data_file)

    assert migrate(tmp_path, "--apply") == 1

    monkeypatch.undo()
    assert marker(tmp_path)["status"] == "in progress"
    assert marker(tmp_path)["backups"] == [
        f"{PREFIX}_2025.csv.{STAMP}.bak", f"{PREFIX}_2026.csv.{STAMP}.bak",
    ]
    assert read_year(tmp_path, 2025) == [("2025-12-30", "41"), ("2025-12-31", "54")]
    assert path_2026.read_bytes() == original_2026
    err = capsys.readouterr().err
    assert "[-] No space left on device" in err
    assert "[-] the migration is incomplete: restore the backups" in err
    # no temporary file is left behind
    assert not [name for name in snapshot(tmp_path) if name.endswith(".tmp")]

    assert migrate(tmp_path, "--apply") == 1
    assert "an earlier --apply did not finish" in capsys.readouterr().err


def test_existing_backup_aborts_before_anything_is_written(tmp_path, capsys):
    path = write_year(tmp_path, 2026, STORED_2026)
    path.with_name(f"{path.name}.{STAMP}.bak").write_text("older backup")
    before = snapshot(tmp_path)

    assert migrate(tmp_path, "--apply") == 1

    assert snapshot(tmp_path) == before
    err = capsys.readouterr().err
    assert "already exists" in err
    assert "[-] no data file changed" in err


def test_apply_keeps_the_file_mode(tmp_path):
    path = write_year(tmp_path, 2026, STORED_2026)
    path.chmod(0o640)

    assert migrate(tmp_path, "--apply") == 0

    assert path.stat().st_mode & 0o777 == 0o640


def test_written_file_matches_the_data_collector(tmp_path, data_collector):
    write_year(tmp_path, 2026, STORED_2026)
    assert migrate(tmp_path, "--set", "2026-11-16=33", "--apply") == 0

    expected = tmp_path / "collector.csv"
    data_collector.write_data(
        expected,
        {"date": "date", "value": "value"},
        {"2026-11-13": 256, "2026-11-14": 127, "2026-11-15": 170, "2026-11-16": 33},
    )
    assert data_file(tmp_path, 2026).read_bytes() == expected.read_bytes()


@pytest.mark.parametrize(
    "argument",
    [
        "2026-11-16",
        "2026-11-16=",
        "2026-11-16=9+12",
        "2026-11-16=-3",
        "2026-11-16=1.5",
        "16.11.2026=33",
        "2026-02-30=33",
    ],
)
def test_invalid_set_argument_is_rejected(tmp_path, capsys, argument):
    write_year(tmp_path, 2026, STORED_2026)

    with pytest.raises(SystemExit) as exit_info:
        migrate(tmp_path, "--set", argument)

    assert exit_info.value.code == 2
    assert "--set" in capsys.readouterr().err


def test_set_value_is_stored_as_whole_number(tmp_path):
    write_year(tmp_path, 2026, STORED_2026)

    assert migrate(tmp_path, "--set", " 2026-11-16=033 ", "--apply") == 0

    assert read_year(tmp_path, 2026)[-1] == ("2026-11-16", "33")


@pytest.mark.parametrize(
    "arguments, message",
    [
        (["--set", "2026-11-17=1", "--set", "2026-11-17=2"],
         "--set 2026-11-17 is given twice"),
        (["--set", "2026-11-20=5"],
         "--set 2026-11-20 is after 2026-11-19: from 2026-11-20 on the data collector"),
    ],
)
def test_invalid_set_dates_abort_without_changes(tmp_path, capsys, arguments, message):
    write_year(tmp_path, 2026, STORED_2026)
    before = snapshot(tmp_path)

    assert migrate(tmp_path, *arguments, "--apply") == 1

    assert snapshot(tmp_path) == before
    assert message in capsys.readouterr().err


@pytest.mark.parametrize(
    "rows, header, message",
    [
        (STORED_2026, ("day", "litres"), "header day,litres instead of date,value"),
        ([("2026-11-14", "256", "x")], ("date", "value"), "line 2: 3 columns instead of 2"),
        ([("14.11.2026", "256")], ("date", "value"),
         "line 2: date '14.11.2026' does not match the date pattern '%Y-%m-%d'"),
        ([("2026-11-5", "256")], ("date", "value"),
         "line 2: date '2026-11-5' does not match the date pattern"),
        ([("2025-12-31", "256")], ("date", "value"),
         "line 2: 2025-12-31 does not belong to 2026"),
        ([("2026-11-14", "256"), ("2026-11-14", "1")], ("date", "value"),
         "line 3: 2026-11-14 appears twice"),
    ],
)
def test_unexpected_data_file_aborts_without_changes(
    tmp_path, capsys, rows, header, message
):
    write_year(tmp_path, 2026, rows, header=header)
    before = snapshot(tmp_path)

    assert migrate(tmp_path, "--apply") == 1

    assert snapshot(tmp_path) == before
    err = capsys.readouterr().err
    assert f"{PREFIX}_2026.csv" in err
    assert message in err


def test_only_yearly_files_with_the_configured_prefix_are_migrated(tmp_path):
    write_year(tmp_path, 2026, STORED_2026)
    other = tmp_path / "data" / "other_2026.csv"
    other.write_bytes(b"date,value\r\n2026-11-16,1\r\n")
    copy = tmp_path / "data" / f"{PREFIX}_2026_copy.csv"
    copy.write_text("unrelated")

    assert migrate(tmp_path, "--apply") == 0

    assert other.read_bytes() == b"date,value\r\n2026-11-16,1\r\n"
    assert copy.read_text() == "unrelated"


def test_columns_and_prefix_come_from_the_configuration(tmp_path):
    config = write_config(
        tmp_path, prefix="water", datePattern="%d.%m.%Y",
        fieldnames={"date": "day", "value": "litres"},
    )
    path = tmp_path / "data" / "water_2026.csv"
    path.parent.mkdir()
    path.write_bytes(b"day,litres\r\n01.01.2026,54\r\n16.11.2026,170\r\n")

    assert migrate(tmp_path, "--set", "2026-11-16=33", "--apply", config=config) == 0

    assert path.read_bytes() == b"day,litres\r\n15.11.2026,170\r\n16.11.2026,33\r\n"
    assert (tmp_path / "data" / "water_2025.csv").read_bytes() == (
        b"day,litres\r\n31.12.2025,54\r\n"
    )


def test_default_config_and_relative_data_path_from_the_current_directory(
    tmp_path, monkeypatch
):
    write_year(tmp_path, 2026, STORED_2026)
    write_config(tmp_path, data_path="./data", name="src/config.json")
    monkeypatch.chdir(tmp_path)

    assert fix.main(["--set", "2026-11-16=33", "--apply"], now=lambda: NOW) == 0

    assert read_year(tmp_path, 2026)[-1] == ("2026-11-16", "33")


@pytest.mark.parametrize(
    "setup, message",
    [
        ("no folder", "data folder"),
        ("empty folder", f"no data files {PREFIX}_<year>.csv in"),
        ("header only", "the data files contain no values"),
    ],
)
def test_missing_data_aborts(tmp_path, capsys, setup, message):
    if setup == "empty folder":
        (tmp_path / "data").mkdir()
    elif setup == "header only":
        write_year(tmp_path, 2026, [])

    assert migrate(tmp_path, "--apply") == 1

    assert message in capsys.readouterr().err


def test_configuration_errors(tmp_path, capsys):
    assert fix.main(["-c", str(tmp_path / "missing.json")]) == 1
    assert "[-] no configuration" in capsys.readouterr().err

    config = tmp_path / "config.json"
    config.write_text(json.dumps({"dataPath": "./data"}))
    assert fix.main(["-c", str(config)]) == 1
    assert "[-] no config parameter: 'dataFile'" in capsys.readouterr().err

    config.write_text("{not json")
    assert fix.main(["-c", str(config)]) == 1
    assert "[-] invalid configuration" in capsys.readouterr().err
