"""web server of the soft water system: parameters, request, meaning of the values"""

import csv
import datetime
import logging
import pathlib
import random
import re
import xml.etree.ElementTree

import requests

from gruenbeck import errors

logger = logging.getLogger(__name__)

# seconds to wait for connect and for the response of the device
DEFAULT_TIMEOUT = 30


# D_Y_2_<n> is the water consumption of n days ago (D_Y_2_1 = yesterday)
DAY_PARAMETER = re.compile(r"D_Y_2_([1-9][0-9]*)")
# the device keeps the consumption of 14 days (D_Y_2_15 ... D_Y_2_27 return "-")
DEVICE_MEMORY_DAYS = 14

# device clock (HH:MM), only checked for a warning: the daily rollover of the device
# does not follow it (about 10:05 CET before and after the clock was set, 2026-11-19/20)
DEVICE_CLOCK_PARAMETER = "D_C_4_2"
DEVICE_CLOCK_FORMAT = re.compile(r"([01][0-9]|2[0-3]):([0-5][0-9])")
CLOCK_TOLERANCE_MINUTES = 15
MINUTES_PER_DAY = 24 * 60


class DeviceError(errors.GruenbeckError):
    """the parameter file or the answer of the device is not usable"""


class Parameter:
    count = 0

    def __init__(self, path):
        self.path_file = path
        self.parameters = {}
        self.read()

    def read(self):
        file_path = pathlib.Path(self.path_file)
        with file_path.open() as input_file:
            reader = csv.DictReader(input_file)
            for row in reader:
                # skip empty lines or with starting with '#'
                if not row["parameter"] or row["parameter"].startswith("#"):
                    continue
                # build parameter dictionary
                self.parameters.update(
                    {
                        row["parameter"]: {
                            "access": row["access"],
                            "device": row["device"],
                            "value": row["value"],
                            "unit": row["unit"],
                            "code": row["code"],
                            "note": row["note"],
                        }
                    }
                )

    def get_count(self):
        return len(self.parameters)

    def get_parameter_list(self):
        return self.parameters.keys()

    def get_parameter_by_note(self, note):
        result = []
        for _ in self.get_parameter_list():
            if note in self.get_parameter(_)["note"]:
                result.append(_)
        return result

    def get_parameter(self, name):
        return self.parameters[name]


def get_data_from_mux_http(host, parameters, timeout=DEFAULT_TIMEOUT):
    """
    request values from the web server of the device
    :param host: host name (optionally with port) of the device
    :param parameters: parameter codes to request
    :param timeout: seconds to wait for connect and for the response
    :return: dictionary of parameter code and value
    :raises requests.exceptions.RequestException: no connection, timeout or HTTP error
    :raises ValueError: response is not valid xml or contains no values
    """
    result_data = {}

    url = f"http://{host}/mux_http"

    request_id = random.randint(4000, 6000)
    payload_header = f"id={request_id}&show="
    data = "|".join(parameters)
    payload = f"{payload_header}{data}~"

    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    response_data = requests.post(url, data=payload, headers=headers, timeout=timeout)
    response_data.raise_for_status()

    try:
        root = xml.etree.ElementTree.fromstring(response_data.text)
    except xml.etree.ElementTree.ParseError as err:
        raise ValueError(f"failed to parse xml: {err}") from err

    for child in root:
        if child.tag == "code":
            continue
        result_data.update({child.tag: child.text})

    if not result_data:
        raise ValueError("device response contains no values")

    return result_data


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
        logger.warning("the device response has no device clock %s", DEVICE_CLOCK_PARAMETER)
        return None
    match = DEVICE_CLOCK_FORMAT.fullmatch(str(device_clock).strip())
    if not match:
        logger.warning(
            "invalid device clock %s %r (expected HH:MM)", DEVICE_CLOCK_PARAMETER, device_clock
        )
        return None
    device_minutes = int(match.group(1)) * 60 + int(match.group(2))
    local_minutes = now.hour * 60 + now.minute
    deviation = (device_minutes - local_minutes) % MINUTES_PER_DAY
    if deviation > MINUTES_PER_DAY // 2:
        deviation -= MINUTES_PER_DAY
    if abs(deviation) > CLOCK_TOLERANCE_MINUTES:
        logger.warning(
            "the device clock is off (device clock %s, local time %s, deviation %s): set the"
            " device clock",
            match.group(0),
            f"{now:%H:%M}",
            format_minutes(deviation),
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
    :raises DeviceError: a parameter code is not D_Y_2_<n>
    """
    today = today or datetime.date.today()
    result = {}
    for param, value in device_data.items():
        match = DAY_PARAMETER.fullmatch(param)
        if not match:
            raise DeviceError(
                f"unknown consumption parameter {param!r}:"
                " expected D_Y_2_<n> (consumption of n days ago)"
            )
        result[today - datetime.timedelta(days=int(match.group(1)))] = value
    return result
