"""
exit codes and error mails of the commands (P006-S4)

Only gruenbeck.cli catches the errors of the package: every failure of a run ends with
exit code 1, and with an error mail if the mail section of the configuration is valid.
"""

import collections.abc
import datetime
import logging
import os
import pathlib
import subprocess
import sys
import typing

import pytest
import requests

from gruenbeck import analysis, cli, collector, config, device, errors, mail, storage

MEMORY = [f"D_Y_2_{n}" for n in range(1, 15)]
TODAY = datetime.date(2026, 11, 23)


@pytest.fixture
def mails(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, typing.Any]]:
    """records data and error mails instead of sending them"""
    sent: list[tuple[str, typing.Any]] = []

    def record(
        settings: config.Mail,
        subject: str,
        text: str,
        attachments: collections.abc.Iterable[pathlib.Path] = (),
        html: str | None = None,
    ) -> None:
        if subject == cli.ERROR_MAIL_SUBJECT:
            sent.append((subject, text))
        else:
            # the data mail attaches the csv files of the data folder
            sent.append(("data", next(iter(attachments)).parent))

    monkeypatch.setattr(mail, "send_mail", record)
    return sent


@pytest.fixture
def answers(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> list[dict[str, str | None] | BaseException]:
    """
    fake device: answers the items of the list in turn (an exception is raised); without
    items it answers with D_C_4_2 = 16:00 and 1 litre per day
    """
    queue: list[dict[str, str | None] | BaseException] = []

    def fetch(
        host: str,
        parameters: collections.abc.Iterable[str],
        timeout: float,
        session: object = None,
    ) -> dict[str, str | None]:
        if queue:
            item = queue.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
        return {"D_C_4_2": "16:00", **{name: "1" for name in MEMORY}}

    monkeypatch.setattr(device, "get_data_from_mux_http", fetch)
    now = datetime.datetime.combine(TODAY, datetime.time(16, 0))
    monkeypatch.setattr(collector, "local_now", lambda: now)
    return queue


@pytest.fixture
def collect(
    tmp_path: pathlib.Path,
    write_config: collections.abc.Callable[..., pathlib.Path],
    config_data: dict[str, typing.Any],
    answers: list[dict[str, str | None] | BaseException],
    mails: list[tuple[str, typing.Any]],
) -> collections.abc.Iterator[collections.abc.Callable[..., int]]:
    """
    gruenbeck-collect with -c and -e in tmp_path; the handlers are removed afterwards
    :return: function(config=config_data) -> exit code
    """
    existing = list(cli.package_logger.handlers)

    def run(data: dict[str, typing.Any] | None = None) -> int:
        config_file = write_config(config_data if data is None else data)
        return cli.collect(["-c", str(config_file), "-e", str(tmp_path / "errors.log")])

    yield run
    for handler in [h for h in cli.package_logger.handlers if h not in existing]:
        cli.package_logger.removeHandler(handler)
        handler.close()


def error_mails(mails: list[tuple[str, typing.Any]]) -> list[typing.Any]:
    return [text for kind, text in mails if kind == cli.ERROR_MAIL_SUBJECT]


def test_successful_run_exits_with_0(
    collect: collections.abc.Callable[..., int],
    mails: list[tuple[str, typing.Any]],
    tmp_path: pathlib.Path,
) -> None:
    assert collect() == 0

    assert mails == [("data", tmp_path / "data")]


def test_missing_configuration_exits_with_1_without_mail(
    collect: collections.abc.Callable[..., int],
    mails: list[tuple[str, typing.Any]],
    tmp_path: pathlib.Path,
) -> None:
    assert cli.collect(["-c", str(tmp_path / "missing.json"), "-e", str(tmp_path / "e.log")]) == 1

    assert mails == []
    assert "no configuration: [Errno 2]" in (tmp_path / "e.log").read_text()


def test_invalid_configuration_exits_with_1_and_error_mail(
    collect: collections.abc.Callable[..., int],
    mails: list[tuple[str, typing.Any]],
    config_data: dict[str, typing.Any],
) -> None:
    del config_data["dataPath"]

    assert collect() == 1

    assert error_mails(mails) == ["no config parameter: 'dataPath'"]


def test_invalid_mail_section_exits_with_1_without_mail(
    collect: collections.abc.Callable[..., int],
    mails: list[tuple[str, typing.Any]],
    config_data: dict[str, typing.Any],
) -> None:
    del config_data["mail"]

    assert collect() == 1

    assert mails == []


def test_device_error_exits_with_1_and_error_mail(
    collect: collections.abc.Callable[..., int],
    mails: list[tuple[str, typing.Any]],
    answers: list[dict[str, str | None] | BaseException],
) -> None:
    # the session of the device query repeated the request already (tests/test_device_query.py)
    answers.append(requests.exceptions.ConnectTimeout("connect timed out"))

    assert collect() == 1

    assert error_mails(mails) == ["failed to get device data: connect timed out"]


def test_invalid_device_answer_exits_with_1_after_all_attempts(
    collect: collections.abc.Callable[..., int],
    mails: list[tuple[str, typing.Any]],
    answers: list[dict[str, str | None] | BaseException],
    sleeps: list[float],
) -> None:
    answers.extend([ValueError("device response contains no values")] * 6)

    assert collect() == 1

    # retries 5 by default: 6 attempts, 5 seconds apart
    assert error_mails(mails) == [
        "failed to get device data after 6 attempts: device response contains no values"
    ]
    assert sleeps == [5.0] * 5


def test_retries_of_the_configuration_are_used(
    collect: collections.abc.Callable[..., int],
    mails: list[tuple[str, typing.Any]],
    answers: list[dict[str, str | None] | BaseException],
    sleeps: list[float],
    config_data: dict[str, typing.Any],
) -> None:
    config_data["softWaterSystem"].update(retries=1, retryDelay=0.5)
    answers.extend([ValueError("bad answer")] * 2)

    assert collect() == 1

    assert error_mails(mails) == ["failed to get device data after 2 attempts: bad answer"]
    assert sleeps == [0.5]


def test_unknown_parameter_in_the_answer_exits_with_1_and_error_mail(
    collect: collections.abc.Callable[..., int],
    mails: list[tuple[str, typing.Any]],
    answers: list[dict[str, str | None] | BaseException],
) -> None:
    answers.append({"D_C_4_2": "16:00", **{name: "1" for name in MEMORY}, "D_Y_1": "5"})

    assert collect() == 1

    assert error_mails(mails) == [
        "unknown consumption parameter 'D_Y_1': expected D_Y_2_<n> (consumption of n days ago)"
    ]


def test_run_with_the_former_parameter_file_key_exits_with_0_and_warns(
    collect: collections.abc.Callable[..., int],
    mails: list[tuple[str, typing.Any]],
    config_data: dict[str, typing.Any],
    caplog: pytest.LogCaptureFixture,
    tmp_path: pathlib.Path,
) -> None:
    # configurations from before P009-S7 still have it: the file is not read any more,
    # so it does not matter that it is missing
    config_data["parameterFile"] = str(tmp_path / "missing.csv")

    assert collect() == 0

    assert mails == [("data", tmp_path / "data")]
    assert "unknown config parameter 'parameterFile' is ignored" in caplog.messages


def test_data_folder_that_cannot_be_created_exits_with_1_and_error_mail(
    collect: collections.abc.Callable[..., int],
    mails: list[tuple[str, typing.Any]],
    config_data: dict[str, typing.Any],
    tmp_path: pathlib.Path,
) -> None:
    config_data["dataPath"] = str(tmp_path / "missing" / "data")

    assert collect() == 1

    (text,) = error_mails(mails)
    assert text.startswith("creation data folder failed: [Errno 2] No such file or directory")


def test_invalid_data_file_exits_with_1_and_error_mail(
    collect: collections.abc.Callable[..., int],
    mails: list[tuple[str, typing.Any]],
    tmp_path: pathlib.Path,
) -> None:
    (tmp_path / "data").mkdir()
    path = tmp_path / "data" / "gruenbeck_water_consumption_2026.csv"
    path.write_text("day,litres\n2026-11-01,1\n")

    assert collect() == 1

    assert error_mails(mails) == [
        f"{path} has no column 'date', 'value' of dataFile.fieldnames (columns: day, litres):"
        " nothing written"
    ]
    assert path.read_text() == "day,litres\n2026-11-01,1\n"


def test_differing_stored_value_exits_with_1_and_error_mail(
    collect: collections.abc.Callable[..., int],
    mails: list[tuple[str, typing.Any]],
    tmp_path: pathlib.Path,
) -> None:
    (tmp_path / "data").mkdir()
    path = tmp_path / "data" / "gruenbeck_water_consumption_2026.csv"
    path.write_text("date,value\n2026-11-09,7\n")

    assert collect() == 1

    (text,) = error_mails(mails)
    assert text.startswith("the new values differ from the stored ones (2026-11-09: stored 7")


def test_unexpected_error_exits_with_1_and_error_mail_with_traceback(
    collect: collections.abc.Callable[..., int],
    mails: list[tuple[str, typing.Any]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    def disk_full(source: object, target: object) -> typing.NoReturn:
        raise OSError(28, "No space left on device")

    # storage uses os.replace: the module os is the same object
    monkeypatch.setattr(os, "replace", disk_full)

    assert collect() == 1

    (text,) = error_mails(mails)
    assert text.startswith("unexpected error: OSError: [Errno 28] No space left on device\n\n")
    assert "Traceback (most recent call last):" in text
    assert 'in disk_full\n    raise OSError(28, "No space left on device")' in text
    log = (tmp_path / "errors.log").read_text()
    assert "ERROR - unexpected error: OSError: [Errno 28] No space left on device\n" in log
    assert "Traceback (most recent call last):" in log


def test_failed_data_mail_exits_with_1_without_error_mail(
    collect: collections.abc.Callable[..., int],
    mails: list[tuple[str, typing.Any]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    def refused(
        settings: config.Mail,
        subject: str,
        text: str,
        attachments: collections.abc.Iterable[pathlib.Path] = (),
        html: str | None = None,
    ) -> typing.NoReturn:
        raise mail.MailError("Authentication failed: refused")

    monkeypatch.setattr(mail, "send_mail", refused)

    assert collect() == 1

    assert error_mails(mails) == []
    assert (tmp_path / "data" / "gruenbeck_water_consumption_2026.csv").exists()


def test_failed_error_mail_keeps_exit_code_1(
    collect: collections.abc.Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
    config_data: dict[str, typing.Any],
    tmp_path: pathlib.Path,
) -> None:
    def refused(
        settings: config.Mail,
        subject: str,
        text: str,
        attachments: collections.abc.Iterable[pathlib.Path] = (),
        html: str | None = None,
    ) -> typing.NoReturn:
        raise mail.MailError("Authentication failed: refused")

    monkeypatch.setattr(mail, "send_mail", refused)
    del config_data["dataPath"]

    assert collect() == 1

    assert "Failed to send error notification email: Authentication failed: refused" in (
        (tmp_path / "errors.log").read_text()
    )


def test_missing_log_folder_exits_with_1_without_mail(
    mails: list[tuple[str, typing.Any]],
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
    answers: list[dict[str, str | None] | BaseException],
) -> None:
    log_file = tmp_path / "missing" / "errors.log"

    assert cli.collect(["-c", str(tmp_path / "config.json"), "-e", str(log_file)]) == 1

    assert capsys.readouterr().err == (
        f"gruenbeck-collect: cannot open the log file: [Errno 2] No such file or directory:"
        f" '{log_file}'\n"
    )
    assert mails == []


def test_keyboard_interrupt_is_not_caught(
    collect: collections.abc.Callable[..., int],
    answers: list[dict[str, str | None] | BaseException],
) -> None:
    answers.append(KeyboardInterrupt())

    # BaseException, not an error of the run: no error mail, the interpreter stops
    with pytest.raises(KeyboardInterrupt):
        collect()


def test_errors_of_the_package_have_a_common_base_class() -> None:
    for error in (
        config.ConfigurationError,
        device.DeviceError,
        storage.StorageError,
        collector.CollectError,
        analysis.AnalysisError,
    ):
        assert issubclass(error, errors.GruenbeckError)
    # read_configuration_file() callers (gruenbeck.rollover) catch ValueError
    assert issubclass(config.ConfigurationError, ValueError)


# --- gruenbeck-analyse --------------------------------------------------------------


@pytest.mark.parametrize(
    "error, message",
    [
        (FileNotFoundError(2, "No such file or directory", "c.json"), "no configuration: "),
        (config.ConfigurationError(["no config parameter: 'dataPath'"]), ""),
        (analysis.AnalysisError("no data files 'p_<year>.csv' in /data"), ""),
    ],
    ids=lambda value: type(value).__name__ if isinstance(value, Exception) else repr(value),
)
def test_analyse_exits_with_1_and_the_message(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
    message: str,
) -> None:
    def fail(config_file: object) -> typing.NoReturn:
        raise error

    monkeypatch.setattr(analysis, "main", fail)

    assert cli.analyse(["-c", "c.json"]) == 1

    assert capsys.readouterr().err == f"gruenbeck-analyse: {message}{error}\n"


def test_analyse_exits_with_0(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analysis, "main", lambda config_file: None)

    assert cli.analyse([]) == 0


# --- logging ------------------------------------------------------------------------


def test_every_module_logs_with_its_own_name() -> None:
    assert cli.logger.name == "gruenbeck.cli"
    assert collector.logger.name == "gruenbeck.collector"
    assert config.logger.name == "gruenbeck.config"
    assert device.logger.name == "gruenbeck.device"
    assert mail.logger.name == "gruenbeck.mail"
    assert storage.logger.name == "gruenbeck.storage"
    assert cli.package_logger.name == "gruenbeck"


def test_importing_the_package_configures_no_logging() -> None:
    # a new interpreter: the tests of this process call setup_logging()
    code = (
        "import logging, gruenbeck.analysis, gruenbeck.cli, gruenbeck.collector, gruenbeck.config,"
        " gruenbeck.device, gruenbeck.mail, gruenbeck.storage;"
        " logger = logging.getLogger('gruenbeck');"
        " print(logger.level, logger.handlers, logging.getLogger().handlers)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=60
    )

    assert result.stdout == "0 [] []\n"


def test_setup_logging_configures_the_package_logger(tmp_path: pathlib.Path) -> None:
    cli.setup_logging(True, tmp_path / "errors.log")

    assert cli.package_logger.level == logging.INFO
    assert [type(h).__name__ for h in cli.package_logger.handlers] == [
        "StreamHandler",
        "RotatingFileHandler",
    ]
