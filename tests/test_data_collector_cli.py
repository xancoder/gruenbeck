"""
characterization of the command line of src/data-collector.py (P006-S1)

P006-S2 replaces the script by the command gruenbeck-collect with the same options.
"""

import datetime
import json
import logging
import re
import runpy
import subprocess
import sys

import pytest

import datacollector
import gruenbeck

SCRIPT = "src/data-collector.py"


def run_script(repo_root, cwd, *args):
    return subprocess.run(
        [sys.executable, str(repo_root / SCRIPT), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_help_lists_the_options(repo_root, tmp_path):
    result = run_script(repo_root, tmp_path, "--help")

    assert result.returncode == 0
    # the layout of the help text differs between Python versions
    for long_option, short_option, text in (
        ("--config-file", "-c", "set config file"),
        ("--log-console", "-l", "activate console logging"),
        ("--log-error", "-e", "log warnings and errors to file"),
    ):
        assert re.search(rf"{long_option}\b.*, {short_option}\b", result.stdout), long_option
        assert text in result.stdout


def test_defaults_are_relative_to_the_working_directory(repo_root, tmp_path):
    (tmp_path / "log").mkdir()

    result = run_script(repo_root, tmp_path)

    assert result.returncode == 1
    log = (tmp_path / "log" / "gruenbeck_error.log").read_text()
    # default ./src/config.json, normalized by pathlib
    assert (
        "ERROR - [-] no configuration: [Errno 2] No such file or directory: 'src/config.json'"
    ) in log
    # no console logging without -l
    assert result.stderr == ""


def test_missing_log_folder_fails_before_the_run(repo_root, tmp_path):
    result = run_script(repo_root, tmp_path)

    assert result.returncode == 1
    assert "FileNotFoundError" in result.stderr
    assert not (tmp_path / "log").exists()


@pytest.fixture
def main_logger():
    """the logger of the script run as __main__; its handlers are removed afterwards"""
    logger = logging.getLogger("__main__")
    existing = list(logger.handlers)
    yield logger
    for handler in [handler for handler in logger.handlers if handler not in existing]:
        logger.removeHandler(handler)
        handler.close()


def test_run_with_options(repo_root, tmp_path, monkeypatch, capsys, main_logger, parameter_file):
    now = datetime.datetime.now()
    config = {
        "dataFile": {
            "datePattern": "%Y-%m-%d",
            "fieldnames": {"date": "date", "value": "value"},
            "prefix": "p",
        },
        "dataPath": str(tmp_path / "data"),
        "mail": {},
        "parameterFile": str(parameter_file),
        "softWaterSystem": {"host": "device.lan"},
    }
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config))
    log_file = tmp_path / "errors.log"
    sent = []

    def fetch(host, parameters, timeout):
        return {"D_C_4_2": f"{now:%H:%M}", **{name: "1" for name in parameters[1:]}}

    monkeypatch.setattr(gruenbeck, "get_data_from_mux_http", fetch)
    monkeypatch.setattr(datacollector, "send_mail", lambda param, folder: sent.append(folder))
    monkeypatch.setattr(sys, "argv", [SCRIPT, "-c", str(config_file), "-e", str(log_file), "-l"])

    runpy.run_path(str(repo_root / SCRIPT), run_name="__main__")

    assert sent == [tmp_path / "data"]
    assert len(list((tmp_path / "data").glob("p_*.csv"))) in (1, 2)  # 2 at the year change
    # -l: INFO and above on the console (stderr), plain messages without format
    assert "[*] Data collection completed" in capsys.readouterr().err
    assert log_file.read_text() == ""
