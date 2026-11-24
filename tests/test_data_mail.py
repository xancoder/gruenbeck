"""
the data mail with the statistics (P007-S2): text and attachments over a fake SMTP server,
and the run when the statistics cannot be calculated
"""

import datetime
import email.message
import logging
import pathlib
import typing

import pytest

from gruenbeck import cli, config, report, storage

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

    assert cli.get_mail(loaded_config, loaded_config.data_path, TODAY) is True

    text, attachments = sent(smtp)
    assert text.startswith("your stored data\n\nWater consumption in liters, run on 2026-11-23\n")
    lines = text.splitlines()
    assert "Last week: week 47/2026, 2026-11-16 .. 2026-11-22" in lines
    assert "  Fri 2026-11-20      300" in lines
    assert "2026  11-16..11-22     1100     157     90 11-21    300 11-20" in lines
    assert "2025  11-17..11-23      350      50     50 11-17     50 11-17" in lines
    assert attachments == [f"{prefix}_2025.csv", f"{prefix}_2026.csv"]
    assert warnings() == []


def test_data_mail_marks_interpolated_and_missing_days(
    smtp: "FakeSMTP", loaded_config: config.Configuration
) -> None:
    # Tuesday is no number: interpolated; Thursday to Sunday have no value: missing
    write_year(loaded_config, 2026, week_rows(100, "-", 300))

    assert cli.get_mail(loaded_config, loaded_config.data_path, TODAY) is True

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

    assert cli.get_mail(loaded_config, loaded_config.data_path, TODAY) is True

    text, _ = sent(smtp)
    assert text.count("No earlier year has values for this period.") == 4
    assert "No earlier year has values.\n" in text


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

    assert cli.get_mail(loaded_config, loaded_config.data_path, TODAY) is True

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


def test_unexpected_error_of_the_statistics_gives_the_note_too(
    monkeypatch: pytest.MonkeyPatch,
    smtp: "FakeSMTP",
    warnings: typing.Callable[[], list[logging.LogRecord]],
    loaded_config: config.Configuration,
) -> None:
    write_year(loaded_config, 2026, week_rows(100))

    def fail(report_: report.Report) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(report, "format_text", fail)

    assert cli.get_mail(loaded_config, loaded_config.data_path, TODAY) is True

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
    monkeypatch.setattr(cli, "collect_and_store", lambda config: loaded_config.data_path)
    monkeypatch.setattr(
        cli, "local_now", lambda: datetime.datetime.combine(TODAY, datetime.time(16, 0))
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
    monkeypatch.setattr(cli, "collect_and_store", lambda config: loaded_config.data_path)
    # Thursday: the week of the statistics is the one before the week of the run
    monkeypatch.setattr(
        cli,
        "local_now",
        lambda: datetime.datetime.combine(datetime.date(2026, 11, 26), datetime.time(16, 0)),
    )

    assert cli.main(str(loaded_config.file)) == 0

    text, _ = sent(smtp)
    assert "Water consumption in liters, run on 2026-11-26\n" in text
    assert "Last week: week 47/2026, 2026-11-16 .. 2026-11-22" in text.splitlines()
