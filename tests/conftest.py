import email
import email.policy
import importlib.util
import pathlib
import smtplib
import time

import pytest

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


@pytest.fixture
def data_collector():
    """
    src/data-collector.py as a module (the file name is not importable with 'import')
    """
    path = REPO_ROOT / "src" / "data-collector.py"
    spec = importlib.util.spec_from_file_location("data_collector", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
