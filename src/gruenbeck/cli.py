"""
commands of the package: gruenbeck-collect (data collector) and gruenbeck-analyse
"""

import argparse
import datetime
import logging.handlers
import sys
import time
import typing

import requests

from gruenbeck import analysis, device, mail, storage
from gruenbeck import config as configuration

# the handlers of setup_logging() sit on the logger of the package, so they also get the
# messages of the other modules (gruenbeck.device, gruenbeck.storage)
package_logger = logging.getLogger("gruenbeck")
package_logger.setLevel(logging.INFO)
logger = logging.getLogger(__name__)

# create logging formatter
formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S"
)

ONE_DAY = datetime.timedelta(days=1)


def setup_logging(log_console=False, log_file="./log/gruenbeck_error.log"):
    """
    attach the handlers to the logger of the package

    The rotating file takes warnings as well as errors: scheduled runs (systemd timer,
    cron) have no console, so a warning would be lost otherwise.
    :param log_console: also log INFO and above to the console (stderr)
    :param log_file: path of the rotating log file
    :return: list of the added handlers
    """
    handlers: list[logging.Handler] = []
    if log_console:
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        handlers.append(console)
    log_rotate_file = logging.handlers.RotatingFileHandler(
        f"{log_file}", maxBytes=8000000, backupCount=5
    )
    log_rotate_file.setLevel(logging.WARNING)
    handlers.append(log_rotate_file)
    for handler in handlers:
        handler.setFormatter(formatter)
        package_logger.addHandler(handler)
    return handlers


def main(config_file):
    logger.info(f"[*] run script: {sys.argv[0]}")

    config = get_configuration(config_file)
    data_path = get_data_folder(config)
    data_file = config.data_file
    device_parameter = get_device_parameter(config)
    device_data = get_device_data(config, device_parameter)
    now = local_now()
    device.check_device_clock(device_data.pop(device.DEVICE_CLOCK_PARAMETER, None), now)
    try:
        device_data = device.add_timestamp_as_key_device_data(device_data, today=now.date())
    except ValueError as err:
        handle_error(config.mail, f"{err}")
    device_data = filter_first_date(config, device_data, data_file.first_date)
    new_values = {day: int(value) for day, value in device_data.items()}

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
    except storage.DataFileError as err:
        handle_error(config.mail, f"[-] {err}: nothing written")
    check_stored_overlap(
        config,
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
        handle_error(config.mail, "[-] no data was processed")

    # the data is stored at this point; a failed mail still has to be visible
    # as a failed run (exit code 1) for cron and systemd
    if not get_mail(config, data_path):
        logger.error("[-] data was collected and stored, but email sending failed")
        sys.exit(1)

    logger.info("[*] Data collection completed")


def get_configuration(config_file) -> configuration.Configuration:
    try:
        return configuration.load_configuration(config_file)
    except FileNotFoundError as err:
        logger.error(f"[-] no configuration: {err}")
        sys.exit(1)
    except configuration.ConfigurationError as err:
        # an error mail is only possible if the mail section is valid
        handle_error(err.mail, f"[-] {err}")


def get_data_folder(config):
    data_path = None
    try:
        data_path = storage.check_data_folder(config.data_path)
    except PermissionError as err:
        handle_error(config.mail, f"[-] creation data folder failed: {err}")
    return data_path


def get_device_parameter(config):
    parameter = None
    try:
        parameter = device.Parameter(config.parameter_file)
    except FileNotFoundError as err:
        handle_error(config.mail, f"{err}")
    return parameter


def get_consumption_parameters(config, parameter):
    """
    parameter codes of the 14-day memory: D_Y_2_1 ... D_Y_2_14 in this order

    Other rows of the parameter file about the water consumption (D_Y_1, D_Y_2_27)
    are not requested.
    :param parameter: device.Parameter of the parameter file
    :return: list of parameter codes
    """
    names = [f"D_Y_2_{n}" for n in range(1, device.DEVICE_MEMORY_DAYS + 1)]
    known = parameter.get_parameter_list()
    missing = [name for name in names if name not in known]
    if missing:
        handle_error(
            config.mail,
            f"[-] parameter file {parameter.path_file} lacks the consumption"
            f" parameters: {', '.join(missing)}",
        )
    return names


def get_device_data(config, parameter, max_retries=3, retry_delay=5):
    result = None
    attempts = 0
    last_error: Exception | None = None
    timeout = config.soft_water_system.timeout
    # the device clock comes with the values, see check_device_clock()
    request_parameters = [
        device.DEVICE_CLOCK_PARAMETER,
        *get_consumption_parameters(config, parameter),
    ]

    while attempts <= max_retries:
        try:
            if attempts > 0:
                logger.info(f"[*] Retry attempt {attempts}/{max_retries} for API request")

            result = device.get_data_from_mux_http(
                config.soft_water_system.host,
                request_parameters,
                timeout=timeout,
            )

            # If we got here, the request was successful
            if attempts > 0:
                logger.info(f"[*] Successfully retrieved data after {attempts} retry attempts")
            return result

        except ValueError as err:
            # invalid xml or response without values
            last_error = err
            logger.warning(
                f"[-] invalid device response: {err}. Attempt {attempts + 1}/{max_retries + 1}"
            )

        except requests.exceptions.RequestException as err:
            # Network-related errors
            last_error = err
            logger.warning(f"[-] request failed: {err}. Attempt {attempts + 1}/{max_retries + 1}")

        except Exception as err:
            # Any other unexpected errors
            last_error = err
            logger.warning(f"[-] unexpected error: {err}. Attempt {attempts + 1}/{max_retries + 1}")

        attempts += 1

        # If we've reached max retries, handle the error
        if attempts > max_retries:
            error_msg = (
                f"[-] failed to get device data after {max_retries + 1} attempts: {last_error}"
            )
            handle_error(config.mail, error_msg)

        # Wait before retrying

        time.sleep(retry_delay)

    return result


def handle_error(mail_settings: configuration.Mail | None, error_text: str) -> typing.NoReturn:
    """
    log the error, send the error mail and exit with code 1
    :param mail_settings: mail section of the configuration, None if it is invalid
    """
    logger.error(error_text)

    # Try to send an email notification about the error
    if mail_settings is None:
        logger.error("[-] Failed to send error notification email: no valid mail configuration")
    else:
        try:
            mail.send_mail_text(
                mail_settings.as_dict(), "gruenbeck data collector failure", error_text
            )
            logger.info("[*] Error notification email sent")
        except Exception as mail_error:
            logger.error(f"[-] Failed to send error notification email: {mail_error}")

    logger.info("[*] Exiting program due to error")
    sys.exit(1)


def local_now():
    """current local time of the run"""
    return datetime.datetime.now()


def filter_first_date(config, device_data, first_date):
    """
    drop the values of days before dataFile.firstDate
    :param device_data: dictionary of datetime.date and value
    :param first_date: datetime.date, or None for no limit
    :return: dictionary of the remaining datetime.date and value
    """
    if first_date is None:
        return device_data
    result = {day: value for day, value in device_data.items() if day >= first_date}
    skipped = len(device_data) - len(result)
    if skipped:
        logger.info(f"[*] {skipped} values before dataFile.firstDate {first_date} are not written")
    if device_data and not result:
        handle_error(
            config.mail,
            f"[-] no data was processed: all {skipped} values are before"
            f" dataFile.firstDate {first_date}",
        )
    return result


def check_stored_overlap(config, new_values, stored, date_pattern):
    """
    compare the new values with the days that are stored already

    Values of past days do not change on the device. If a stored day gets another
    value, the run writes nothing: either the run was before the daily rollover of the
    device (every new value equals the stored value of the day before) or the data
    files and the device disagree.
    :param new_values: dictionary of datetime.date and value (int)
    :param stored: dictionary of date text and stored value of all files involved
    :param date_pattern: dataFile.datePattern, the format of the date texts
    """
    overlap = [day for day in sorted(new_values) if day.strftime(date_pattern) in stored]
    differing = [day for day in overlap if stored[day.strftime(date_pattern)] != new_values[day]]
    if not differing:
        return
    with_day_before = [day for day in overlap if (day - ONE_DAY).strftime(date_pattern) in stored]
    if with_day_before and all(
        stored[(day - ONE_DAY).strftime(date_pattern)] == new_values[day] for day in with_day_before
    ):
        handle_error(
            config.mail,
            "[-] one day late: the run was probably before the daily rollover of the"
            " device; run again later (the new values of"
            f" {with_day_before[0]} ... {with_day_before[-1]} equal the stored values"
            " of the day before; nothing written)",
        )
    details = ", ".join(
        f"{day}: stored {stored[day.strftime(date_pattern)]}, new {new_values[day]}"
        for day in differing
    )
    handle_error(
        config.mail,
        f"[-] the new values differ from the stored ones ({details}): nothing written;"
        " check the data files and the device",
    )


def get_mail(config, data_path):
    try:
        mail.send_mail(config.mail.as_dict(), data_path)
        logger.info("[*] mail sent successfully")
        return True
    except KeyError as error:
        logger.error(f"[-] no mail configured: {error}")
        # Continue execution instead of exiting
        return False
    except ValueError as error:
        logger.error(f"[-] mail sending failed: {error}")
        # Continue execution instead of exiting
        return False
    except Exception as error:
        logger.error(f"[-] unexpected error during mail sending: {error}")
        # Continue execution instead of exiting
        return False


def collect(argv=None):
    """command gruenbeck-collect: the options of the former src/data-collector.py"""
    parser = argparse.ArgumentParser(
        description="collect the water consumption of the soft water system, store it and mail it"
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

    setup_logging(args.log_console, args.log_error)

    main(args.config_file)


def analyse(argv=None):
    """command gruenbeck-analyse: the options of the former src/data-analyse.py"""
    parser = argparse.ArgumentParser(
        description="monthly statistics of the collected water consumption"
    )
    parser.add_argument(
        "--config-file",
        "-c",
        help="set config file",
        required=False,
        default="./src/config.json",
    )
    args = parser.parse_args(argv)

    analysis.main(args.config_file)
