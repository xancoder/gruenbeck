"""
the run of the data collector: request the device, store the new values in the yearly
files, compose and send the data mail with the statistics

The errors are raised to gruenbeck.cli, which logs them, sends the error mail and sets the
exit code; only the statistics and the HTML of the data mail catch their own failures,
because the data is stored already when they are made (see get_statistics()).
"""

import dataclasses
import datetime
import logging
import pathlib
from collections.abc import Callable, Sequence

from gruenbeck import config as configuration
from gruenbeck import (
    device,
    errors,
    mail,
    report,
    report_html,
    report_text,
    storage,
)

logger = logging.getLogger(__name__)

ONE_DAY = datetime.timedelta(days=1)
DATA_MAIL_TEXT = "your stored data"
NO_DATA_FILES_TEXT = "No data files found to attach."
STATISTICS_FAILED_TEXT = (
    "The statistics could not be calculated: {error}\nDetails are in the log file."
)


class CollectError(errors.GruenbeckError):
    """the new values are not stored (none left, or they differ from the stored ones)"""


@dataclasses.dataclass(frozen=True)
class CollectResult:
    """what the data collector stored"""

    data_path: pathlib.Path
    """the data folder"""
    today: datetime.date
    """the day of the run: the values were stored under it (the only call of local_now)"""


def collect_and_store(config: configuration.Configuration) -> CollectResult:
    """
    request the device and store the new values in the yearly files

    The time of the run is taken once, after the response of the device (the request can
    take minutes with retries); the day of the run is part of the result, so the statistics
    of the data mail are calculated for the day the values were stored under.
    :return: the data folder and the day of the run
    :raises errors.GruenbeckError: the run fails; nothing is written then
    """
    data_path = get_data_folder(config)
    data_file = config.data_file
    water_system = config.soft_water_system
    device_data = device.get_device_data(
        water_system.host,
        water_system.timeout,
        water_system.retries,
        water_system.retry_delay,
    )
    now = local_now()
    device.check_device_clock(device_data.pop(device.DEVICE_CLOCK_PARAMETER, None), now)
    # checks every value before anything is written
    new_values = filter_first_date(
        device.read_consumption(device_data, today=now.date()), data_file.first_date
    )

    # read every yearly file involved (also the one of the day before the oldest new
    # value, see check_stored_overlap) before anything is written
    years = sorted({day.year for day in new_values})
    years_to_read = set(years)
    if new_values:
        years_to_read.add((min(new_values) - ONE_DAY).year)
    try:
        stored_by_year = {
            year: storage.read_data_file(
                storage.get_data_file(data_path, data_file.prefix, year),
                data_file.fieldnames,
                data_file.date_pattern,
            )
            for year in sorted(years_to_read)
        }
    except storage.StorageError as err:
        raise storage.StorageError(f"{err}: nothing written") from err
    check_stored_overlap(
        new_values,
        {day: value for values in stored_by_year.values() for day, value in values.items()},
        data_file.date_pattern,
    )

    # provides files per year and handle year change
    for year in years:
        data_existing = dict(stored_by_year[year])
        data_existing.update(
            {
                day.strftime(data_file.date_pattern): value
                for day, value in sorted(new_values.items())
                if day.year == year
            }
        )
        storage.write_data(
            storage.get_data_file(data_path, data_file.prefix, year),
            data_file.fieldnames,
            data_existing,
            data_file.date_pattern,
        )
    return CollectResult(data_path, now.date())


def get_data_folder(config: configuration.Configuration) -> pathlib.Path:
    """
    :raises storage.StorageError: the data folder cannot be created
    """
    try:
        return storage.check_data_folder(config.data_path)
    except OSError as err:
        raise storage.StorageError(f"creation data folder failed: {err}") from err


def local_now() -> datetime.datetime:
    """current local time of the run"""
    return datetime.datetime.now()


def filter_first_date[V](
    device_data: dict[datetime.date, V], first_date: datetime.date | None
) -> dict[datetime.date, V]:
    """
    drop the values of days before dataFile.firstDate
    :param device_data: dictionary of datetime.date and value
    :param first_date: datetime.date, or None for no limit
    :return: dictionary of the remaining datetime.date and value
    :raises CollectError: every value is before first_date
    """
    if first_date is None:
        return device_data
    result = {day: value for day, value in device_data.items() if day >= first_date}
    skipped = len(device_data) - len(result)
    if skipped:
        logger.info("%d values before dataFile.firstDate %s are not written", skipped, first_date)
    if device_data and not result:
        raise CollectError(
            f"no data was processed: all {skipped} values are before"
            f" dataFile.firstDate {first_date}"
        )
    return result


def check_stored_overlap(
    new_values: dict[datetime.date, int], stored: dict[str, int | str], date_pattern: str
) -> None:
    """
    compare the new values with the days that are stored already

    Values of past days do not change on the device. If a stored day gets another
    value, the run writes nothing: either the run was before the daily rollover of the
    device (every new value equals the stored value of the day before) or the data
    files and the device disagree.
    :param new_values: dictionary of datetime.date and value (int)
    :param stored: dictionary of date text and stored value of all files involved
    :param date_pattern: dataFile.datePattern, the format of the date texts
    :raises CollectError: a stored day gets another value
    """
    overlap = [day for day in sorted(new_values) if day.strftime(date_pattern) in stored]
    differing = [day for day in overlap if stored[day.strftime(date_pattern)] != new_values[day]]
    if not differing:
        return
    with_day_before = [day for day in overlap if (day - ONE_DAY).strftime(date_pattern) in stored]
    if with_day_before and all(
        stored[(day - ONE_DAY).strftime(date_pattern)] == new_values[day] for day in with_day_before
    ):
        raise CollectError(
            "one day late: the run was probably before the daily rollover of the"
            " device; run again later (the new values of"
            f" {with_day_before[0]} ... {with_day_before[-1]} equal the stored values"
            " of the day before; nothing written)"
        )
    details = ", ".join(
        f"{day}: stored {stored[day.strftime(date_pattern)]}, new {new_values[day]}"
        for day in differing
    )
    raise CollectError(
        f"the new values differ from the stored ones ({details}): nothing written;"
        " check the data files and the device"
    )


@dataclasses.dataclass(frozen=True)
class DataMail:
    """the data mail as it goes out, before it is sent"""

    text: str
    html: str | None
    """the HTML document, None if it could not be made (the mail has the text only)"""
    files: tuple[pathlib.Path, ...]
    """the csv files to attach"""


def compose_data_mail(
    config: configuration.Configuration, data_path: pathlib.Path, today: datetime.date
) -> DataMail:
    """
    make the data mail from the csv files of the data folder and the statistics

    Only reads the data folder: nothing is written and nothing is sent. The statistics
    never fail the mail, see get_statistics().
    :param today: day of the run, for the statistics
    :raises storage.StorageError: the data folder does not exist or is not a folder
    """
    files = storage.list_csv_files(data_path)
    notes = [] if files else [NO_DATA_FILES_TEXT]
    statistics = get_statistics(config, data_path, today, notes)
    text = "\n\n".join([DATA_MAIL_TEXT, *notes, statistics.text])
    return DataMail(text, statistics.html, tuple(files))


def send_data_mail(
    config: configuration.Configuration, data_path: pathlib.Path, today: datetime.date
) -> None:
    """
    send the csv files of the data folder as data mail, with the statistics as text and HTML
    :param today: day of the run, for the statistics
    :raises storage.StorageError: the data folder does not exist or is not a folder
    :raises mail.MailError: the mail cannot be built or sent; an unexpected error becomes an
        unexpected MailError (MailError.unexpected) with the error as its cause
    """
    try:
        data_mail = compose_data_mail(config, data_path, today)
        mail.send_mail(
            config.mail,
            config.mail.subject,
            data_mail.text,
            data_mail.files,
            html=data_mail.html,
        )
    except errors.GruenbeckError:
        raise
    except Exception as error:
        raise mail.MailError(
            f"unexpected error: {type(error).__name__}: {error}", unexpected=True
        ) from error
    logger.info("mail sent successfully")


@dataclasses.dataclass(frozen=True)
class Statistics:
    """the statistics for the data mail: the text, and the HTML document (None if not made)"""

    text: str
    html: str | None


def get_statistics(
    config: configuration.Configuration,
    data_path: pathlib.Path,
    today: datetime.date,
    notes: Sequence[str] = (),
) -> Statistics:
    """
    the statistics of the stored data for the data mail, as text and as HTML

    The data is stored already and the data mail has to go out, so nothing here fails the
    run; every failure is logged as a warning with its traceback:

    - the statistics cannot be calculated (an unusable data file, a bug): a note takes
      their place in the text and in the HTML
    - the HTML cannot be made: the mail has the text only

    :param notes: texts for the top of the HTML (the text gets them from the caller)
    """
    try:
        stats = report.build_report(data_path, config.data_file, today)
        text = report_text.format_text(stats)
    except Exception as error:
        logger.warning("statistics for the data mail failed: %s", error, exc_info=True)
        note = STATISTICS_FAILED_TEXT.format(error=error)
        return Statistics(note, _make_html(lambda: report_html.format_failure_html(note, notes)))
    return Statistics(text, _make_html(lambda: report_html.format_html(stats, notes)))


def _make_html(build: Callable[[], str]) -> str | None:
    try:
        return build()
    except Exception as error:
        logger.warning("HTML part of the data mail failed: %s", error, exc_info=True)
        return None
