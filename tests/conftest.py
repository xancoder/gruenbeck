import copy
import email
import email.policy
import json
import logging
import pathlib
import smtplib
import time

import pytest

from gruenbeck import config

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def repo_root() -> pathlib.Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def config_example_file(repo_root) -> pathlib.Path:
    """example configuration; the real src/config.json is not versioned"""
    return repo_root / "src" / "config.example.json"


@pytest.fixture(scope="session")
def parameter_file(repo_root) -> pathlib.Path:
    return repo_root / "assets" / "Gruenbeck_Webserver_Dokumentation.csv"


# mail section of the configurations of the tests (no mail leaves a test: the tests
# replace the functions of gruenbeck.mail or smtplib)
MAIL_SECTION = {
    "recipients": ["receiver@example.com"],
    "senderEmail": "sender@example.com",
    "senderPassword": "test-password",
    "smtpPort": 587,
    "smtpServer": "smtp.example.com",
    "subject": "[data collector] - gruenbeck",
}


@pytest.fixture
def config_data(tmp_path, parameter_file) -> dict:
    """a complete and valid configuration as in the JSON file; data folder in tmp_path"""
    return {
        "dataFile": {
            "datePattern": "%Y-%m-%d",
            "fieldnames": {"date": "date", "value": "value"},
            "prefix": "gruenbeck_water_consumption",
        },
        "dataPath": str(tmp_path / "data"),
        "mail": copy.deepcopy(MAIL_SECTION),
        "parameterFile": str(parameter_file),
        "softWaterSystem": {"host": "device.lan"},
    }


@pytest.fixture
def write_config(tmp_path):
    """writes a configuration (dictionary) as JSON; returns the path of the file"""

    def write(data, path=None) -> pathlib.Path:
        path = pathlib.Path(path) if path is not None else tmp_path / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    return write


@pytest.fixture
def loaded_config(config_data, write_config) -> config.Configuration:
    """config_data, loaded and checked"""
    return config.load_configuration(write_config(config_data))


class FakeSMTP:
    """
    records connections and calls instead of talking to an SMTP server

    `errors` lists (step, exception) pairs; when a step (connect, starttls, login,
    sendmail, quit) is reached and the first pair names it, the exception is raised
    and the pair is used up.
    """

    def __init__(self):
        self.connections: list[dict] = []
        self.errors: list[tuple[str, BaseException]] = []

    def step(self, name):
        if self.errors and self.errors[0][0] == name:
            raise self.errors.pop(0)[1]

    def factory(self, kind):
        fake = self

        class Server:
            def __init__(self, host, port, **kwargs):
                fake.step("connect")
                self.calls: list[tuple] = []
                fake.connections.append(
                    {
                        "kind": kind,
                        "host": host,
                        "port": port,
                        "kwargs": kwargs,
                        "calls": self.calls,
                    }
                )

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                self.calls.append(("exit",))
                return False

            def starttls(self, context=None):
                fake.step("starttls")
                self.calls.append(("starttls", context))

            def login(self, user, password):
                fake.step("login")
                self.calls.append(("login", user, password))

            def sendmail(self, from_addr, to_addrs, msg):
                fake.step("sendmail")
                self.calls.append(("sendmail", from_addr, to_addrs, msg))

            def quit(self):
                fake.step("quit")
                self.calls.append(("quit",))

        return Server

    def raw_messages(self):
        """sent mails as given to sendmail()"""
        return [
            call[3]
            for connection in self.connections
            for call in connection["calls"]
            if call[0] == "sendmail"
        ]

    def messages(self):
        """sent mails, parsed"""
        return [
            email.message_from_string(raw, policy=email.policy.default)
            for raw in self.raw_messages()
        ]


@pytest.fixture(autouse=True)
def restore_package_logger():
    """removes the handlers and the level that setup_logging() gives the package logger"""
    logger = logging.getLogger("gruenbeck")
    level, handlers = logger.level, list(logger.handlers)
    yield
    for handler in [h for h in logger.handlers if h not in handlers]:
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(level)


@pytest.fixture
def smtp(monkeypatch):
    """fake SMTP server in place of smtplib.SMTP and smtplib.SMTP_SSL"""
    fake = FakeSMTP()
    monkeypatch.setattr(smtplib, "SMTP", fake.factory("SMTP"))
    monkeypatch.setattr(smtplib, "SMTP_SSL", fake.factory("SMTP_SSL"))
    return fake


@pytest.fixture
def sleeps(monkeypatch):
    """records the waiting time between attempts (time.sleep) instead of waiting"""
    waited: list[float] = []
    monkeypatch.setattr(time, "sleep", waited.append)
    return waited
