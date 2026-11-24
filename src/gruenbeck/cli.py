"""
commands of the package: gruenbeck-collect (data collector) and gruenbeck-analyse

Only this module catches the errors of the package (gruenbeck.errors.GruenbeckError and
its subclasses), sends the error mail and sets the exit code; only this module configures
the logging handlers.
"""

import argparse
import datetime
import logging.handlers
import os
import pathlib
import sys
import traceback
from collections.abc import Sequence

from gruenbeck import analysis, device, errors, mail, storage
from gruenbeck import config as configuration

# the handlers of setup_logging() sit on the logger of the package, so they also get the
# messages of the other modules (gruenbeck.config, gruenbeck.device, gruenbeck.storage)
package_logger = logging.getLogger("gruenbeck")
logger = logging.getLogger(__name__)

# create logging formatter
formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S"
)

ONE_DAY = datetime.timedelta(days=1)
ERROR_MAIL_SUBJECT = "gruenbeck data collector failure"
DATA_MAIL_TEXT = "your stored data"
NO_DATA_FILES_TEXT = "No data files found to attach."


class CollectError(errors.GruenbeckError):
    """the new values are not stored (none left, or they differ from the stored ones)"""


def setup_logging(
    log_console: bool = False, log_file: str | os.PathLike[str] = "./log/gruenbeck_error.log"
) -> list[logging.Handler]:
    """
    attach the handlers to the logger of the package and let it pass INFO and above

    The rotating file takes warnings as well as errors: scheduled runs (systemd timer,
    cron) have no console, so a warning would be lost otherwise.
    :param log_console: also log INFO and above to the console (stderr)
    :param log_file: path of the rotating log file
    :return: list of the added handlers
    :raises OSError: the log file cannot be opened (e.g. its folder is missing)
    """
    handlers: list[logging.Handler] = []
    log_rotate_file = logging.handlers.RotatingFileHandler(
        f"{log_file}", maxBytes=8000000, backupCount=5
    )
    log_rotate_file.setLevel(logging.WARNING)
    handlers.append(log_rotate_file)
    if log_console:
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        handlers.insert(0, console)
    package_logger.setLevel(logging.INFO)
    for handler in handlers:
        handler.setFormatter(formatter)
        package_logger.addHandler(handler)
    return handlers


def main(config_file: str | os.PathLike[str]) -> int:
    """
    run the data collector once
    :return: exit code, 0 if the data was collected, stored and sent by mail, else 1
    """
    logger.info("run script: %s", sys.argv[0])

    try:
        config = configuration.load_configuration(config_file)
    except FileNotFoundError as err:
        logger.error("no configuration: %s", err)
        return 1
    except configuration.ConfigurationError as err:
        # an error mail is only possible if the mail section is valid
        report_error(err.mail, str(err))
        return 1

    try:
        data_path = collect_and_store(config)
    except errors.GruenbeckError as err:
        report_error(config.mail, str(err))
        return 1
    except Exception as err:
        # a failure nobody expected: with traceback in the log and in the error mail
        report_error(
            config.mail,
            f"unexpected error: {type(err).__name__}: {err}\n\n{traceback.format_exc()}",
            unexpected=True,
        )
        return 1

    # the data is stored at this point; a failed mail still has to be visible
    # as a failed run (exit code 1) for cron and systemd
    if not get_mail(config, data_path):
        logger.error("data was collected and stored, but email sending failed")
        return 1

    logger.info("Data collection completed")
    return 0


def collect_and_store(config: configuration.Configuration) -> pathlib.Path:
    """
    request the device and store the new values in the yearly files
    :return: pathlib.Path of the data folder
    :raises errors.GruenbeckError: the run fails; nothing is written then
    """
    data_path = get_data_folder(config)
    data_file = config.data_file
    device_parameter = get_device_parameter(config)
    water_system = config.soft_water_system
    device_data = device.get_device_data(
        water_system.host,
        device_parameter,
        water_system.timeout,
        water_system.retries,
        water_system.retry_delay,
    )
    now = local_now()
    device.check_device_clock(device_data.pop(device.DEVICE_CLOCK_PARAMETER, None), now)
    values_by_day = device.add_timestamp_as_key_device_data(device_data, today=now.date())
    values_by_day = filter_first_date(values_by_day, data_file.first_date)
    # a value without text is None: int() raises TypeError, reported as unexpected error
    # until P006-S9 checks the values
    new_values = {
        day: int(value)  # type: ignore[arg-type]  # a value may be None, see above
        for day, value in values_by_day.items()
    }

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

    # Track if any data was processed
    data_processed = False

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
        data_processed = True

    # nothing stored is a failure, not a successful run
    if not data_processed:
        raise CollectError("no data was processed")
    return data_path


def get_data_folder(config: configuration.Configuration) -> pathlib.Path:
    """
    :raises storage.StorageError: the data folder cannot be created
    """
    try:
        return storage.check_data_folder(config.data_path)
    except OSError as err:
        raise storage.StorageError(f"creation data folder failed: {err}") from err


def get_device_parameter(config: configuration.Configuration) -> device.Parameter:
    """
    :raises device.DeviceError: the parameter file is missing
    """
    try:
        return device.Parameter(config.parameter_file)
    except FileNotFoundError as err:
        raise device.DeviceError(f"{err}") from err


def report_error(
    mail_settings: configuration.Mail | None, error_text: str, unexpected: bool = False
) -> None:
    """
    log the error and send it as error mail
    :param mail_settings: mail section of the configuration, None if it is invalid
    :param unexpected: called while handling an unexpected exception: log its traceback
    """
    if unexpected:
        logger.exception("%s", error_text.split("\n", 1)[0])
    else:
        logger.error("%s", error_text)

    # Try to send an email notification about the error
    if mail_settings is None:
        logger.error("Failed to send error notification email: no valid mail configuration")
        return
    try:
        mail.send_mail(mail_settings, ERROR_MAIL_SUBJECT, error_text)
        logger.info("Error notification email sent")
    except Exception as mail_error:
        logger.error("Failed to send error notification email: %s", mail_error)


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


def get_mail(config: configuration.Configuration, data_path: pathlib.Path) -> bool:
    """
    send the csv files of the data folder as data mail
    :return: True if the mail was sent; a failure is logged and gives False
    """
    try:
        files = storage.list_csv_files(data_path)
        text = DATA_MAIL_TEXT if files else f"{DATA_MAIL_TEXT}\n\n{NO_DATA_FILES_TEXT}"
        mail.send_mail(config.mail, config.mail.subject, text, files)
        logger.info("mail sent successfully")
        return True
    except errors.GruenbeckError as error:
        logger.error("mail sending failed: %s", error)
        return False
    except Exception as error:
        logger.error("unexpected error during mail sending: %s", error)
        return False


def collect(argv: Sequence[str] | None = None) -> int:
    """
    command gruenbeck-collect: the options of the former src/data-collector.py
    :return: exit code (the console script passes it to sys.exit)
    """
    parser = argparse.ArgumentParser(
        prog="gruenbeck-collect",
        description="collect the water consumption of the soft water system, store it and mail it",
    )
    parser.add_argument(
        "--config-file",
        "-c",
        help="set config file",
        required=False,
        default="./src/config.json",
    )
    parser.add_argument("--log-console", "-l", help="activate console logging", action="store_true")
    parser.add_argument(
        "--log-error",
        "-e",
        help="log warnings and errors to file",
        required=False,
        default="./log/gruenbeck_error.log",
    )
    args = parser.parse_args(argv)

    try:
        setup_logging(args.log_console, args.log_error)
    except OSError as err:
        # before the configuration is read: no log file and no error mail
        print(f"{parser.prog}: cannot open the log file: {err}", file=sys.stderr)
        return 1

    return main(args.config_file)


def analyse(argv: Sequence[str] | None = None) -> int:
    """
    command gruenbeck-analyse: the options of the former src/data-analyse.py
    :return: exit code (the console script passes it to sys.exit)
    """
    parser = argparse.ArgumentParser(
        prog="gruenbeck-analyse",
        description="monthly statistics of the collected water consumption",
    )
    parser.add_argument(
        "--config-file",
        "-c",
        help="set config file",
        required=False,
        default="./src/config.json",
    )
    args = parser.parse_args(argv)

    try:
        analysis.main(args.config_file)
    except FileNotFoundError as err:
        print(f"{parser.prog}: no configuration: {err}", file=sys.stderr)
        return 1
    except errors.GruenbeckError as err:
        print(f"{parser.prog}: {err}", file=sys.stderr)
        return 1
    return 0
