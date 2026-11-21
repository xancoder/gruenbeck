"""
command line of the data collector: gruenbeck-collect, formerly src/data-collector.py

The characterization of P006-S1 holds for the command: same options and defaults.
"""

import datetime
import importlib.metadata
import pathlib
import re
import subprocess
import sys

import pytest

from gruenbeck import cli, device, mail

# the commands are installed next to the interpreter of the virtual environment (uv sync)
BIN = pathlib.Path(sys.executable).parent


def run_command(command, cwd, *args):
    path = BIN / command
    assert path.exists(), f"{path} is missing: install the package with uv sync"
    return subprocess.run(
        [str(path), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_commands_are_entry_points_of_the_cli_module():
    scripts = {
        entry.name: entry.value
        for entry in importlib.metadata.entry_points(group="console_scripts")
        if entry.name.startswith("gruenbeck-")
    }

    assert scripts == {
        "gruenbeck-collect": "gruenbeck.cli:collect",
        "gruenbeck-analyse": "gruenbeck.cli:analyse",
    }


def test_help_lists_the_options(tmp_path):
    result = run_command("gruenbeck-collect", tmp_path, "--help")

    assert result.returncode == 0
    assert result.stdout.startswith("usage: gruenbeck-collect ")
    # the layout of the help text differs between Python versions
    for long_option, short_option, text in (
        ("--config-file", "-c", "set config file"),
        ("--log-console", "-l", "activate console logging"),
        ("--log-error", "-e", "log warnings and errors to file"),
    ):
        assert re.search(rf"{long_option}\b.*, {short_option}\b", result.stdout), long_option
        assert text in result.stdout


def test_defaults_are_relative_to_the_working_directory(tmp_path):
    (tmp_path / "log").mkdir()

    result = run_command("gruenbeck-collect", tmp_path)

    assert result.returncode == 1
    log = (tmp_path / "log" / "gruenbeck_error.log").read_text()
    # default ./src/config.json, normalized by pathlib
    assert (
        "ERROR - no configuration: [Errno 2] No such file or directory: 'src/config.json'"
    ) in log
    # no console logging without -l
    assert result.stderr == ""


def test_missing_log_folder_fails_before_the_run(tmp_path):
    result = run_command("gruenbeck-collect", tmp_path)

    assert result.returncode == 1
    # up to P006-S4 a traceback
    assert result.stderr == (
        "gruenbeck-collect: cannot open the log file: [Errno 2] No such file or directory:"
        f" '{tmp_path / 'log' / 'gruenbeck_error.log'}'\n"
    )
    assert not (tmp_path / "log").exists()


@pytest.fixture
def package_logger():
    """the logger with the handlers of setup_logging(); added handlers are removed afterwards"""
    existing = list(cli.package_logger.handlers)
    yield cli.package_logger
    for handler in [h for h in cli.package_logger.handlers if h not in existing]:
        cli.package_logger.removeHandler(handler)
        handler.close()


def test_run_with_options(tmp_path, monkeypatch, capsys, package_logger, config_data, write_config):
    now = datetime.datetime.now()
    config_data["dataFile"]["prefix"] = "p"
    config_file = write_config(config_data)
    log_file = tmp_path / "errors.log"
    sent = []

    def fetch(host, parameters, timeout):
        return {"D_C_4_2": f"{now:%H:%M}", **{name: "1" for name in parameters[1:]}}

    monkeypatch.setattr(device, "get_data_from_mux_http", fetch)
    monkeypatch.setattr(mail, "send_mail", lambda param, folder: sent.append(folder))

    cli.collect(["-c", str(config_file), "-e", str(log_file), "-l"])

    assert sent == [tmp_path / "data"]
    assert len(list((tmp_path / "data").glob("p_*.csv"))) in (1, 2)  # 2 at the year change
    # -l: INFO and above on the console (stderr), also from other modules of the package
    err = capsys.readouterr().err
    assert "gruenbeck.cli - INFO - Data collection completed" in err
    assert "gruenbeck.storage - INFO - data to write:" in err
    assert log_file.read_text() == ""
