"""
error paths of the data collector (characterization of P006-S1): handle_error, the
configuration and the data folder, the retries of the device request, get_mail and main

Since P006-S3 the configuration is checked when it is loaded (tests/test_config.py).
"""

import copy
import datetime
import logging
import smtplib
import sys

import pytest

# the fixture device is the fake device, so the module is used as gruenbeck.device
import gruenbeck.device
from gruenbeck import cli, mail, storage
from gruenbeck import config as configuration

PREFIX = "p"
TODAY = datetime.date(2026, 11, 23)
MEMORY = [f"D_Y_2_{n}" for n in range(1, 15)]


@pytest.fixture
def mails(monkeypatch):
    """records data and error mails instead of sending them"""
    sent = []

    def record(settings, subject, text, attachments=()):
        if subject == cli.ERROR_MAIL_SUBJECT:
            sent.append((subject, settings, text))
        else:
            # the data mail attaches the csv files of the data folder
            sent.append(("data", settings, next(iter(attachments)).parent))

    monkeypatch.setattr(mail, "send_mail", record)
    return sent


def mail_settings(config_data):
    """the mail section of config_data as the loaded configuration has it"""
    section = config_data["mail"]
    return configuration.Mail(
        smtp_server=section["smtpServer"],
        smtp_port=section["smtpPort"],
        smtp_security=None,
        sender_email=section["senderEmail"],
        sender_password=section["senderPassword"],
        recipients=tuple(section["recipients"]),
        subject=section["subject"],
        retries=3,
        retry_delay=5.0,
    )


@pytest.fixture
def logs(caplog):
    """(level, message) of the records of the data collector, INFO and above"""
    caplog.set_level(logging.INFO, logger=cli.package_logger.name)

    def records():
        return [
            (record.levelname, record.getMessage())
            for record in caplog.records
            if record.name.startswith(f"{cli.package_logger.name}.")
        ]

    return records


# --- report_error: log and error mail ------------------------------------------------


def test_report_error_logs_and_sends_the_error_mail(mails, logs, loaded_config):
    # no exit (no SystemExit): since P006-S4 main() sets the exit code
    cli.report_error(loaded_config.mail, "something failed")

    assert mails == [
        (
            "gruenbeck data collector failure",
            loaded_config.mail,
            "something failed",
        )
    ]
    assert logs() == [
        ("ERROR", "something failed"),
        ("INFO", "Error notification email sent"),
    ]


def test_report_error_sends_a_text_mail_over_smtp(smtp, sleeps, loaded_config):
    cli.report_error(loaded_config.mail, "something failed")

    (message,) = smtp.messages()
    assert message["Subject"] == "gruenbeck data collector failure"
    assert message.get_content_type() == "text/plain"
    assert message.get_content() == "something failed\n"


def test_failed_error_mail_is_logged(smtp, sleeps, logs, loaded_config):
    smtp.errors = [("login", smtplib.SMTPAuthenticationError(535, b"bad credentials"))]

    cli.report_error(loaded_config.mail, "something failed")

    assert logs() == [
        ("ERROR", "something failed"),
        (
            "ERROR",
            "Failed to send error notification email:"
            " Authentication failed: (535, b'bad credentials')",
        ),
    ]


def test_error_mail_without_mail_configuration_is_logged(smtp, logs):
    # None: the mail section of the configuration is missing or invalid
    cli.report_error(None, "something failed")

    assert logs() == [
        ("ERROR", "something failed"),
        ("ERROR", "Failed to send error notification email: no valid mail configuration"),
    ]
    assert smtp.connections == []


def test_texts_with_percent_signs_are_logged_unchanged(mails, logs, loaded_config):
    cli.report_error(loaded_config.mail, "the date does not match '%d.%m.%Y'")

    assert logs()[0] == ("ERROR", "the date does not match '%d.%m.%Y'")


# --- configuration and data folder ---------------------------------------------------


def test_missing_configuration_exits_with_1_without_mail(mails, logs, tmp_path):
    config_file = tmp_path / "missing.json"

    assert cli.main(str(config_file)) == 1

    assert logs()[1:] == [
        ("ERROR", f"no configuration: [Errno 2] No such file or directory: '{config_file}'")
    ]
    assert mails == []


def test_invalid_json_exits_with_1_without_mail(mails, logs, tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text("{not json")

    assert cli.main(str(config_file)) == 1

    assert logs()[1:] == [
        (
            "ERROR",
            f"configuration file {config_file} is not valid JSON: Expecting property name"
            " enclosed in double quotes: line 1 column 2 (char 1)",
        ),
        ("ERROR", "Failed to send error notification email: no valid mail configuration"),
    ]
    assert mails == []


def test_invalid_configuration_sends_every_problem_by_mail(mails, logs, config_data, write_config):
    del config_data["parameterFile"]
    config_data["softWaterSystem"]["timeout"] = 0

    assert cli.main(str(write_config(config_data))) == 1

    message = (
        "invalid config parameter softWaterSystem.timeout 0: must be a number greater"
        " than 0; no config parameter: 'parameterFile'"
    )
    assert logs()[1] == ("ERROR", message)
    assert mails == [("gruenbeck data collector failure", mail_settings(config_data), message)]


def test_invalid_mail_section_exits_with_1_without_mail(mails, logs, config_data, write_config):
    config_data["mail"]["smtpPort"] = "smtp"

    assert cli.main(str(write_config(config_data))) == 1

    assert logs()[1:] == [
        (
            "ERROR",
            "invalid config parameter mail.smtpPort 'smtp': expected a port number 1 ... 65535",
        ),
        ("ERROR", "Failed to send error notification email: no valid mail configuration"),
    ]
    assert mails == []


def test_data_folder_is_created(tmp_path, loaded_config):
    folder = tmp_path / "data"

    assert cli.get_data_folder(loaded_config) == folder
    assert folder.is_dir()


def test_data_folder_without_permission_is_an_error(monkeypatch, tmp_path, loaded_config):
    def denied(data_folder):
        raise PermissionError(13, "Permission denied", str(data_folder))

    monkeypatch.setattr(storage, "check_data_folder", denied)

    with pytest.raises(storage.StorageError) as err:
        cli.get_data_folder(loaded_config)

    assert str(err.value) == (
        f"creation data folder failed: [Errno 13] Permission denied: '{tmp_path / 'data'}'"
    )


def test_data_folder_in_a_missing_folder_is_an_error(tmp_path, config_data, write_config):
    config_data["dataPath"] = str(tmp_path / "a" / "data")
    loaded = gruenbeck.config.load_configuration(write_config(config_data))

    # only the last folder is created; up to P006-S4 a traceback without error mail
    with pytest.raises(storage.StorageError) as err:
        cli.get_data_folder(loaded)

    assert str(err.value) == (
        "creation data folder failed: [Errno 2] No such file or directory:"
        f" '{tmp_path / 'a' / 'data'}'"
    )


def test_device_parameter_is_read_from_the_parameter_file(loaded_config):
    parameter = cli.get_device_parameter(loaded_config)

    assert "D_Y_2_14" in parameter.get_parameter_list()


def test_missing_parameter_file_is_an_error(tmp_path, config_data, write_config):
    path = tmp_path / "missing.csv"
    config_data["parameterFile"] = str(path)
    loaded = gruenbeck.config.load_configuration(write_config(config_data))

    with pytest.raises(gruenbeck.device.DeviceError) as err:
        cli.get_device_parameter(loaded)

    # the text of the FileNotFoundError
    assert str(err.value) == f"[Errno 2] No such file or directory: '{path}'"


# --- fake device ----------------------------------------------------------------------


@pytest.fixture
def device(monkeypatch):
    """
    fake device: `device.errors` are raised by the next requests, then it answers
    `device.answer`; `device.calls` records (host, parameters, timeout)
    """

    class Device:
        def __init__(self):
            self.calls: list[tuple] = []
            self.errors: list[BaseException] = []
            self.answer = {"D_C_4_2": "16:00", **{name: "1" for name in MEMORY}}

        def fetch(self, host, parameters, timeout, session=None):
            self.calls.append((host, list(parameters), timeout))
            if self.errors:
                raise self.errors.pop(0)
            return dict(self.answer)

    fake = Device()
    monkeypatch.setattr(gruenbeck.device, "get_data_from_mux_http", fake.fetch)
    return fake


# --- data mail: get_mail ------------------------------------------------------------


def parts(message):
    """(content type, filename, content) of every part of a multipart mail"""
    return [
        (part.get_content_type(), part.get_filename(), part.get_content())
        for part in message.iter_parts()
    ]


def test_get_mail_sends_the_csv_files_of_the_data_folder(smtp, logs, tmp_path, loaded_config):
    (tmp_path / "gruenbeck_2026.csv").write_text("date,value\n2026-11-22,101\n")
    (tmp_path / "gruenbeck_2025.csv").write_bytes(b"date,value\r\n2025-12-31,3\r\n")
    (tmp_path / "notes.txt").write_text("not attached")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "deeper.csv").write_text("not attached")

    assert cli.get_mail(loaded_config, tmp_path) is True

    (message,) = smtp.messages()
    # the subject is the one of the mail section
    assert message["Subject"] == "[data collector] - gruenbeck"
    assert message.get_content_type() == "multipart/mixed"
    # attachments sorted by name
    assert parts(message) == [
        ("text/plain", None, "your stored data\n"),
        ("application/octet-stream", "gruenbeck_2025.csv", b"date,value\r\n2025-12-31,3\r\n"),
        ("application/octet-stream", "gruenbeck_2026.csv", b"date,value\n2026-11-22,101\n"),
    ]
    assert logs() == [("INFO", "mail sent successfully")]


def test_get_mail_without_csv_files_says_so(smtp, logs, tmp_path, loaded_config):
    (tmp_path / "notes.txt").write_text("not attached")

    assert cli.get_mail(loaded_config, tmp_path) is True

    (message,) = smtp.messages()
    assert message.get_content_type() == "text/plain"
    assert message.get_content() == "your stored data\n\nNo data files found to attach.\n"
    assert logs() == [("INFO", "mail sent successfully")]


def test_get_mail_without_data_folder_returns_false(smtp, logs, tmp_path, loaded_config):
    folder = tmp_path / "missing"

    assert cli.get_mail(loaded_config, folder) is False

    assert logs() == [
        (
            "ERROR",
            f"mail sending failed: data folder does not exist or is not a directory: {folder}",
        )
    ]
    assert smtp.connections == []


@pytest.mark.parametrize(
    "error, message",
    [
        (
            mail.MailError("Authentication failed: x"),
            "mail sending failed: Authentication failed: x",
        ),
        (RuntimeError("boom"), "unexpected error during mail sending: boom"),
    ],
    ids=lambda value: value if isinstance(value, str) else type(value).__name__,
)
def test_failed_data_mail_returns_false(monkeypatch, logs, tmp_path, loaded_config, error, message):
    def fail(settings, subject, text, attachments=()):
        raise error

    monkeypatch.setattr(mail, "send_mail", fail)

    assert cli.get_mail(loaded_config, tmp_path) is False
    assert logs() == [("ERROR", message)]


def test_data_mail_over_smtp_with_rejected_login_returns_false(
    smtp, sleeps, logs, tmp_path, loaded_config
):
    smtp.errors = [("login", smtplib.SMTPAuthenticationError(535, b"bad credentials"))]

    assert cli.get_mail(loaded_config, tmp_path) is False
    assert logs() == [
        ("ERROR", "mail sending failed: Authentication failed: (535, b'bad credentials')")
    ]


# --- complete run -------------------------------------------------------------------


@pytest.fixture
def run(device, mails, monkeypatch, config_data, write_config):
    """
    run main() on TODAY 16:00 with the fake device
    :return: function(**changes); a change replaces a top-level key of the
        configuration, None removes it
    """
    now = datetime.datetime.combine(TODAY, datetime.time(16, 0))
    monkeypatch.setattr(cli, "local_now", lambda: now)

    def run_main(**changes):
        config = copy.deepcopy(config_data)
        config["dataFile"]["prefix"] = PREFIX
        config.update(changes)
        config_file = write_config(
            {key: value for key, value in config.items() if value is not None}
        )
        return cli.main(str(config_file))

    return run_main


def test_successful_run_logs_start_and_end(run, device, mails, logs, tmp_path, config_data):
    assert run() == 0

    assert logs()[0] == ("INFO", f"run script: {sys.argv[0]}")
    assert logs()[-2:] == [
        ("INFO", "mail sent successfully"),
        ("INFO", "Data collection completed"),
    ]
    assert mails == [("data", mail_settings(config_data), tmp_path / "data")]
    assert len((tmp_path / "data" / f"{PREFIX}_2026.csv").read_text().splitlines()) == 15


def test_run_with_failed_data_mail_keeps_the_data_and_exits_with_1(
    run, device, monkeypatch, logs, tmp_path
):
    subjects = []

    def fail(settings, subject, text, attachments=()):
        subjects.append(subject)
        raise mail.MailError("Authentication failed: refused")

    monkeypatch.setattr(mail, "send_mail", fail)

    assert run() == 1
    assert (tmp_path / "data" / f"{PREFIX}_2026.csv").exists()
    assert logs()[-2:] == [
        ("ERROR", "mail sending failed: Authentication failed: refused"),
        ("ERROR", "data was collected and stored, but email sending failed"),
    ]
    # no error mail in this case: the data mail was the only attempt
    assert subjects == ["[data collector] - gruenbeck"]


def test_run_without_consumption_values_is_an_error(run, device, mails, tmp_path):
    device.answer = {"D_C_4_2": "16:00"}

    assert run() == 1
    assert [text for kind, _, text in mails] == ["no data was processed"]
    assert list((tmp_path / "data").iterdir()) == []


def test_run_without_configuration_file_asks_nobody(device, mails, tmp_path):
    assert cli.main(str(tmp_path / "missing.json")) == 1
    assert device.calls == []
    assert mails == []


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"dataPath": None}, "no config parameter: 'dataPath'"),
        ({"dataFile": None}, "no config parameter: 'dataFile'"),
        ({"parameterFile": None}, "no config parameter: 'parameterFile'"),
        ({"softWaterSystem": None}, "no config parameter: 'softWaterSystem'"),
        ({"softWaterSystem": {}}, "no config parameter: 'softWaterSystem.host'"),
        (
            {"dataPath": None, "softWaterSystem": {"host": ""}},
            "invalid config parameter softWaterSystem.host '': expected a non-empty"
            " text; no config parameter: 'dataPath'",
        ),
    ],
    ids=lambda value: value if isinstance(value, str) else str(value),
)
def test_run_with_incomplete_configuration_fails_before_asking_the_device(
    run, device, mails, tmp_path, changes, message
):
    assert run(**changes) == 1
    assert device.calls == []
    assert [text for _, _, text in mails] == [message]
    assert not list(tmp_path.glob("data/*.csv"))


def test_run_without_valid_mail_section_fails_without_mail(run, device, mails, logs, tmp_path):
    assert run(mail=None, dataPath=None) == 1
    assert device.calls == []
    assert mails == []
    assert logs()[1] == (
        "ERROR",
        "no config parameter: 'mail'; no config parameter: 'dataPath'",
    )
