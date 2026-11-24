"""web server of the soft water system: parameters, request, meaning of the values"""

import csv
import datetime
import logging
import os
import pathlib
import random
import re
import time
import types
import typing
import xml.etree.ElementTree
from collections.abc import Iterable, KeysView

import requests
import urllib3.exceptions
import urllib3.util

from gruenbeck import errors

logger = logging.getLogger(__name__)

# seconds to wait for connect and for the response of the device
DEFAULT_TIMEOUT = 30
# answers of the web server that are asked again: every server error
RETRY_STATUS = frozenset(range(500, 600))


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


class _LoggingRetry(urllib3.util.Retry):
    """the Retry of urllib3 that logs every repeated attempt"""

    def increment(
        self,
        method: str | None = None,
        url: str | None = None,
        response: urllib3.BaseHTTPResponse | None = None,
        error: Exception | None = None,
        _pool: urllib3.connectionpool.ConnectionPool | None = None,
        _stacktrace: types.TracebackType | None = None,
    ) -> typing.Self:
        # raises MaxRetryError if no attempt is left: the caller reports the failure
        retry = super().increment(method, url, response, error, _pool, _stacktrace)
        done = len(retry.history)
        total = done + typing.cast(int, retry.total)
        reason = error if error is not None else f"HTTP status {getattr(response, 'status', '?')}"
        logger.warning(
            "request failed: %s. Retry %d/%d in %g s",
            reason,
            done,
            total,
            retry.get_backoff_time(),
        )
        return retry


class Parameter:
    count = 0

    def __init__(self, path: str | os.PathLike[str]):
        self.path_file = path
        self.parameters: dict[str, dict[str, str]] = {}
        self.read()

    def read(self) -> None:
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

    def get_count(self) -> int:
        return len(self.parameters)

    def get_parameter_list(self) -> KeysView[str]:
        return self.parameters.keys()

    def get_parameter_by_note(self, note: str) -> list[str]:
        result = []
        for _ in self.get_parameter_list():
            if note in self.get_parameter(_)["note"]:
                result.append(_)
        return result

    def get_parameter(self, name: str) -> dict[str, str]:
        return self.parameters[name]


def create_session(retries: int, retry_delay: float) -> requests.Session:
    """
    session that repeats a request after a temporary error

    Repeated are connection errors, timeouts, an aborted connection and server errors
    (HTTP 5xx), also for POST: the request only reads values. Other answers such as 404 fail
    at once. The first repeat comes at once, the n-th after retry_delay * 2^(n-1) seconds
    (at most 120): retry_delay=5 waits 0, 10, 20, 40, 80 s.
    :param retries: number of repeated attempts after the first one
    :param retry_delay: backoff factor in seconds
    """
    retry = _LoggingRetry(
        total=retries,
        backoff_factor=retry_delay,
        status_forcelist=RETRY_STATUS,
        allowed_methods=frozenset({"POST"}),
        # the last answer is returned and raise_for_status() names its status
        raise_on_status=False,
    )
    session = requests.Session()
    session.mount("http://", requests.adapters.HTTPAdapter(max_retries=retry))
    return session


def get_data_from_mux_http(
    host: str,
    parameters: Iterable[str],
    timeout: float = DEFAULT_TIMEOUT,
    session: requests.Session | None = None,
) -> dict[str, str | None]:
    """
    request values from the web server of the device
    :param host: host name (optionally with port) of the device
    :param parameters: parameter codes to request
    :param timeout: seconds to wait for connect and for the response (per attempt)
    :param session: requests.Session, e.g. of create_session(); default: no repeated attempts
    :return: dictionary of parameter code and value
    :raises requests.exceptions.RequestException: no connection, timeout or HTTP error
    :raises ValueError: response is not valid xml or contains no values
    """
    result_data: dict[str, str | None] = {}

    url = f"http://{host}/mux_http"

    request_id = random.randint(4000, 6000)
    payload_header = f"id={request_id}&show="
    data = "|".join(parameters)
    payload = f"{payload_header}{data}~"

    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    post = requests.post if session is None else session.post
    response_data = post(url, data=payload, headers=headers, timeout=timeout)
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


def get_consumption_parameters(parameter: Parameter) -> list[str]:
    """
    parameter codes of the 14-day memory: D_Y_2_1 ... D_Y_2_14 in this order

    Other rows of the parameter file about the water consumption (D_Y_1, D_Y_2_27)
    are not requested.
    :param parameter: Parameter of the parameter file
    :return: list of parameter codes
    :raises DeviceError: the parameter file lacks one of them
    """
    names = [f"D_Y_2_{n}" for n in range(1, DEVICE_MEMORY_DAYS + 1)]
    known = parameter.get_parameter_list()
    missing = [name for name in names if name not in known]
    if missing:
        raise DeviceError(
            f"parameter file {parameter.path_file} lacks the consumption"
            f" parameters: {', '.join(missing)}"
        )
    return names


def _describe(error: requests.exceptions.RequestException) -> str:
    """the text of a failed request; without the pool and url urllib3 adds to the last error"""
    cause = error.args[0] if error.args else None
    if isinstance(cause, urllib3.exceptions.MaxRetryError) and cause.reason is not None:
        return str(cause.reason)
    return str(error)


def get_device_data(
    host: str, parameter: Parameter, timeout: float, retries: int, retry_delay: float
) -> dict[str, str | None]:
    """
    ask the device for the 14-day memory and its clock

    A temporary failure of the request is repeated by the session (create_session).
    A response that is not valid xml or has no values (ValueError) is asked again as
    well, up to `retries` times with retry_delay seconds in between.
    :param host: host name (optionally with port) of the device
    :param parameter: Parameter of the parameter file
    :param timeout: seconds to wait for connect and for the response (per attempt)
    :param retries: number of repeated attempts after the first one
    :param retry_delay: seconds to wait (backoff factor of the session)
    :return: dictionary of parameter code and value
    :raises DeviceError: no valid answer after the repeated attempts
    """
    # the device clock comes with the values, see check_device_clock()
    request_parameters = [DEVICE_CLOCK_PARAMETER, *get_consumption_parameters(parameter)]
    attempts = 0
    with create_session(retries, retry_delay) as session:
        while True:
            try:
                result = get_data_from_mux_http(host, request_parameters, timeout, session)
            except requests.exceptions.RequestException as err:
                # includes InvalidURL, which is a ValueError as well
                raise DeviceError(f"failed to get device data: {_describe(err)}") from err
            except ValueError as err:
                # invalid xml or response without values
                attempts += 1
                logger.warning(
                    "invalid device response: %s. Attempt %d/%d", err, attempts, retries + 1
                )
                if attempts > retries:
                    raise DeviceError(
                        f"failed to get device data after {attempts} attempts: {err}"
                    ) from err
                time.sleep(retry_delay)
                continue
            if attempts:
                logger.info("Successfully retrieved data after %d retry attempts", attempts)
            return result


def format_minutes(minutes: int) -> str:
    """signed duration in minutes as +H:MM / -H:MM"""
    sign = "-" if minutes < 0 else "+"
    hours, rest = divmod(abs(minutes), 60)
    return f"{sign}{hours}:{rest:02d}"


def check_device_clock(device_clock: str | None, now: datetime.datetime) -> int | None:
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


def add_timestamp_as_key_device_data[V](
    device_data: dict[str, V], today: datetime.date | None = None
) -> dict[datetime.date, V]:
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
