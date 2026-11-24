"""
command line of the data collector: gruenbeck-collect, formerly src/data-collector.py

The characterization of P006-S1 holds for the command: same options and defaults.
"""

import collections.abc
import datetime
import importlib.metadata
import logging
import os
import pathlib
import re
import subprocess
import sys
import typing

import pytest

from gruenbeck import analysis, cli, device, mail, preview, rollover

# the commands are installed next to the interpreter of the virtual environment (uv sync)
BIN = pathlib.Path(sys.executable).parent


def run_command(command: str, cwd: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
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


def test_commands_are_entry_points_of_the_package() -> None:
    scripts = {
        entry.name: entry.value
        for entry in importlib.metadata.entry_points(group="console_scripts")
        if entry.name.startswith("gruenbeck-")
    }

    assert scripts == {
        "gruenbeck-collect": "gruenbeck.cli:collect",
        "gruenbeck-analyse": "gruenbeck.cli:analyse",
        "gruenbeck-preview-mail": "gruenbeck.preview:main",
        "gruenbeck-log-rollover": "gruenbeck.rollover:main",
    }


@pytest.mark.parametrize(
    ("command", "options"),
    [
        ("gruenbeck-preview-mail", ("--config-file", "--today", "--output-dir", "--send-to")),
        ("gruenbeck-log-rollover", ("--config-file", "--interval", "--hours", "--output")),
    ],
)
def test_tools_list_their_options(
    command: str, options: tuple[str, ...], tmp_path: pathlib.Path
) -> None:
    result = run_command(command, tmp_path, "--help")

    assert result.returncode == 0
    assert result.stdout.startswith(f"usage: {command} ")
    for option in options:
        assert option in result.stdout


def test_help_lists_the_options(tmp_path: pathlib.Path) -> None:
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


def test_defaults_are_relative_to_the_working_directory(tmp_path: pathlib.Path) -> None:
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


def test_missing_log_folder_fails_before_the_run(tmp_path: pathlib.Path) -> None:
    result = run_command("gruenbeck-collect", tmp_path)

    assert result.returncode == 1
    # up to P006-S4 a traceback
    assert result.stderr == (
        "gruenbeck-collect: cannot open the log file: [Errno 2] No such file or directory:"
        f" '{tmp_path / 'log' / 'gruenbeck_error.log'}'\n"
    )
    assert not (tmp_path / "log").exists()


@pytest.fixture
def package_logger() -> collections.abc.Iterator[logging.Logger]:
    """the logger with the handlers of setup_logging(); added handlers are removed afterwards"""
    existing = list(cli.package_logger.handlers)
    yield cli.package_logger
    for handler in [h for h in cli.package_logger.handlers if h not in existing]:
        cli.package_logger.removeHandler(handler)
        handler.close()


def test_run_with_options(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    package_logger: logging.Logger,
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
) -> None:
    now = datetime.datetime.now()
    config_data["dataFile"]["prefix"] = "p"
    config_file = write_config(config_data)
    log_file = tmp_path / "errors.log"
    sent: list[pathlib.Path] = []

    def fetch(
        host: str, parameters: list[str], timeout: float, session: object = None
    ) -> dict[str, str | None]:
        return {"D_C_4_2": f"{now:%H:%M}", **{name: "1" for name in parameters[1:]}}

    monkeypatch.setattr(device, "get_data_from_mux_http", fetch)
    monkeypatch.setattr(
        mail,
        "send_mail",
        lambda settings, subject, text, attachments=(), html=None: sent.extend(attachments),
    )

    cli.collect(["-c", str(config_file), "-e", str(log_file), "-l"])

    files = sorted((tmp_path / "data").glob("p_*.csv"))
    assert len(files) in (1, 2)  # 2 at the year change
    # the data mail attaches the yearly files
    assert sent == files
    # -l: INFO and above on the console (stderr), also from other modules of the package
    err = capsys.readouterr().err
    assert "gruenbeck.cli - INFO - Data collection completed" in err
    assert "gruenbeck.storage - INFO - data to write:" in err
    assert log_file.read_text() == ""


@pytest.mark.parametrize(
    "command",
    ["gruenbeck-collect", "gruenbeck-analyse", "gruenbeck-preview-mail", "gruenbeck-log-rollover"],
)
def test_help_names_the_variable_and_the_default_of_the_config_file(
    command: str, tmp_path: pathlib.Path
) -> None:
    result = run_command(command, tmp_path, "--help")

    assert result.returncode == 0
    assert "set config file" in result.stdout
    assert "GRUENBECK_CONFIG" in result.stdout
    assert "./src/config.json" in result.stdout


def test_collect_uses_the_variable_as_config_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files: list[str] = []

    def main(config_file: str) -> int:
        files.append(config_file)
        return 0

    monkeypatch.setattr(cli, "main", main)
    monkeypatch.setattr(cli, "setup_logging", lambda *args, **kwargs: [])
    monkeypatch.setenv("GRUENBECK_CONFIG", "/etc/gruenbeck/config.json")

    assert cli.collect([]) == 0
    assert cli.collect(["-c", "other.json"]) == 0

    assert files == ["/etc/gruenbeck/config.json", "other.json"]


def test_analyse_uses_the_variable_as_config_file(monkeypatch: pytest.MonkeyPatch) -> None:
    files: list[str] = []
    monkeypatch.setattr(analysis, "main", files.append)
    monkeypatch.setenv("GRUENBECK_CONFIG", "/etc/gruenbeck/config.json")

    assert cli.analyse([]) == 0

    assert files == ["/etc/gruenbeck/config.json"]


def test_preview_and_rollover_use_the_variable_as_config_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GRUENBECK_CONFIG", "/etc/gruenbeck/config.json")

    assert preview.parse_args([]).config_file == "/etc/gruenbeck/config.json"
    assert rollover.parse_args([]).config_file == "/etc/gruenbeck/config.json"
    assert preview.parse_args(["-c", "x.json"]).config_file == "x.json"
    assert rollover.parse_args(["-c", "x.json"]).config_file == "x.json"


def test_run_without_the_option_reads_the_file_of_the_variable(
    tmp_path: pathlib.Path,
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
) -> None:
    """a real process: the variable replaces ./src/config.json, there is none in tmp_path"""
    (tmp_path / "log").mkdir()
    config_file = write_config(config_data, tmp_path / "elsewhere" / "config.json")
    del config_data["mail"]
    write_config(config_data, tmp_path / "other" / "config.json")

    result = subprocess.run(
        [str(BIN / "gruenbeck-collect"), "-l"],
        cwd=tmp_path,
        env={**os.environ, "GRUENBECK_CONFIG": str(tmp_path / "other" / "config.json")},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    # the configuration of the variable is read (and found invalid: no mail section)
    assert result.returncode == 1
    assert "no config parameter: 'mail'" in result.stderr
    assert str(config_file) not in result.stderr
