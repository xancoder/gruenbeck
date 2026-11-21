"""
characterization of the error paths of src/data-collector.py (P006-S1): handle_error,
the configuration getters, the retries of the device request, get_mail and main
"""

import datetime
import json
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
MAIL = {
    "recipients": ["one@example.com"],
    "senderEmail": "sender@example.com",
    "senderPassword": "test-password",
    "smtpPort": 587,
    "smtpServer": "smtp.example.com",
    "subject": "data",
}


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


def test_handle_error_logs_sends_the_error_mail_and_exits_with_1(mails, logs):
    with pytest.raises(SystemExit) as exit_info:
        cli.handle_error({"mail": {"smtpServer": "x"}}, "[-] something failed")

    assert exit_info.value.code == 1
    assert mails == [
        ("gruenbeck data collector failure", {"smtpServer": "x"}, "[-] something failed")
    ]
    assert logs() == [
        ("ERROR", "[-] something failed"),
        ("INFO", "[*] Error notification email sent"),
        ("INFO", "[*] Exiting program due to error"),
    ]


def test_handle_error_sends_a_text_mail_over_smtp(smtp, sleeps):
    with pytest.raises(SystemExit):
        cli.handle_error({"mail": MAIL}, "[-] something failed")

    (message,) = smtp.messages()
    assert message["Subject"] == "gruenbeck data collector failure"
    assert [part.get_content() for part in message.iter_parts()] == ["[-] something failed"]


def test_failed_error_mail_is_logged_and_the_exit_code_stays_1(smtp, sleeps, logs):
    smtp.errors = [("login", smtplib.SMTPAuthenticationError(535, b"bad credentials"))]

    with pytest.raises(SystemExit) as exit_info:
        cli.handle_error({"mail": MAIL}, "[-] something failed")

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


@pytest.mark.parametrize(
    "config, reason",
    [({}, "'mail'"), ({"mail": {}}, "Invalid mail configuration: 'smtpServer'")],
    ids=["no mail section", "empty mail section"],
)
def test_error_mail_without_mail_configuration_is_logged(smtp, logs, config, reason):
    with pytest.raises(SystemExit) as exit_info:
        cli.handle_error(config, "[-] something failed")

    assert exit_info.value.code == 1
    assert ("ERROR", f"[-] Failed to send error notification email: {reason}") in logs()
    assert smtp.connections == []


# --- configuration getters ----------------------------------------------------------


def test_configuration_is_the_json_of_the_file(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"dataPath": "./data", "mail": {}}))

    assert cli.get_configuration(str(config_file)) == {"dataPath": "./data", "mail": {}}


def test_missing_configuration_exits_with_1_without_mail(mails, logs, tmp_path):
    config_file = tmp_path / "missing.json"

    with pytest.raises(SystemExit) as exit_info:
        cli.get_configuration(str(config_file))

    assert exit_info.value.code == 1
    assert logs() == [
        ("ERROR", f"[-] no configuration: [Errno 2] No such file or directory: '{config_file}'")
    ]
    assert mails == []


def test_invalid_json_raises_without_exit_code_and_mail(mails, tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text("{not json")

    with pytest.raises(json.JSONDecodeError):
        cli.get_configuration(str(config_file))

    assert mails == []


def test_data_folder_is_created(tmp_path):
    folder = tmp_path / "data"

    assert cli.get_data_folder({"dataPath": str(folder)}) == folder
    assert folder.is_dir()


def test_data_folder_without_data_path_is_an_error(mails):
    with pytest.raises(SystemExit) as exit_info:
        cli.get_data_folder({"mail": {}})

    assert exit_info.value.code == 1
    assert [text for _, _, text in mails] == ["[-] no config parameter: 'dataPath'"]


def test_data_folder_without_permission_is_an_error(mails, monkeypatch, tmp_path):
    def denied(data_folder):
        raise PermissionError(13, "Permission denied", data_folder)

    monkeypatch.setattr(storage, "check_data_folder", denied)

    with pytest.raises(SystemExit):
        cli.get_data_folder({"dataPath": "/root/data", "mail": {}})

    assert [text for _, _, text in mails] == [
        "[-] creation data folder failed: [Errno 13] Permission denied: '/root/data'"
    ]


def test_data_folder_in_a_missing_folder_raises_without_mail(mails, tmp_path):
    # only the last folder is created; FileNotFoundError is not caught
    with pytest.raises(FileNotFoundError):
        cli.get_data_folder({"dataPath": str(tmp_path / "a" / "data"), "mail": {}})

    assert mails == []


def test_device_parameter_is_read_from_the_parameter_file(parameter_file):
    parameter = cli.get_device_parameter({"parameterFile": str(parameter_file)})

    assert "D_Y_2_14" in parameter.get_parameter_list()


def test_device_parameter_without_parameter_file_is_an_error(mails):
    with pytest.raises(SystemExit) as exit_info:
        cli.get_device_parameter({"mail": {}})

    assert exit_info.value.code == 1
    assert [text for _, _, text in mails] == ["[-] no config parameter: 'parameterFile'"]


def test_missing_parameter_file_is_an_error(mails, tmp_path):
    path = tmp_path / "missing.csv"

    with pytest.raises(SystemExit):
        cli.get_device_parameter({"parameterFile": str(path), "mail": {}})

    # the text of the FileNotFoundError, without prefix
    assert [text for _, _, text in mails] == [f"[Errno 2] No such file or directory: '{path}'"]


@pytest.mark.parametrize(
    "device, timeout",
    [({}, 30.0), ({"timeout": 5}, 5.0), ({"timeout": "2.5"}, 2.5), ({"timeout": 0.1}, 0.1)],
)
def test_device_timeout_defaults_to_30_seconds(device, timeout):
    result = cli.get_device_timeout({"softWaterSystem": device})

    assert result == timeout
    assert type(result) is float


@pytest.mark.parametrize(
    "value, reason",
    [
        (0, "must be greater than 0"),
        (-1, "must be greater than 0"),
        ("nan", "must be greater than 0"),
        ("abc", "could not convert string to float: 'abc'"),
        (None, "float() argument must be a string or a real number, not 'NoneType'"),
        ([5], "float() argument must be a string or a real number, not 'list'"),
    ],
    ids=repr,
)
def test_invalid_device_timeout_is_an_error(mails, value, reason):
    with pytest.raises(SystemExit) as exit_info:
        cli.get_device_timeout({"softWaterSystem": {"timeout": value}, "mail": {}})

    assert exit_info.value.code == 1
    assert [text for _, _, text in mails] == [
        f"[-] invalid config parameter softWaterSystem.timeout: {reason}"
    ]


def test_device_timeout_without_device_section_is_an_error(mails):
    with pytest.raises(SystemExit):
        cli.get_device_timeout({"mail": {}})

    assert [text for _, _, text in mails] == ["[-] no config parameter: 'softWaterSystem'"]


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


DEVICE_CONFIG = {"softWaterSystem": {"host": "device.lan"}, "mail": {}}


def test_device_request_with_host_and_timeout(device, device_parameter, sleeps):
    config = {"softWaterSystem": {"host": "device.lan", "timeout": 7}, "mail": {}}

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
    device, device_parameter, sleeps, logs, error, warning
):
    device.errors = [error, error]

    result = cli.get_device_data(DEVICE_CONFIG, device_parameter)

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


def test_device_request_fails_after_four_attempts(device, device_parameter, sleeps, mails):
    device.errors = [
        requests.exceptions.ConnectTimeout("connect timed out"),
        requests.exceptions.ConnectionError("refused"),
        ValueError("[-] device response contains no values"),
        requests.exceptions.ReadTimeout("read timed out"),
        ValueError("not reached"),
    ]

    with pytest.raises(SystemExit) as exit_info:
        cli.get_device_data(DEVICE_CONFIG, device_parameter)

    assert exit_info.value.code == 1
    assert len(device.calls) == 4
    assert sleeps == [5, 5, 5]
    # the error mail names the last error only
    assert [text for _, _, text in mails] == [
        "[-] failed to get device data after 4 attempts: read timed out"
    ]


def test_number_of_retries_and_delay_are_parameters(device, device_parameter, sleeps, mails):
    device.errors = [ValueError("bad")] * 2

    with pytest.raises(SystemExit):
        cli.get_device_data(DEVICE_CONFIG, device_parameter, max_retries=1, retry_delay=0.5)

    assert len(device.calls) == 2
    assert sleeps == [0.5]
    assert [text for _, _, text in mails] == ["[-] failed to get device data after 2 attempts: bad"]


def test_device_request_without_host_is_not_retried(device, device_parameter, sleeps, mails):
    with pytest.raises(SystemExit):
        cli.get_device_data({"softWaterSystem": {}, "mail": {}}, device_parameter)

    assert device.calls == []
    assert sleeps == []
    assert [text for _, _, text in mails] == ["[-] no config parameter: 'host'"]


def test_key_error_of_the_request_counts_as_configuration_error(
    device, device_parameter, sleeps, mails
):
    device.errors = [KeyError("text")]

    with pytest.raises(SystemExit):
        cli.get_device_data(DEVICE_CONFIG, device_parameter)

    assert len(device.calls) == 1
    assert sleeps == []
    assert [text for _, _, text in mails] == ["[-] no config parameter: 'text'"]


# --- data mail: get_mail ------------------------------------------------------------


def test_get_mail_sends_the_data_folder(mails, logs, tmp_path):
    assert cli.get_mail({"mail": {"smtpServer": "x"}}, tmp_path) is True

    assert mails == [("data", {"smtpServer": "x"}, tmp_path)]
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
def test_failed_data_mail_returns_false(monkeypatch, logs, tmp_path, error, message):
    def fail(param, data_folder):
        raise error

    monkeypatch.setattr(mail, "send_mail", fail)

    assert cli.get_mail({"mail": {}}, tmp_path) is False
    assert logs() == [("ERROR", message)]


def test_data_mail_without_mail_section_returns_false(mails, logs, tmp_path):
    assert cli.get_mail({}, tmp_path) is False

    assert logs() == [("ERROR", "[-] no mail configured: 'mail'")]
    assert mails == []


def test_data_mail_over_smtp_with_rejected_login_returns_false(smtp, sleeps, logs, tmp_path):
    smtp.errors = [("login", smtplib.SMTPAuthenticationError(535, b"bad credentials"))]

    assert cli.get_mail({"mail": MAIL}, tmp_path) is False
    assert logs() == [
        (
            "ERROR",
            "[-] mail sending failed: Error preparing email: Authentication failed:"
            " (535, b'bad credentials')",
        )
    ]


# --- complete run -------------------------------------------------------------------


@pytest.fixture
def run(device, mails, monkeypatch, tmp_path, parameter_file):
    """
    run main() on TODAY 16:00 with the fake device
    :return: function(**changes); a change replaces a top-level key of the
        configuration, None removes it
    """
    now = datetime.datetime.combine(TODAY, datetime.time(16, 0))
    monkeypatch.setattr(cli, "local_now", lambda: now)

    def run_main(**changes):
        config = {
            "dataFile": {
                "datePattern": "%Y-%m-%d",
                "fieldnames": {"date": "date", "value": "value"},
                "prefix": PREFIX,
            },
            "dataPath": str(tmp_path / "data"),
            "mail": {"smtpServer": "x"},
            "parameterFile": str(parameter_file),
            "softWaterSystem": {"host": "device.lan"},
        }
        config.update(changes)
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps({key: value for key, value in config.items() if value is not None})
        )
        cli.main(str(config_file))

    return run_main


def test_successful_run_logs_start_and_end(run, device, mails, logs, tmp_path):
    run()

    assert logs()[0] == ("INFO", f"[*] run script: {sys.argv[0]}")
    assert logs()[-2:] == [
        ("INFO", "[*] mail sent successfully"),
        ("INFO", "[*] Data collection completed"),
    ]
    assert mails == [("data", {"smtpServer": "x"}, tmp_path / "data")]
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
        ({"softWaterSystem": {}}, "[-] no config parameter: 'host'"),
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
