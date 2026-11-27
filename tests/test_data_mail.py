"""
the data mail with the statistics (P007-S2, P007-S4, P012-S1): text, HTML and attachments
over a fake SMTP server, and the run when a part of it cannot be made
"""

import collections.abc
import datetime
import email.message
import logging
import pathlib
import re
import typing

import pytest

from gruenbeck import (
    cli,
    collector,
    config,
    device,
    report,
    report_html,
    report_text,
    storage,
)

if typing.TYPE_CHECKING:
    from conftest import FakeSMTP

TODAY = datetime.date(2026, 11, 23)
STATISTICS_FAILED = "The statistics could not be calculated: "


def write_year(
    configuration: config.Configuration, year: int, rows: dict[str, int | str]
) -> pathlib.Path:
    folder = storage.check_data_folder(configuration.data_path)
    data_file = configuration.data_file
    path = storage.get_data_file(folder, data_file.prefix, year)
    storage.write_data(path, data_file.fieldnames, rows, data_file.date_pattern)
    return path


def week_rows(*values: int | str, first: str = "2026-11-16") -> dict[str, int | str]:
    start = datetime.date.fromisoformat(first)
    return {
        (start + datetime.timedelta(days=offset)).isoformat(): value
        for offset, value in enumerate(values)
    }


def sent(smtp: "FakeSMTP") -> tuple[str, list[str]]:
    """the text of the only mail sent and the names of its attachments"""
    (message,) = smtp.messages()
    body = message.get_body(preferencelist=("plain",))
    assert isinstance(body, email.message.EmailMessage)
    return body.get_content(), [part.get_filename() or "" for part in message.iter_attachments()]


def html_of(smtp: "FakeSMTP") -> str:
    """the HTML part of the only mail sent"""
    (message,) = smtp.messages()
    body = message.get_body(preferencelist=("html",))
    assert isinstance(body, email.message.EmailMessage)
    assert body.get_content_type() == "text/html"
    content = body.get_content()
    assert isinstance(content, str)
    return content


@pytest.fixture
def warnings(caplog: pytest.LogCaptureFixture) -> typing.Callable[[], list[logging.LogRecord]]:
    """the warnings and errors logged by the package"""
    caplog.set_level(logging.INFO, logger=cli.package_logger.name)

    def records() -> list[logging.LogRecord]:
        return [record for record in caplog.records if record.levelno >= logging.WARNING]

    return records


def test_data_mail_has_the_statistics_in_the_text_and_the_csv_files_attached(
    smtp: "FakeSMTP",
    warnings: typing.Callable[[], list[logging.LogRecord]],
    loaded_config: config.Configuration,
) -> None:
    prefix = loaded_config.data_file.prefix
    write_year(loaded_config, 2025, week_rows(50, 50, 50, 50, 50, 50, 50, first="2025-11-17"))
    write_year(loaded_config, 2026, week_rows(100, 200, 150, 120, 300, 90, 140))

    collector.send_data_mail(loaded_config, loaded_config.data_path, TODAY)

    text, attachments = sent(smtp)
    assert text.startswith("your stored data\n\nWater consumption in liters, run on 2026-11-23\n")
    lines = text.splitlines()
    assert "Last week: week 47/2026, 2026-11-16 .. 2026-11-22" in lines
    assert "  Fri 2026-11-20      300" in lines
    assert "2026  11-16..11-22     1100     157     90 11-21    300 11-20" in lines
    assert "2025  11-17..11-23      350      50     50 11-17     50 11-17" in lines
    assert attachments == [f"{prefix}_2025.csv", f"{prefix}_2026.csv"]
    assert warnings() == []


def test_composing_the_data_mail_sends_and_writes_nothing(
    smtp: "FakeSMTP", loaded_config: config.Configuration
) -> None:
    path = write_year(loaded_config, 2026, week_rows(100, 200, 150, 120, 300, 90, 140))
    before = path.read_bytes()

    data_mail = collector.compose_data_mail(loaded_config, loaded_config.data_path, TODAY)

    assert data_mail.files == (path,)
    assert data_mail.text.startswith(
        "your stored data\n\nWater consumption in liters, run on 2026-11-23\n"
    )
    assert data_mail.html is not None
    assert data_mail.html.startswith("<!DOCTYPE html>")
    assert smtp.connections == []
    assert path.read_bytes() == before
    assert list(loaded_config.data_path.iterdir()) == [path]


def test_composing_the_data_mail_without_data_folder_fails(
    tmp_path: pathlib.Path, loaded_config: config.Configuration
) -> None:
    folder = tmp_path / "missing"

    with pytest.raises(storage.StorageError, match="data folder does not exist"):
        collector.compose_data_mail(loaded_config, folder, TODAY)

    assert not folder.exists()


def test_data_mail_marks_interpolated_and_missing_days(
    smtp: "FakeSMTP", loaded_config: config.Configuration
) -> None:
    # Tuesday is no number: interpolated; Thursday to Sunday have no value: missing
    write_year(loaded_config, 2026, week_rows(100, "-", 300))

    collector.send_data_mail(loaded_config, loaded_config.data_path, TODAY)

    text, _ = sent(smtp)
    lines = text.splitlines()
    assert "  Tue 2026-11-17      200*" in lines
    assert "  Thu 2026-11-19        -   missing" in lines
    assert "  Sun 2026-11-22        -   missing" in lines
    assert "2026  11-16..11-22      600*    200    100 11-16    300 11-18" in lines
    assert "      incomplete: 4 days missing" in lines
    assert "* includes interpolated days: a gap of up to 3 days between measured days is" in lines


def test_data_mail_without_an_earlier_year_says_so(
    smtp: "FakeSMTP", loaded_config: config.Configuration
) -> None:
    write_year(loaded_config, 2026, week_rows(100, 100, 100, 100, 100, 100, 100))

    collector.send_data_mail(loaded_config, loaded_config.data_path, TODAY)

    text, _ = sent(smtp)
    assert text.count("No earlier year has enough values for this period.") == 4
    assert "No earlier year has enough values.\n" in text


def test_data_mail_with_a_long_history_compares_with_the_latest_five_years(
    smtp: "FakeSMTP", loaded_config: config.Configuration
) -> None:
    for year in range(2017, 2027):
        last = datetime.date(2026, 11, 22) if year == 2026 else datetime.date(year, 12, 31)
        first = datetime.date(year, 1, 1)
        days = (last - first).days + 1
        write_year(
            loaded_config,
            year,
            {(first + datetime.timedelta(days=n)).isoformat(): 100 for n in range(days)},
        )

    collector.send_data_mail(loaded_config, loaded_config.data_path, TODAY)

    text, attachments = sent(smtp)
    years = re.findall(r"^(\d{4})  \d\d-\d\d\.\.", text, flags=re.MULTILINE)
    # four tables with the year of the run and five earlier years, the years as a whole with five
    assert years == ["2026", "2025", "2024", "2023", "2022", "2021"] * 4 + [
        "2025",
        "2024",
        "2023",
        "2022",
        "2021",
    ]
    assert " ".join(text.split()).count("4 earlier years are not shown (") == 5
    assert html_of(smtp).count("4 earlier years are not shown (") == 5
    # the data files of all years are still attached
    assert len(attachments) == 10


def test_data_mail_with_a_superscript_in_a_data_file_has_a_missing_day(
    smtp: "FakeSMTP",
    warnings: typing.Callable[[], list[logging.LogRecord]],
    loaded_config: config.Configuration,
) -> None:
    # "\u00b2" is no number for int(): the day is missing, the statistics are made as usual
    write_year(loaded_config, 2026, week_rows(100, 200, 150, 120, 300, 90, "\u00b2"))

    collector.send_data_mail(loaded_config, loaded_config.data_path, TODAY)

    text, attachments = sent(smtp)
    lines = text.splitlines()
    assert "  Sun 2026-11-22        -   missing" in lines
    assert "      incomplete: 1 day missing" in lines
    assert STATISTICS_FAILED not in text
    assert len(attachments) == 1
    assert warnings() == []


def test_unusable_data_file_gives_a_note_instead_of_the_statistics(
    smtp: "FakeSMTP",
    warnings: typing.Callable[[], list[logging.LogRecord]],
    loaded_config: config.Configuration,
) -> None:
    prefix = loaded_config.data_file.prefix
    write_year(loaded_config, 2026, week_rows(100, 200, 150, 120, 300, 90, 140))
    # a file of an earlier year that the collector does not read, but the statistics do
    old_file = storage.get_data_file(loaded_config.data_path, prefix, 2024)
    old_file.write_text("day,litres\n2024-11-18,5\n", encoding="utf-8")

    collector.send_data_mail(loaded_config, loaded_config.data_path, TODAY)

    text, attachments = sent(smtp)
    assert text.startswith(
        f"your stored data\n\n{STATISTICS_FAILED}{old_file} has no column 'date'"
    )
    assert text.endswith("\nDetails are in the log file.\n")
    assert "Water consumption" not in text
    # the csv files are attached as usual
    assert attachments == [f"{prefix}_2024.csv", f"{prefix}_2026.csv"]
    (record,) = warnings()
    assert record.levelno == logging.WARNING
    assert record.getMessage().startswith("statistics for the data mail failed: ")
    assert record.exc_info is not None
    assert record.exc_info[0] is storage.StorageError


def test_data_file_with_a_row_without_value_gives_the_note(
    smtp: "FakeSMTP",
    warnings: typing.Callable[[], list[logging.LogRecord]],
    loaded_config: config.Configuration,
) -> None:
    write_year(loaded_config, 2026, week_rows(100, 200, 150, 120, 300, 90, 140))
    old_file = storage.get_data_file(loaded_config.data_path, loaded_config.data_file.prefix, 2024)
    old_file.write_text("date,value\n2024-11-18,5\n2024-11-19\n", encoding="utf-8")

    collector.send_data_mail(loaded_config, loaded_config.data_path, TODAY)

    text, _ = sent(smtp)
    assert text.startswith(
        f"your stored data\n\n{STATISTICS_FAILED}{old_file}, line 3: no value in the column"
        " 'value'\n"
    )
    (record,) = warnings()
    assert record.exc_info is not None
    assert record.exc_info[0] is storage.StorageError


def test_unexpected_error_of_the_statistics_gives_the_note_too(
    monkeypatch: pytest.MonkeyPatch,
    smtp: "FakeSMTP",
    warnings: typing.Callable[[], list[logging.LogRecord]],
    loaded_config: config.Configuration,
) -> None:
    write_year(loaded_config, 2026, week_rows(100))

    def fail(report_: report.Report) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(report_text, "format_text", fail)

    collector.send_data_mail(loaded_config, loaded_config.data_path, TODAY)

    text, attachments = sent(smtp)
    assert text == f"your stored data\n\n{STATISTICS_FAILED}boom\nDetails are in the log file.\n"
    assert attachments == [f"{loaded_config.data_file.prefix}_2026.csv"]
    (record,) = warnings()
    assert record.exc_info is not None
    assert record.exc_info[0] is RuntimeError


def test_failed_statistics_do_not_fail_the_run(
    monkeypatch: pytest.MonkeyPatch,
    smtp: "FakeSMTP",
    warnings: typing.Callable[[], list[logging.LogRecord]],
    loaded_config: config.Configuration,
) -> None:
    write_year(loaded_config, 2026, week_rows(100, 200, 150, 120, 300, 90, 140))

    def fail(
        data_path: pathlib.Path, data_file: config.DataFile, today: datetime.date
    ) -> typing.NoReturn:
        raise storage.StorageError("bad file")

    # the collector part of the run is not under test: the data is stored already
    monkeypatch.setattr(
        collector,
        "collect_and_store",
        lambda config: collector.CollectResult(loaded_config.data_path, TODAY),
    )
    monkeypatch.setattr(report, "build_report", fail)

    assert cli.main(str(loaded_config.file)) == 0

    text, attachments = sent(smtp)
    assert (
        text == f"your stored data\n\n{STATISTICS_FAILED}bad file\nDetails are in the log file.\n"
    )
    assert len(attachments) == 1
    assert [record.getMessage() for record in warnings()] == [
        "statistics for the data mail failed: bad file"
    ]


def test_run_calculates_the_statistics_for_the_day_of_the_run(
    monkeypatch: pytest.MonkeyPatch, smtp: "FakeSMTP", loaded_config: config.Configuration
) -> None:
    write_year(loaded_config, 2026, week_rows(100, 200, 150, 120, 300, 90, 140))
    # Thursday: the week of the statistics is the one before the week of the run
    thursday = datetime.date(2026, 11, 26)
    monkeypatch.setattr(
        collector,
        "collect_and_store",
        lambda config: collector.CollectResult(loaded_config.data_path, thursday),
    )

    assert cli.main(str(loaded_config.file)) == 0

    text, _ = sent(smtp)
    assert "Water consumption in liters, run on 2026-11-26\n" in text
    assert "Last week: week 47/2026, 2026-11-16 .. 2026-11-22" in text.splitlines()


def test_run_past_midnight_calculates_the_statistics_for_the_day_of_the_stored_values(
    monkeypatch: pytest.MonkeyPatch,
    smtp: "FakeSMTP",
    warnings: typing.Callable[[], list[logging.LogRecord]],
    loaded_config: config.Configuration,
) -> None:
    monday = datetime.datetime(2026, 11, 23, 23, 59)
    tuesday = datetime.datetime(2026, 11, 24, 0, 1)
    calls: list[datetime.datetime] = []

    def now() -> datetime.datetime:
        # the first call is before midnight, every further call after it
        calls.append(monday if not calls else tuesday)
        return calls[-1]

    def fetch(
        host: str,
        parameters: collections.abc.Iterable[str],
        timeout: float,
        session: object = None,
    ) -> dict[str, str | None]:
        return {"D_C_4_2": "23:59", **{f"D_Y_2_{place}": "100" for place in range(1, 15)}}

    monkeypatch.setattr(device, "get_data_from_mux_http", fetch)
    monkeypatch.setattr(collector, "local_now", now)

    assert cli.main(str(loaded_config.file)) == 0

    # the time of the run is taken once, so the statistics cannot get another day
    assert len(calls) == 1
    text, attachments = sent(smtp)
    assert "Water consumption in liters, run on 2026-11-23\n" in text
    assert "2026-11-24" not in text
    # the values are stored under the day before Monday, the last one is the Sunday
    stored = storage.read_data_file(
        storage.get_data_file(loaded_config.data_path, loaded_config.data_file.prefix, monday.year),
        loaded_config.data_file.fieldnames,
        loaded_config.data_file.date_pattern,
    )
    assert max(stored) == "2026-11-22"
    assert len(attachments) == 1
    assert warnings() == []


# --- HTML part (P007-S4, P012-S1) --------------------------------------------------------


def test_data_mail_is_text_and_html_without_images_and_the_csv_files(
    smtp: "FakeSMTP",
    warnings: typing.Callable[[], list[logging.LogRecord]],
    loaded_config: config.Configuration,
) -> None:
    prefix = loaded_config.data_file.prefix
    write_year(loaded_config, 2025, week_rows(50, 50, 50, 50, 50, 50, 50, first="2025-11-17"))
    write_year(loaded_config, 2026, week_rows(100, 200, 150, 120, 300, 90, 140))

    collector.send_data_mail(loaded_config, loaded_config.data_path, TODAY)

    (message,) = smtp.messages()
    assert message.get_content_type() == "multipart/mixed"
    alternative, *attachments = message.iter_parts()
    assert alternative.get_content_type() == "multipart/alternative"
    assert [part.get_content_type() for part in alternative.iter_parts()] == [
        "text/plain",
        "text/html",
    ]
    text, document = (part.get_content() for part in alternative.iter_parts())
    # the text as before; the HTML has the same tables
    assert text.startswith("your stored data\n\nWater consumption in liters, run on 2026-11-23\n")
    assert "2026  11-16..11-22     1100     157     90 11-21    300 11-20" in text.splitlines()
    assert document.startswith("<!DOCTYPE html>")
    assert re.findall(r"<td [^>]*>1100</td>", document)
    # no chart (P012-S1): no SVG, no image and no address of an external resource
    assert "<svg" not in document
    assert "<img" not in document
    assert "http" not in document
    assert [part.get_content_maintype() for part in message.walk()] == [
        "multipart",
        "multipart",
        "text",
        "text",
        "application",
        "application",
    ]
    assert [part.get_filename() for part in attachments] == [
        f"{prefix}_2025.csv",
        f"{prefix}_2026.csv",
    ]
    assert warnings() == []


def test_failed_statistics_give_a_note_in_the_html_too(
    monkeypatch: pytest.MonkeyPatch,
    smtp: "FakeSMTP",
    warnings: typing.Callable[[], list[logging.LogRecord]],
    loaded_config: config.Configuration,
) -> None:
    write_year(loaded_config, 2026, week_rows(100, 200, 150, 120, 300, 90, 140))

    def fail(
        data_path: pathlib.Path, data_file: config.DataFile, today: datetime.date
    ) -> typing.NoReturn:
        raise storage.StorageError('bad <file> & "x"')

    monkeypatch.setattr(report, "build_report", fail)

    collector.send_data_mail(loaded_config, loaded_config.data_path, TODAY)

    (message,) = smtp.messages()
    assert message.get_content_type() == "multipart/mixed"
    text, _ = (part.get_content() for part in next(message.iter_parts()).iter_parts())
    document = html_of(smtp)
    failed = f'{STATISTICS_FAILED}bad <file> & "x"\nDetails are in the log file.'
    assert text == f"your stored data\n\n{failed}\n"
    # in the HTML the special characters of the message are escaped, and there is no statistics
    assert "bad &lt;file&gt; &amp; &quot;x&quot;<br>Details are in the log file." in document
    assert "<file>" not in document
    assert "<h2" not in document
    assert len(list(message.iter_attachments())) == 1
    (record,) = warnings()
    assert record.getMessage() == 'statistics for the data mail failed: bad <file> & "x"'
    assert record.exc_info is not None
    assert record.exc_info[0] is storage.StorageError


def test_special_characters_of_a_data_file_name_are_escaped_in_the_html(
    smtp: "FakeSMTP",
    tmp_path: pathlib.Path,
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
) -> None:
    config_data["dataFile"]["prefix"] = "w&<b>"
    configuration = config.load_configuration(write_config(config_data))
    write_year(configuration, 2026, week_rows(100, 200, 150, 120, 300, 90, 140))
    bad_file = storage.get_data_file(configuration.data_path, "w&<b>", 2024)
    bad_file.write_text("day,litres\n2024-11-18,5\n", encoding="utf-8")

    collector.send_data_mail(configuration, configuration.data_path, TODAY)

    text, _ = sent(smtp)
    document = html_of(smtp)
    assert f"{bad_file} has no column" in text
    assert str(bad_file).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") in document
    assert "w&<b>" not in document


def test_failed_html_leaves_the_mail_with_the_text(
    monkeypatch: pytest.MonkeyPatch,
    smtp: "FakeSMTP",
    warnings: typing.Callable[[], list[logging.LogRecord]],
    loaded_config: config.Configuration,
) -> None:
    write_year(loaded_config, 2026, week_rows(100, 200, 150, 120, 300, 90, 140))

    def fail(*arguments: object) -> str:
        raise RuntimeError("no html")

    monkeypatch.setattr(report_html, "format_html", fail)

    collector.send_data_mail(loaded_config, loaded_config.data_path, TODAY)

    (message,) = smtp.messages()
    # the text and the attachment, without a multipart/alternative
    assert message.get_content_type() == "multipart/mixed"
    first, attachment = message.iter_parts()
    assert first.get_content_type() == "text/plain"
    assert first.get_content().startswith("your stored data\n\nWater consumption in liters")
    assert attachment.get_filename() == f"{loaded_config.data_file.prefix}_2026.csv"
    (record,) = warnings()
    assert record.getMessage() == "HTML part of the data mail failed: no html"
    assert record.exc_info is not None


def test_failed_statistics_and_failed_note_leave_the_note_in_the_text(
    monkeypatch: pytest.MonkeyPatch,
    smtp: "FakeSMTP",
    warnings: typing.Callable[[], list[logging.LogRecord]],
    loaded_config: config.Configuration,
) -> None:
    def fail(*arguments: object) -> typing.NoReturn:
        raise RuntimeError("boom")

    monkeypatch.setattr(report, "build_report", fail)
    monkeypatch.setattr(report_html, "format_failure_html", fail)
    storage.check_data_folder(loaded_config.data_path)

    collector.send_data_mail(loaded_config, loaded_config.data_path, TODAY)

    (message,) = smtp.messages()
    # no csv file and no HTML: a plain text mail
    assert message.get_content_type() == "text/plain"
    assert message.get_content() == (
        "your stored data\n\nNo data files found to attach.\n\n"
        f"{STATISTICS_FAILED}boom\nDetails are in the log file.\n"
    )
    assert [record.getMessage() for record in warnings()] == [
        "statistics for the data mail failed: boom",
        "HTML part of the data mail failed: boom",
    ]
