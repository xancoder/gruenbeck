#!/usr/bin/env python3

import csv
import datetime
import logging.handlers
import os
import pathlib
import re
import shutil
import sys
import time
import typing

import requests

import datacollector
import gruenbeck

# create main logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# create logging formatter
formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S"
)

# D_Y_2_<n> is the water consumption of n days ago (D_Y_2_1 = yesterday)
DAY_PARAMETER = re.compile(r"D_Y_2_([1-9][0-9]*)")
# the device keeps the consumption of 14 days (D_Y_2_15 ... D_Y_2_27 return "-")
DEVICE_MEMORY_DAYS = 14
FIRST_DATE_FORMAT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

# device clock (HH:MM), only checked for a warning: the daily rollover of the device
# does not follow it (about 10:05 CET before and after the clock was set, 2026-11-19/20)
DEVICE_CLOCK_PARAMETER = "D_C_4_2"
DEVICE_CLOCK_FORMAT = re.compile(r"([01][0-9]|2[0-3]):([0-5][0-9])")
CLOCK_TOLERANCE_MINUTES = 15
MINUTES_PER_DAY = 24 * 60
ONE_DAY = datetime.timedelta(days=1)


def setup_logging(log_console=False, log_file="./log/gruenbeck_error.log"):
    """
    attach the handlers to the logger of this script

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
        logger.addHandler(handler)
    return handlers


def main(config_file):
    logger.info(f"[*] run script: {sys.argv[0]}")

    config = get_configuration(config_file)
    data_path = get_data_folder(config)
    first_date = get_first_date(config)
    device_parameter = get_device_parameter(config)
    device_data = get_device_data(config, device_parameter)
    now = local_now()
    check_device_clock(device_data.pop(DEVICE_CLOCK_PARAMETER, None), now)
    try:
        device_data = add_timestamp_as_key_device_data(device_data, today=now.date())
    except ValueError as err:
        handle_error(config, f"{err}")
    device_data = filter_first_date(config, device_data, first_date)
    new_values = {day: int(value) for day, value in device_data.items()}

    # read every yearly file involved (also the one of the day before the oldest new
    # value, see check_stored_overlap) before anything is written
    data_file = config["dataFile"]
    years = sorted({day.year for day in new_values})
    years_to_read = set(years)
    if new_values:
        years_to_read.add((min(new_values) - ONE_DAY).year)
    stored_by_year = {
        year: read_data_file(get_data_file(config, data_path, year), data_file["fieldnames"])
        for year in sorted(years_to_read)
    }
    check_stored_overlap(
        config,
        new_values,
        {day: value for values in stored_by_year.values() for day, value in values.items()},
        data_file["datePattern"],
    )

    # Track if any data was processed
    data_processed = False

    # provides files per year and handle year change
    for year in years:
        data_existing = dict(stored_by_year[year])
        data_existing.update(
            {
                day.strftime(data_file["datePattern"]): value
                for day, value in sorted(new_values.items())
                if day.year == year
            }
        )
        write_data(get_data_file(config, data_path, year), data_file["fieldnames"], data_existing)
        data_processed = True

    # nothing stored is a failure, not a successful run
    if not data_processed:
        handle_error(config, "[-] no data was processed")

    # the data is stored at this point; a failed mail still has to be visible
    # as a failed run (exit code 1) for cron and systemd
    if not get_mail(config, data_path):
        logger.error("[-] data was collected and stored, but email sending failed")
        sys.exit(1)

    logger.info("[*] Data collection completed")


def get_configuration(config_file):
    config = None
    try:
        config = datacollector.check_configuration(config_file)
    except FileNotFoundError as err:
        logger.error(f"[-] no configuration: {err}")
        sys.exit(1)
    return config


def get_data_folder(config):
    data_path = None
    try:
        data_path = datacollector.check_data_folder(config["dataPath"])
    except KeyError as err:
        handle_error(config, f"[-] no config parameter: {err}")
    except PermissionError as err:
        handle_error(config, f"[-] creation data folder failed: {err}")
    return data_path


def get_first_date(config):
    """
    optional dataFile.firstDate (YYYY-MM-DD): values of earlier days are not written
    :return: datetime.date, or None if the key is missing
    """
    try:
        data_file = config["dataFile"]
    except KeyError as err:
        handle_error(config, f"[-] no config parameter: {err}")
    if "firstDate" not in data_file:
        return None
    first_date = data_file["firstDate"]
    try:
        if not isinstance(first_date, str) or not FIRST_DATE_FORMAT.fullmatch(first_date):
            raise ValueError("expected a date YYYY-MM-DD")
        return datetime.date.fromisoformat(first_date)
    except ValueError as err:
        handle_error(
            config,
            f"[-] invalid config parameter dataFile.firstDate {first_date!r}: {err}",
        )


def get_device_parameter(config):
    parameter = None
    try:
        parameter = gruenbeck.Parameter(config["parameterFile"])
    except KeyError as err:
        handle_error(config, f"[-] no config parameter: {err}")
    except FileNotFoundError as err:
        handle_error(config, f"{err}")
    return parameter


def get_device_timeout(config):
    try:
        timeout = float(config["softWaterSystem"].get("timeout", gruenbeck.DEFAULT_TIMEOUT))
        if not timeout > 0:
            raise ValueError("must be greater than 0")
    except KeyError as err:
        handle_error(config, f"[-] no config parameter: {err}")
    except (TypeError, ValueError) as err:
        handle_error(config, f"[-] invalid config parameter softWaterSystem.timeout: {err}")
    return timeout


def get_consumption_parameters(config, parameter):
    """
    parameter codes of the 14-day memory: D_Y_2_1 ... D_Y_2_14 in this order

    Other rows of the parameter file about the water consumption (D_Y_1, D_Y_2_27)
    are not requested.
    :param parameter: gruenbeck.Parameter of the parameter file
    :return: list of parameter codes
    """
    names = [f"D_Y_2_{n}" for n in range(1, DEVICE_MEMORY_DAYS + 1)]
    known = parameter.get_parameter_list()
    missing = [name for name in names if name not in known]
    if missing:
        handle_error(
            config,
            f"[-] parameter file {parameter.path_file} lacks the consumption"
            f" parameters: {', '.join(missing)}",
        )
    return names


def get_device_data(config, parameter, max_retries=3, retry_delay=5):
    result = None
    attempts = 0
    last_error: Exception | None = None
    timeout = get_device_timeout(config)
    # the device clock comes with the values, see check_device_clock()
    request_parameters = [
        DEVICE_CLOCK_PARAMETER,
        *get_consumption_parameters(config, parameter),
    ]

    while attempts <= max_retries:
        try:
            if attempts > 0:
                logger.info(f"[*] Retry attempt {attempts}/{max_retries} for API request")

            result = gruenbeck.get_data_from_mux_http(
                config["softWaterSystem"]["host"],
                request_parameters,
                timeout=timeout,
            )

            # If we got here, the request was successful
            if attempts > 0:
                logger.info(f"[*] Successfully retrieved data after {attempts} retry attempts")
            return result

        except KeyError as err:
            # Configuration errors should not be retried
            handle_error(config, f"[-] no config parameter: {err}")

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
            handle_error(config, error_msg)

        # Wait before retrying

        time.sleep(retry_delay)

    return result


def handle_error(config, error_text: str) -> typing.NoReturn:
    logger.error(error_text)

    # Try to send an email notification about the error
    try:
        datacollector.send_mail_text(config["mail"], "gruenbeck data collector failure", error_text)
        logger.info("[*] Error notification email sent")
    except Exception as mail_error:
        logger.error(f"[-] Failed to send error notification email: {mail_error}")

    logger.info("[*] Exiting program due to error")
    sys.exit(1)


def local_now():
    """current local time of the run"""
    return datetime.datetime.now()


def format_minutes(minutes):
    """signed duration in minutes as +H:MM / -H:MM"""
    sign = "-" if minutes < 0 else "+"
    hours, rest = divmod(abs(minutes), 60)
    return f"{sign}{hours}:{rest:02d}"


def check_device_clock(device_clock, now):
    """
    log a warning if the device clock is off; it does not decide on the run

    The daily rollover of the device does not follow its clock (about 10:05 CET before
    and after the clock was set on 2026-11-19), so the clock is only checked to tell
    the user to set it. check_stored_overlap() detects a run before the rollover.
    :param device_clock: value of D_C_4_2 (HH:MM), None if missing in the response
    :param now: local time of the run (datetime.datetime)
    :return: deviation device clock - local time in minutes, within (-12 h, +12 h],
        or None without a valid device clock
    """
    if device_clock is None:
        logger.warning(f"[-] the device response has no device clock {DEVICE_CLOCK_PARAMETER}")
        return None
    match = DEVICE_CLOCK_FORMAT.fullmatch(str(device_clock).strip())
    if not match:
        logger.warning(
            f"[-] invalid device clock {DEVICE_CLOCK_PARAMETER} {device_clock!r} (expected HH:MM)"
        )
        return None
    device_minutes = int(match.group(1)) * 60 + int(match.group(2))
    local_minutes = now.hour * 60 + now.minute
    deviation = (device_minutes - local_minutes) % MINUTES_PER_DAY
    if deviation > MINUTES_PER_DAY // 2:
        deviation -= MINUTES_PER_DAY
    if abs(deviation) > CLOCK_TOLERANCE_MINUTES:
        logger.warning(
            f"[-] the device clock is off (device clock {match.group(0)}, local time"
            f" {now:%H:%M}, deviation {format_minutes(deviation)}): set the device clock"
        )
    return deviation


def add_timestamp_as_key_device_data(device_data, today=None):
    """
    replace the parameter codes with the day each value belongs to

    D_Y_2_<n> is the consumption of n days ago, so its value is stored under
    today - n days (a calendar date without time). The day comes from the
    parameter name, so the order of the device response does not matter.
    :param device_data: dictionary of parameter code and value
    :param today: date of the run (default: the current local date)
    :return: dictionary of datetime.date and value
    :raises ValueError: a parameter code is not D_Y_2_<n>
    """
    today = today or datetime.date.today()
    result = {}
    for param, value in device_data.items():
        match = DAY_PARAMETER.fullmatch(param)
        if not match:
            raise ValueError(
                f"[-] unknown consumption parameter {param!r}:"
                " expected D_Y_2_<n> (consumption of n days ago)"
            )
        result[today - datetime.timedelta(days=int(match.group(1)))] = value
    return result


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
            config,
            f"[-] no data was processed: all {skipped} values are before"
            f" dataFile.firstDate {first_date}",
        )
    return result


def get_data_file(config, data_path, year):
    """path of the yearly data file"""
    return pathlib.Path(f"{data_path}/{config['dataFile']['prefix']}_{year}.csv")


def read_data_file(file_obj, fieldnames):
    """
    stored values of one yearly file
    :return: dictionary of date text and value (int if numeric), empty without file
    """
    data = {}
    if file_obj.exists():
        with file_obj.open(mode="r", newline="", encoding="utf-8") as csv_file:
            for row in csv.DictReader(csv_file):
                value = row[fieldnames["value"]]
                data[row[fieldnames["date"]]] = int(value) if value.isnumeric() else value
    return data


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
            config,
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
        config,
        f"[-] the new values differ from the stored ones ({details}): nothing written;"
        " check the data files and the device",
    )


def write_data(file_object: pathlib.Path, fieldnames: dict, data: dict) -> None:
    """
    write data to csv file
    :param file_object: pathlib.Path of output file
    :param fieldnames: fieldnames as column headers
    :param data: dictionary data to write
    """
    # build data structure to write
    write_list = []
    for item in sorted(data):
        write_list.append({fieldnames["date"]: item, fieldnames["value"]: data[item]})

    # write into a temporary file next to the target and replace the target
    # afterwards, so an interruption never leaves a truncated data file
    logger.info(f"[*] data to write: {data}")
    tmp_file = file_object.with_name(f".{file_object.name}.tmp")
    try:
        with tmp_file.open(mode="w", newline="", encoding="utf-8") as csv_out_file:
            writer = csv.DictWriter(csv_out_file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(write_list)
            csv_out_file.flush()
            os.fsync(csv_out_file.fileno())
        if file_object.exists():
            shutil.copymode(file_object, tmp_file)
        os.replace(tmp_file, file_object)
    except BaseException:
        tmp_file.unlink(missing_ok=True)
        raise


def get_mail(config, data_path):
    try:
        datacollector.send_mail(config["mail"], data_path)
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


if __name__ == "__main__":
    import argparse

    # parse commandline arguments
    parser = argparse.ArgumentParser()
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
    args = parser.parse_args()

    CONFIG_file = args.config_file

    setup_logging(args.log_console, args.log_error)

    main(CONFIG_file)
