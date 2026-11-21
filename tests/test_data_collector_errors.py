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
import requests

# the fixture device is the fake device, so the module is used as gruenbeck.device
import gruenbeck.device
from gruenbeck import cli, mail, storage

PREFIX = "p"
TODAY = datetime.date(2026, 11, 23)
MEMORY = [f"D_Y_2_{n}" for n in range(1, 15)]


@pytest.fixture
def mails(monkeypatch):
    """records data and error mails instead of sending them"""
    sent = []
    monkeypatch.setattr(
        mail,
        "send_mail",
        lambda param, data_folder: sent.append(("data", param, data_folder)),
    )
    monkeypatch.setattr(
        mail,
        "send_mail_text",
        lambda param, subject, text: sent.append((subject, param, text)),
    )
    return sent


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


# --- handle_error -------------------------------------------------------------------


def test_handle_error_logs_sends_the_error_mail_and_exits_with_1(mails, logs, loaded_config):
    with pytest.raises(SystemExit) as exit_info:
        cli.handle_error(loaded_config.mail, "[-] something failed")

    assert exit_info.value.code == 1
    assert mails == [
        (
            "gruenbeck data collector failure",
            loaded_config.mail.as_dict(),
            "[-] something failed",
        )
    ]
    assert logs() == [
        ("ERROR", "[-] something failed"),
        ("INFO", "[*] Error notification email sent"),
        ("INFO", "[*] Exiting program due to error"),
    ]


def test_handle_error_sends_a_text_mail_over_smtp(smtp, sleeps, loaded_config):
    with pytest.raises(SystemExit):
        cli.handle_error(loaded_config.mail, "[-] something failed")

    (message,) = smtp.messages()
    assert message["Subject"] == "gruenbeck data collector failure"
    assert [part.get_content() for part in message.iter_parts()] == ["[-] something failed"]


def test_failed_error_mail_is_logged_and_the_exit_code_stays_1(smtp, sleeps, logs, loaded_config):
    smtp.errors = [("login", smtplib.SMTPAuthenticationError(535, b"bad credentials"))]

    with pytest.raises(SystemExit) as exit_info:
        cli.handle_error(loaded_config.mail, "[-] something failed")

    assert exit_info.value.code == 1
    assert logs() == [
        ("ERROR", "[-] something failed"),
        (
            "ERROR",
            "[-] Failed to send error notification email: Error preparing email:"
            " Authentication failed: (535, b'bad credentials')",
        ),
        ("INFO", "[*] Exiting program due to error"),
    ]


def test_error_mail_without_mail_configuration_is_logged(smtp, logs):
    # None: the mail section of the configuration is missing or invalid
    with pytest.raises(SystemExit) as exit_info:
        cli.handle_error(None, "[-] something failed")

    assert exit_info.value.code == 1
    assert logs() == [
        ("ERROR", "[-] something failed"),
        ("ERROR", "[-] Failed to send error notification email: no valid mail configuration"),
        ("INFO", "[*] Exiting program due to error"),
    ]
    assert smtp.connections == []


# --- configuration and data folder ---------------------------------------------------


def test_configuration_is_loaded_and_checked(config_data, write_config, loaded_config):
    assert cli.get_configuration(str(write_config(config_data))) == loaded_config


def test_missing_configuration_exits_with_1_without_mail(mails, logs, tmp_path):
    config_file = tmp_path / "missing.json"

    with pytest.raises(SystemExit) as exit_info:
        cli.get_configuration(str(config_file))

    assert exit_info.value.code == 1
    assert logs() == [
        ("ERROR", f"[-] no configuration: [Errno 2] No such file or directory: '{config_file}'")
    ]
    assert mails == []


def test_invalid_json_exits_with_1_without_mail(mails, logs, tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text("{not json")

    with pytest.raises(SystemExit) as exit_info:
        cli.get_configuration(str(config_file))

    assert exit_info.value.code == 1
    assert logs()[:2] == [
        (
            "ERROR",
            f"[-] configuration file {config_file} is not valid JSON: Expecting property name"
            " enclosed in double quotes: line 1 column 2 (char 1)",
        ),
        ("ERROR", "[-] Failed to send error notification email: no valid mail configuration"),
    ]
    assert mails == []


def test_invalid_configuration_sends_every_problem_by_mail(mails, logs, config_data, write_config):
    del config_data["parameterFile"]
    config_data["softWaterSystem"]["timeout"] = 0

    with pytest.raises(SystemExit) as exit_info:
        cli.get_configuration(str(write_config(config_data)))

    assert exit_info.value.code == 1
    message = (
        "[-] invalid config parameter softWaterSystem.timeout 0: must be a number greater"
        " than 0; no config parameter: 'parameterFile'"
    )
    assert logs()[0] == ("ERROR", message)
    assert mails == [("gruenbeck data collector failure", config_data["mail"], message)]


def test_invalid_mail_section_exits_with_1_without_mail(mails, logs, config_data, write_config):
    config_data["mail"]["smtpPort"] = "smtp"

    with pytest.raises(SystemExit) as exit_info:
        cli.get_configuration(str(write_config(config_data)))

    assert exit_info.value.code == 1
    assert logs()[:2] == [
        (
            "ERROR",
            "[-] invalid config parameter mail.smtpPort 'smtp': expected a port number 1 ... 65535",
        ),
        ("ERROR", "[-] Failed to send error notification email: no valid mail configuration"),
    ]
    assert mails == []


def test_data_folder_is_created(tmp_path, loaded_config):
    folder = tmp_path / "data"

    assert cli.get_data_folder(loaded_config) == folder
    assert folder.is_dir()


def test_data_folder_without_permission_is_an_error(mails, monkeypatch, tmp_path, loaded_config):
    def denied(data_folder):
        raise PermissionError(13, "Permission denied", str(data_folder))

    monkeypatch.setattr(storage, "check_data_folder", denied)

    with pytest.raises(SystemExit):
        cli.get_data_folder(loaded_config)

    assert [text for _, _, text in mails] == [
        f"[-] creation data folder failed: [Errno 13] Permission denied: '{tmp_path / 'data'}'"
    ]


def test_data_folder_in_a_missing_folder_raises_without_mail(
    mails, tmp_path, config_data, write_config
):
    config_data["dataPath"] = str(tmp_path / "a" / "data")
    loaded = gruenbeck.config.load_configuration(write_config(config_data))

    # only the last folder is created; FileNotFoundError is not caught
    with pytest.raises(FileNotFoundError):
        cli.get_data_folder(loaded)

    assert mails == []


def test_device_parameter_is_read_from_the_parameter_file(loaded_config):
    parameter = cli.get_device_parameter(loaded_config)

    assert "D_Y_2_14" in parameter.get_parameter_list()


def test_missing_parameter_file_is_an_error(mails, tmp_path, config_data, write_config):
    path = tmp_path / "missing.csv"
    config_data["parameterFile"] = str(path)
    loaded = gruenbeck.config.load_configuration(write_config(config_data))

    with pytest.raises(SystemExit):
        cli.get_device_parameter(loaded)

    # the text of the FileNotFoundError, without prefix
    assert [text for _, _, text in mails] == [f"[Errno 2] No such file or directory: '{path}'"]


# --- device request with retries ----------------------------------------------------


@pytest.fixture
def device_parameter(parameter_file):
    return gruenbeck.device.Parameter(str(parameter_file))


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

        def fetch(self, host, parameters, timeout):
            self.calls.append((host, list(parameters), timeout))
            if self.errors:
                raise self.errors.pop(0)
            return dict(self.answer)

    fake = Device()
    monkeypatch.setattr(gruenbeck.device, "get_data_from_mux_http", fake.fetch)
    return fake


def test_device_request_with_host_and_timeout(
    device, device_parameter, sleeps, config_data, write_config
):
    config_data["softWaterSystem"]["timeout"] = 7
    config = gruenbeck.config.load_configuration(write_config(config_data))

    result = cli.get_device_data(config, device_parameter)

    assert result == device.answer
    assert device.calls == [("device.lan", ["D_C_4_2", *MEMORY], 7.0)]
    assert sleeps == []


@pytest.mark.parametrize(
    "error, warning",
    [
        (
            ValueError("[-] failed to parse xml: x"),
            "[-] invalid device response: [-] failed to parse xml: x",
        ),
        (requests.exceptions.ReadTimeout("read timed out"), "[-] request failed: read timed out"),
        (requests.exceptions.HTTPError("500 Server Error"), "[-] request failed: 500 Server Error"),
        (RuntimeError("boom"), "[-] unexpected error: boom"),
        (TypeError("bad type"), "[-] unexpected error: bad type"),
    ],
    ids=lambda value: value if isinstance(value, str) else type(value).__name__,
)
def test_device_request_succeeds_after_retries(
    device, device_parameter, sleeps, logs, error, warning, loaded_config
):
    device.errors = [error, error]

    result = cli.get_device_data(loaded_config, device_parameter)

    assert result == device.answer
    assert len(device.calls) == 3
    assert sleeps == [5, 5]
    assert logs() == [
        ("WARNING", f"{warning}. Attempt 1/4"),
        ("INFO", "[*] Retry attempt 1/3 for API request"),
        ("WARNING", f"{warning}. Attempt 2/4"),
        ("INFO", "[*] Retry attempt 2/3 for API request"),
        ("INFO", "[*] Successfully retrieved data after 2 retry attempts"),
    ]


def test_device_request_fails_after_four_attempts(
    device, device_parameter, sleeps, mails, loaded_config
):
    device.errors = [
        requests.exceptions.ConnectTimeout("connect timed out"),
        requests.exceptions.ConnectionError("refused"),
        ValueError("[-] device response contains no values"),
        requests.exceptions.ReadTimeout("read timed out"),
        ValueError("not reached"),
    ]

    with pytest.raises(SystemExit) as exit_info:
        cli.get_device_data(loaded_config, device_parameter)

    assert exit_info.value.code == 1
    assert len(device.calls) == 4
    assert sleeps == [5, 5, 5]
    # the error mail names the last error only
    assert [text for _, _, text in mails] == [
        "[-] failed to get device data after 4 attempts: read timed out"
    ]


def test_number_of_retries_and_delay_are_parameters(
    device, device_parameter, sleeps, mails, loaded_config
):
    device.errors = [ValueError("bad")] * 2

    with pytest.raises(SystemExit):
        cli.get_device_data(loaded_config, device_parameter, max_retries=1, retry_delay=0.5)

    assert len(device.calls) == 2
    assert sleeps == [0.5]
    assert [text for _, _, text in mails] == ["[-] failed to get device data after 2 attempts: bad"]


def test_key_error_of_the_request_is_retried_like_other_errors(
    device, device_parameter, sleeps, mails, logs, loaded_config
):
    # up to P006-S3 a KeyError counted as missing config parameter and was not retried
    device.errors = [KeyError("text")]

    assert cli.get_device_data(loaded_config, device_parameter) == device.answer

    assert len(device.calls) == 2
    assert sleeps == [5]
    assert logs()[0] == ("WARNING", "[-] unexpected error: 'text'. Attempt 1/4")
    assert mails == []


# --- data mail: get_mail ------------------------------------------------------------


def test_get_mail_sends_the_data_folder(mails, logs, tmp_path, loaded_config):
    assert cli.get_mail(loaded_config, tmp_path) is True

    assert mails == [("data", loaded_config.mail.as_dict(), tmp_path)]
    assert logs() == [("INFO", "[*] mail sent successfully")]


@pytest.mark.parametrize(
    "error, message",
    [
        (KeyError("smtpServer"), "[-] no mail configured: 'smtpServer'"),
        (
            ValueError("Error preparing email: x"),
            "[-] mail sending failed: Error preparing email: x",
        ),
        (RuntimeError("boom"), "[-] unexpected error during mail sending: boom"),
    ],
    ids=lambda value: value if isinstance(value, str) else type(value).__name__,
)
def test_failed_data_mail_returns_false(monkeypatch, logs, tmp_path, loaded_config, error, message):
    def fail(param, data_folder):
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
        (
            "ERROR",
            "[-] mail sending failed: Error preparing email: Authentication failed:"
            " (535, b'bad credentials')",
        )
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
        cli.main(str(config_file))

    return run_main


def test_successful_run_logs_start_and_end(run, device, mails, logs, tmp_path, config_data):
    run()

    assert logs()[0] == ("INFO", f"[*] run script: {sys.argv[0]}")
    assert logs()[-2:] == [
        ("INFO", "[*] mail sent successfully"),
        ("INFO", "[*] Data collection completed"),
    ]
    assert mails == [("data", config_data["mail"], tmp_path / "data")]
    assert len((tmp_path / "data" / f"{PREFIX}_2026.csv").read_text().splitlines()) == 15


def test_run_with_failed_data_mail_keeps_the_data_and_exits_with_1(
    run, device, monkeypatch, logs, tmp_path
):
    sent = []

    def fail(param, data_folder):
        raise ValueError("Error preparing email: refused")

    monkeypatch.setattr(mail, "send_mail", fail)
    monkeypatch.setattr(mail, "send_mail_text", lambda *args: sent.append(args))

    with pytest.raises(SystemExit) as exit_info:
        run()

    assert exit_info.value.code == 1
    assert (tmp_path / "data" / f"{PREFIX}_2026.csv").exists()
    assert logs()[-2:] == [
        ("ERROR", "[-] mail sending failed: Error preparing email: refused"),
        ("ERROR", "[-] data was collected and stored, but email sending failed"),
    ]
    # no error mail in this case
    assert sent == []


def test_run_without_consumption_values_is_an_error(run, device, mails, tmp_path):
    device.answer = {"D_C_4_2": "16:00"}

    with pytest.raises(SystemExit) as exit_info:
        run()

    assert exit_info.value.code == 1
    assert [text for kind, _, text in mails] == ["[-] no data was processed"]
    assert list((tmp_path / "data").iterdir()) == []


def test_run_without_configuration_file_asks_nobody(device, mails, tmp_path):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(str(tmp_path / "missing.json"))

    assert exit_info.value.code == 1
    assert device.calls == []
    assert mails == []


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"dataPath": None}, "[-] no config parameter: 'dataPath'"),
        ({"dataFile": None}, "[-] no config parameter: 'dataFile'"),
        ({"parameterFile": None}, "[-] no config parameter: 'parameterFile'"),
        ({"softWaterSystem": None}, "[-] no config parameter: 'softWaterSystem'"),
        ({"softWaterSystem": {}}, "[-] no config parameter: 'softWaterSystem.host'"),
        (
            {"dataPath": None, "softWaterSystem": {"host": ""}},
            "[-] invalid config parameter softWaterSystem.host '': expected a non-empty"
            " text; no config parameter: 'dataPath'",
        ),
    ],
    ids=lambda value: value if isinstance(value, str) else str(value),
)
def test_run_with_incomplete_configuration_fails_before_asking_the_device(
    run, device, mails, tmp_path, changes, message
):
    with pytest.raises(SystemExit) as exit_info:
        run(**changes)

    assert exit_info.value.code == 1
    assert device.calls == []
    assert [text for _, _, text in mails] == [message]
    assert not list(tmp_path.glob("data/*.csv"))


def test_run_without_valid_mail_section_fails_without_mail(run, device, mails, logs, tmp_path):
    with pytest.raises(SystemExit) as exit_info:
        run(mail=None, dataPath=None)

    assert exit_info.value.code == 1
    assert device.calls == []
    assert mails == []
    assert logs()[1] == (
        "ERROR",
        "[-] no config parameter: 'mail'; no config parameter: 'dataPath'",
    )
