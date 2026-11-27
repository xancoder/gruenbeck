"""gruenbeck-preview-mail: the data mail from the stored data, without the device (P008-S4)"""

import collections.abc
import dataclasses
import datetime
import email.message
import json
import pathlib
import smtplib
import typing

import pytest

from gruenbeck import collector, config, device, preview, report, report_html, storage

if typing.TYPE_CHECKING:
    from conftest import FakeSMTP

TODAY = "2026-11-23"
SUBJECT = "[data collector] - gruenbeck"


def week(first: str, *values: int | str) -> dict[str, int | str]:
    start = datetime.date.fromisoformat(first)
    return {
        (start + datetime.timedelta(days=offset)).isoformat(): value
        for offset, value in enumerate(values)
    }


def write_year(
    configuration: config.Configuration, year: int, rows: dict[str, int | str]
) -> pathlib.Path:
    folder = storage.check_data_folder(configuration.data_path)
    data_file = configuration.data_file
    path = storage.get_data_file(folder, data_file.prefix, year)
    storage.write_data(path, data_file.fieldnames, rows, data_file.date_pattern)
    return path


@pytest.fixture
def stored(loaded_config: config.Configuration) -> config.Configuration:
    """a configuration whose data folder has the yearly files of 2025 and 2026"""
    write_year(loaded_config, 2025, week("2025-11-17", 50, 50, 50, 50, 50, 50, 50))
    write_year(
        loaded_config,
        2026,
        {
            **week("2026-11-16", 100, 200, 150, 120, 300, 90, 140),
            **week("2026-11-23", 110, 210, 160, 130, 310, 100, 150),
        },
    )
    return loaded_config


@pytest.fixture(autouse=True)
def no_device(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """the device must not be asked: a call fails the test and is recorded"""
    calls: list[str] = []

    def fail(*args: object, **kwargs: object) -> typing.NoReturn:
        calls.append("device")
        raise AssertionError("the device was asked")

    monkeypatch.setattr(device, "get_data_from_mux_http", fail)
    monkeypatch.setattr(device, "get_device_data", fail)
    return calls


def data_files(folder: pathlib.Path) -> dict[str, bytes]:
    """name and content of every file in the folder"""
    return {path.name: path.read_bytes() for path in sorted(folder.iterdir())}


def run(configuration: config.Configuration, *options: str, today: str | None = TODAY) -> int:
    day = ["--today", today] if today is not None else []
    return int(preview.main(["-c", str(configuration.file), *day, *options]))


def text_of(message: email.message.EmailMessage) -> str:
    body = message.get_body(preferencelist=("plain",))
    assert isinstance(body, email.message.EmailMessage)
    content = body.get_content()
    assert isinstance(content, str)
    return content


def html_of(message: email.message.EmailMessage) -> str:
    body = message.get_body(preferencelist=("html",))
    assert isinstance(body, email.message.EmailMessage)
    content = body.get_content()
    assert isinstance(content, str)
    return content


def test_output_files_are_what_the_data_mail_contains(
    tmp_path: pathlib.Path, smtp: "FakeSMTP", stored: config.Configuration
) -> None:
    output = tmp_path / "preview"

    assert run(stored, "--output-dir", str(output)) == 0

    assert sorted(path.name for path in output.iterdir()) == ["data-mail.html", "data-mail.txt"]
    # the data collector sends the same day's mail: both parts are the files, line for line
    collector.send_data_mail(stored, stored.data_path, datetime.date.fromisoformat(TODAY))
    (message,) = smtp.messages()
    assert (output / "data-mail.txt").read_text(encoding="utf-8") == text_of(message)
    assert (output / "data-mail.html").read_text(encoding="utf-8") == html_of(message)
    assert "Last week: week 47/2026, 2026-11-16 .. 2026-11-22" in text_of(message)


def test_data_files_are_unchanged_and_the_data_folder_gets_no_file(
    tmp_path: pathlib.Path, smtp: "FakeSMTP", stored: config.Configuration
) -> None:
    before = data_files(stored.data_path)

    assert run(stored) == 0
    assert run(stored, "--output-dir", str(tmp_path / "preview")) == 0
    assert run(stored, "--send-to", "me@example.org") == 0

    assert data_files(stored.data_path) == before
    assert len(before) == 2


def test_nothing_is_written_and_no_mail_is_sent_by_default(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    smtp: "FakeSMTP",
    no_device: list[str],
    stored: config.Configuration,
) -> None:
    folder = tmp_path / "elsewhere"
    folder.mkdir()
    monkeypatch.chdir(folder)
    before = {path.name for path in tmp_path.iterdir()}

    assert run(stored) == 0

    assert {path.name for path in tmp_path.iterdir()} == before
    assert list(folder.iterdir()) == []
    assert smtp.connections == []
    assert no_device == []
    out = capsys.readouterr().out.splitlines()
    assert out[0] == f"[*] data mail for the run on {TODAY} from {stored.data_path}"
    assert out[1].startswith("[*] text: ")
    assert out[2].startswith("[*] html: ")
    assert "characters" in out[2]
    prefix = stored.data_file.prefix
    assert out[3] == f"[*] attachments: {prefix}_2025.csv, {prefix}_2026.csv"
    assert len(out) == 4


def test_send_to_sends_the_mail_to_that_address_only(
    smtp: "FakeSMTP", capsys: pytest.CaptureFixture[str], stored: config.Configuration
) -> None:
    prefix = stored.data_file.prefix

    assert run(stored, "--send-to", "me@example.org") == 0

    (connection,) = smtp.connections
    assert [call[0] for call in connection["calls"]] == [
        "starttls",
        "login",
        "send_message",
        "sendmail",
        "quit",
        "close",
        "exit",
    ]
    (sendmail,) = [call for call in connection["calls"] if call[0] == "sendmail"]
    assert sendmail[1:3] == ("sender@example.com", ["me@example.org"])
    (message,) = smtp.messages()
    assert message["To"] == "me@example.org"
    assert message["From"] == "sender@example.com"
    assert message["Subject"] == f"[preview] {SUBJECT}"
    assert [part.get_filename() for part in message.iter_attachments()] == [
        f"{prefix}_2025.csv",
        f"{prefix}_2026.csv",
    ]
    assert "Last week: week 47/2026, 2026-11-16 .. 2026-11-22" in text_of(message)
    assert "<table" in html_of(message)
    assert f"[*] sent to me@example.org: [preview] {SUBJECT}" in capsys.readouterr().out


def test_send_to_sends_what_the_data_mail_contains(
    smtp: "FakeSMTP", stored: config.Configuration
) -> None:
    assert run(stored, "--send-to", "me@example.org") == 0
    collector.send_data_mail(stored, stored.data_path, datetime.date.fromisoformat(TODAY))

    preview_mail, data_mail = smtp.messages()
    assert text_of(preview_mail) == text_of(data_mail)
    assert html_of(preview_mail) == html_of(data_mail)
    assert data_mail["To"] == "receiver@example.com"
    assert data_mail["Subject"] == SUBJECT


def test_today_moves_the_week(tmp_path: pathlib.Path, stored: config.Configuration) -> None:
    assert run(stored, "--output-dir", str(tmp_path / "monday")) == 0
    assert run(stored, "--output-dir", str(tmp_path / "next"), today="2026-11-30") == 0

    monday = (tmp_path / "monday" / "data-mail.txt").read_text(encoding="utf-8").splitlines()
    following = (tmp_path / "next" / "data-mail.txt").read_text(encoding="utf-8").splitlines()
    assert "Water consumption in liters, run on 2026-11-23" in monday
    assert "Last week: week 47/2026, 2026-11-16 .. 2026-11-22" in monday
    assert "Water consumption in liters, run on 2026-11-30" in following
    assert "Last week: week 48/2026, 2026-11-23 .. 2026-11-29" in following
    assert "  Fri 2026-11-27      310" in following


def test_default_day_is_today(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, stored: config.Configuration
) -> None:
    monkeypatch.setattr(preview, "local_today", lambda: datetime.date(2026, 11, 30))

    assert run(stored, "--output-dir", str(tmp_path), today=None) == 0

    text = (tmp_path / "data-mail.txt").read_text(encoding="utf-8")
    assert "Water consumption in liters, run on 2026-11-30\n" in text


def test_output_dir_is_created(tmp_path: pathlib.Path, stored: config.Configuration) -> None:
    output = tmp_path / "a" / "b"

    assert run(stored, "--output-dir", str(output)) == 0

    assert (output / "data-mail.txt").is_file()


def test_data_mail_without_html_writes_the_text_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
    stored: config.Configuration,
) -> None:
    def fail(stats: report.Report, notes: object) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(report_html, "format_html", fail)

    assert run(stored, "--output-dir", str(tmp_path / "out")) == 0

    assert [path.name for path in (tmp_path / "out").iterdir()] == ["data-mail.txt"]
    captured = capsys.readouterr()
    assert "[*] html: none" in captured.out
    assert "[!] no HTML part was made: data-mail.html is not written" in captured.err


def test_failed_statistics_show_up_as_in_the_data_mail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, stored: config.Configuration
) -> None:
    def fail(*args: object, **kwargs: object) -> typing.NoReturn:
        raise storage.StorageError("bad file")

    monkeypatch.setattr(report, "build_report", fail)

    assert run(stored, "--output-dir", str(tmp_path)) == 0

    text = (tmp_path / "data-mail.txt").read_text(encoding="utf-8")
    assert text == (
        "your stored data\n\nThe statistics could not be calculated: bad file\n"
        "Details are in the log file.\n"
    )


def test_folder_without_csv_files_says_so(
    tmp_path: pathlib.Path, loaded_config: config.Configuration
) -> None:
    loaded_config.data_path.mkdir()

    assert run(loaded_config, "--output-dir", str(tmp_path / "preview")) == 0

    text = (tmp_path / "preview" / "data-mail.txt").read_text(encoding="utf-8")
    assert text.startswith("your stored data\n\nNo data files found to attach.\n")


# --- errors: a message on stderr and exit code 1 -----------------------------------------


def test_missing_configuration_file_exits_with_1(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert preview.main(["-c", str(tmp_path / "missing.json")]) == 1

    assert "[-] no configuration: " in capsys.readouterr().err


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda data: data.pop("dataPath"), id="missing-key"),
        pytest.param(lambda data: data["mail"].update(recipients=[]), id="empty-recipients"),
        pytest.param(lambda data: data.update(dataFile="no object"), id="no-object"),
    ],
)
def test_invalid_configuration_exits_with_1(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
    smtp: "FakeSMTP",
    write_config: collections.abc.Callable[..., pathlib.Path],
    config_data: dict[str, typing.Any],
    mutate: collections.abc.Callable[[dict[str, typing.Any]], object],
) -> None:
    mutate(config_data)
    config_file = write_config(config_data)

    assert preview.main(["-c", str(config_file), "--output-dir", str(tmp_path / "out")]) == 1

    assert "[-] invalid configuration: " in capsys.readouterr().err
    assert not (tmp_path / "out").exists()
    assert smtp.connections == []


def without_password(
    configuration: config.Configuration,
    write_config: collections.abc.Callable[..., pathlib.Path],
    config_data: dict[str, typing.Any],
) -> config.Configuration:
    """the configuration of the tests without senderPassword and without a credential"""
    del config_data["mail"]["senderPassword"]
    return dataclasses.replace(configuration, file=write_config(config_data))


def test_output_needs_no_password(
    tmp_path: pathlib.Path,
    smtp: "FakeSMTP",
    stored: config.Configuration,
    write_config: collections.abc.Callable[..., pathlib.Path],
    config_data: dict[str, typing.Any],
) -> None:
    open_config = without_password(stored, write_config, config_data)

    assert run(open_config, "--output-dir", str(tmp_path / "out")) == 0

    assert (tmp_path / "out" / "data-mail.txt").exists()
    assert smtp.connections == []


def test_send_to_needs_the_password(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
    smtp: "FakeSMTP",
    stored: config.Configuration,
    write_config: collections.abc.Callable[..., pathlib.Path],
    config_data: dict[str, typing.Any],
) -> None:
    open_config = without_password(stored, write_config, config_data)

    assert run(open_config, "--send-to", "me@example.com") == 1

    err = capsys.readouterr().err
    assert "[-] invalid configuration: no SMTP password: " in err
    assert smtp.connections == []


def test_unreadable_configuration_file_exits_with_1(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    assert preview.main(["-c", str(config_file)]) == 1

    assert "[-] invalid configuration: " in capsys.readouterr().err


def test_missing_data_folder_exits_with_1_and_is_not_created(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str], loaded_config: config.Configuration
) -> None:
    assert not loaded_config.data_path.exists()

    assert run(loaded_config, "--output-dir", str(tmp_path / "out")) == 1

    assert "[-] data folder does not exist or is not a directory: " in capsys.readouterr().err
    assert not loaded_config.data_path.exists()
    assert not (tmp_path / "out").exists()


def test_failed_sending_exits_with_1(
    capsys: pytest.CaptureFixture[str], smtp: "FakeSMTP", stored: config.Configuration
) -> None:
    smtp.errors.append(("login", smtplib.SMTPAuthenticationError(535, b"bad credentials")))

    assert run(stored, "--send-to", "me@example.org") == 1

    captured = capsys.readouterr()
    assert "[-] sending the mail failed: Authentication failed: " in captured.err
    assert "[*] sent to" not in captured.out


def test_invalid_address_exits_with_1(
    capsys: pytest.CaptureFixture[str], smtp: "FakeSMTP", stored: config.Configuration
) -> None:
    assert run(stored, "--send-to", "me@example.org\nBcc: other@example.org") == 1

    assert "[-] sending the mail failed: Cannot build the email: " in capsys.readouterr().err
    assert smtp.connections == []


def test_output_dir_that_is_a_file_exits_with_1(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str], stored: config.Configuration
) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("not a folder", encoding="utf-8")

    assert run(stored, "--output-dir", str(blocker)) == 1

    assert f"[-] cannot write the mail into {blocker}: " in capsys.readouterr().err
    assert blocker.read_text(encoding="utf-8") == "not a folder"


@pytest.mark.parametrize(
    "options",
    [
        ["--today", "2026-13-01"],
        ["--today", "yesterday"],
        ["--send-to", "  "],
        # the charts are gone from the data mail (P012-S1), and so is their option
        ["--charts", "inline"],
    ],
)
def test_invalid_options_are_a_usage_error(options: list[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        preview.main(options)

    assert exit_info.value.code == 2
