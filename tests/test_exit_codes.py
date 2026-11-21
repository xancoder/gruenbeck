"""
exit codes and error mails of the commands (P006-S4)

Only gruenbeck.cli catches the errors of the package: every failure of a run ends with
exit code 1, and with an error mail if the mail section of the configuration is valid.
"""

import datetime
import logging
import subprocess
import sys

import pytest
import requests

from gruenbeck import analysis, cli, config, device, errors, mail, storage

MEMORY = [f"D_Y_2_{n}" for n in range(1, 15)]
TODAY = datetime.date(2026, 11, 23)


@pytest.fixture
def mails(monkeypatch):
    """records data and error mails instead of sending them"""
    sent = []
    monkeypatch.setattr(mail, "send_mail", lambda param, folder: sent.append(("data", folder)))
    monkeypatch.setattr(
        mail, "send_mail_text", lambda param, subject, text: sent.append((subject, text))
    )
    return sent


@pytest.fixture
def answers(monkeypatch, sleeps):
    """
    fake device: answers the items of the list in turn (an exception is raised); without
    items it answers with D_C_4_2 = 16:00 and 1 litre per day
    """
    queue: list = []

    def fetch(host, parameters, timeout):
        if queue:
            item = queue.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
        return {"D_C_4_2": "16:00", **{name: "1" for name in MEMORY}}

    monkeypatch.setattr(device, "get_data_from_mux_http", fetch)
    now = datetime.datetime.combine(TODAY, datetime.time(16, 0))
    monkeypatch.setattr(cli, "local_now", lambda: now)
    return queue


@pytest.fixture
def collect(tmp_path, write_config, config_data, answers, mails):
    """
    gruenbeck-collect with -c and -e in tmp_path; the handlers are removed afterwards
    :return: function(config=config_data) -> exit code
    """
    existing = list(cli.package_logger.handlers)

    def run(data=None):
        config_file = write_config(config_data if data is None else data)
        return cli.collect(["-c", str(config_file), "-e", str(tmp_path / "errors.log")])

    yield run
    for handler in [h for h in cli.package_logger.handlers if h not in existing]:
        cli.package_logger.removeHandler(handler)
        handler.close()


def error_mails(mails):
    return [text for kind, text in mails if kind == cli.ERROR_MAIL_SUBJECT]


def test_successful_run_exits_with_0(collect, mails, tmp_path):
    assert collect() == 0

    assert mails == [("data", tmp_path / "data")]


def test_missing_configuration_exits_with_1_without_mail(collect, mails, tmp_path):
    assert cli.collect(["-c", str(tmp_path / "missing.json"), "-e", str(tmp_path / "e.log")]) == 1

    assert mails == []
    assert "no configuration: [Errno 2]" in (tmp_path / "e.log").read_text()


def test_invalid_configuration_exits_with_1_and_error_mail(collect, mails, config_data):
    del config_data["dataPath"]

    assert collect() == 1

    assert error_mails(mails) == ["no config parameter: 'dataPath'"]


def test_invalid_mail_section_exits_with_1_without_mail(collect, mails, config_data):
    del config_data["mail"]

    assert collect() == 1

    assert mails == []


def test_device_error_exits_with_1_and_error_mail(collect, mails, answers):
    answers.extend([requests.exceptions.ConnectTimeout("connect timed out")] * 4)

    assert collect() == 1

    assert error_mails(mails) == ["failed to get device data after 4 attempts: connect timed out"]


def test_unknown_parameter_in_the_answer_exits_with_1_and_error_mail(collect, mails, answers):
    answers.append({"D_Y_2_1": "1", "D_Y_1": "5"})

    assert collect() == 1

    assert error_mails(mails) == [
        "unknown consumption parameter 'D_Y_1': expected D_Y_2_<n> (consumption of n days ago)"
    ]


def test_missing_parameter_file_exits_with_1_and_error_mail(collect, mails, config_data, tmp_path):
    config_data["parameterFile"] = str(tmp_path / "missing.csv")

    assert collect() == 1

    assert error_mails(mails) == [
        f"[Errno 2] No such file or directory: '{tmp_path / 'missing.csv'}'"
    ]


def test_data_folder_that_cannot_be_created_exits_with_1_and_error_mail(
    collect, mails, config_data, tmp_path
):
    config_data["dataPath"] = str(tmp_path / "missing" / "data")

    assert collect() == 1

    (text,) = error_mails(mails)
    assert text.startswith("creation data folder failed: [Errno 2] No such file or directory")


def test_invalid_data_file_exits_with_1_and_error_mail(collect, mails, tmp_path):
    (tmp_path / "data").mkdir()
    path = tmp_path / "data" / "gruenbeck_water_consumption_2026.csv"
    path.write_text("day,litres\n2026-11-01,1\n")

    assert collect() == 1

    assert error_mails(mails) == [
        f"{path} has no column 'date', 'value' of dataFile.fieldnames (columns: day, litres):"
        " nothing written"
    ]
    assert path.read_text() == "day,litres\n2026-11-01,1\n"


def test_differing_stored_value_exits_with_1_and_error_mail(collect, mails, tmp_path):
    (tmp_path / "data").mkdir()
    path = tmp_path / "data" / "gruenbeck_water_consumption_2026.csv"
    path.write_text("date,value\n2026-11-09,7\n")

    assert collect() == 1

    (text,) = error_mails(mails)
    assert text.startswith("the new values differ from the stored ones (2026-11-09: stored 7")


def test_unexpected_error_exits_with_1_and_error_mail_with_traceback(
    collect, mails, monkeypatch, tmp_path
):
    def disk_full(source, target):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(storage.os, "replace", disk_full)

    assert collect() == 1

    (text,) = error_mails(mails)
    assert text.startswith("unexpected error: OSError: [Errno 28] No space left on device\n\n")
    assert "Traceback (most recent call last):" in text
    assert 'in disk_full\n    raise OSError(28, "No space left on device")' in text
    log = (tmp_path / "errors.log").read_text()
    assert "ERROR - unexpected error: OSError: [Errno 28] No space left on device\n" in log
    assert "Traceback (most recent call last):" in log


def test_failed_data_mail_exits_with_1_without_error_mail(collect, mails, monkeypatch, tmp_path):
    def refused(param, folder):
        raise ValueError("Error preparing email: refused")

    monkeypatch.setattr(mail, "send_mail", refused)

    assert collect() == 1

    assert error_mails(mails) == []
    assert (tmp_path / "data" / "gruenbeck_water_consumption_2026.csv").exists()


def test_failed_error_mail_keeps_exit_code_1(collect, monkeypatch, config_data, tmp_path):
    def refused(param, subject, text):
        raise ValueError("Error preparing email: refused")

    monkeypatch.setattr(mail, "send_mail_text", refused)
    del config_data["dataPath"]

    assert collect() == 1

    assert "Failed to send error notification email: Error preparing email: refused" in (
        (tmp_path / "errors.log").read_text()
    )


def test_missing_log_folder_exits_with_1_without_mail(mails, tmp_path, capsys, answers):
    log_file = tmp_path / "missing" / "errors.log"

    assert cli.collect(["-c", str(tmp_path / "config.json"), "-e", str(log_file)]) == 1

    assert capsys.readouterr().err == (
        f"gruenbeck-collect: cannot open the log file: [Errno 2] No such file or directory:"
        f" '{log_file}'\n"
    )
    assert mails == []


def test_keyboard_interrupt_is_not_caught(collect, answers):
    answers.append(KeyboardInterrupt())

    # BaseException, not an error of the run: no error mail, the interpreter stops
    with pytest.raises(KeyboardInterrupt):
        collect()


def test_errors_of_the_package_have_a_common_base_class():
    for error in (
        config.ConfigurationError,
        device.DeviceError,
        storage.StorageError,
        cli.CollectError,
        analysis.AnalysisError,
    ):
        assert issubclass(error, errors.GruenbeckError)
    # read_configuration_file() callers (scripts/log_device_rollover.py) catch ValueError
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
def test_analyse_exits_with_1_and_the_message(monkeypatch, capsys, error, message):
    def fail(config_file):
        raise error

    monkeypatch.setattr(analysis, "main", fail)

    assert cli.analyse(["-c", "c.json"]) == 1

    assert capsys.readouterr().err == f"gruenbeck-analyse: {message}{error}\n"


def test_analyse_exits_with_0(monkeypatch):
    monkeypatch.setattr(analysis, "main", lambda config_file: None)

    assert cli.analyse([]) == 0


# --- logging ------------------------------------------------------------------------


def test_every_module_logs_with_its_own_name():
    assert cli.logger.name == "gruenbeck.cli"
    assert config.logger.name == "gruenbeck.config"
    assert device.logger.name == "gruenbeck.device"
    assert storage.logger.name == "gruenbeck.storage"
    assert cli.package_logger.name == "gruenbeck"


def test_importing_the_package_configures_no_logging():
    # a new interpreter: the tests of this process call setup_logging()
    code = (
        "import logging, gruenbeck.analysis, gruenbeck.cli, gruenbeck.config,"
        " gruenbeck.device, gruenbeck.mail, gruenbeck.storage;"
        " logger = logging.getLogger('gruenbeck');"
        " print(logger.level, logger.handlers, logging.getLogger().handlers)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=60
    )

    assert result.stdout == "0 [] []\n"


def test_setup_logging_configures_the_package_logger(tmp_path):
    cli.setup_logging(True, tmp_path / "errors.log")

    assert cli.package_logger.level == logging.INFO
    assert [type(h).__name__ for h in cli.package_logger.handlers] == [
        "StreamHandler",
        "RotatingFileHandler",
    ]
