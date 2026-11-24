"""
the query of the device with repeated attempts (P006-S6)

Two kinds of tests: with a fake request function (answers that are not valid, errors that
are not repeated) and with a local web server that answers following a script (what the
session of urllib3 repeats). The waiting time (time.sleep) is recorded, not waited.
"""

import collections.abc
import http.server
import logging
import socket
import threading
import typing

import pytest
import requests
import urllib3.exceptions

from gruenbeck import device

MEMORY = [f"D_Y_2_{n}" for n in range(1, 15)]
ANSWER = {"D_C_4_2": "16:00", **{name: "1" for name in MEMORY}}
VALID_XML = (
    "<data>" + "".join(f"<{key}>{value}</{key}>" for key, value in ANSWER.items()) + "</data>"
)


type LogRecords = collections.abc.Callable[[], list[tuple[str, str]]]


@pytest.fixture
def logs(caplog: pytest.LogCaptureFixture) -> LogRecords:
    """(level, message) of the records of the device module, INFO and above"""
    caplog.set_level(logging.INFO, logger="gruenbeck")

    def records() -> list[tuple[str, str]]:
        return [
            (record.levelname, record.getMessage())
            for record in caplog.records
            if record.name == "gruenbeck.device"
        ]

    return records


# --- a fake request function --------------------------------------------------------


class Fake:
    """
    fake get_data_from_mux_http: `errors` are raised by the next requests, then it gives the
    `answers` in turn and then ANSWER; `calls` records (host, parameters, timeout, session)
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str], float, requests.Session | None]] = []
        self.errors: list[BaseException] = []
        self.answers: list[dict[str, str | None]] = []

    def fetch(
        self,
        host: str,
        parameters: collections.abc.Iterable[str],
        timeout: float,
        session: requests.Session | None = None,
    ) -> dict[str, str | None]:
        self.calls.append((host, list(parameters), timeout, session))
        if self.errors:
            raise self.errors.pop(0)
        return self.answers.pop(0) if self.answers else dict(ANSWER)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Fake:
    result = Fake()
    monkeypatch.setattr(device, "get_data_from_mux_http", result.fetch)
    return result


def test_the_device_is_asked_for_the_clock_and_the_memory_with_a_session(
    fake: Fake, sleeps: list[float]
) -> None:
    result = device.get_device_data("device.lan", 7.0, 5, 5.0)

    assert result == ANSWER
    ((host, parameters, timeout, session),) = fake.calls
    assert (host, parameters, timeout) == ("device.lan", ["D_C_4_2", *MEMORY], 7.0)
    assert isinstance(session, requests.Session)
    assert sleeps == []


@pytest.mark.parametrize(
    "error",
    [ValueError("failed to parse xml: x"), ValueError("device response contains no values")],
    ids=["invalid xml", "no values"],
)
def test_invalid_response_is_asked_again(
    fake: Fake,
    sleeps: list[float],
    logs: LogRecords,
    error: Exception,
) -> None:
    fake.errors = [error, error]

    result = device.get_device_data("device.lan", 30, 5, 5.0)

    assert result == ANSWER
    assert len(fake.calls) == 3
    # the same time in between, not growing
    assert sleeps == [5.0, 5.0]
    assert logs() == [
        ("WARNING", f"invalid device response: {error}. Attempt 1/6"),
        ("WARNING", f"invalid device response: {error}. Attempt 2/6"),
        ("INFO", "Successfully retrieved data after 2 retry attempts"),
    ]


def test_invalid_response_fails_after_all_attempts(fake: Fake, sleeps: list[float]) -> None:
    errors = [ValueError(f"bad {n}") for n in range(5)]
    fake.errors = list(errors)

    with pytest.raises(device.DeviceError) as err:
        device.get_device_data("device.lan", 30, 3, 5.0)

    assert len(fake.calls) == 4
    assert sleeps == [5.0, 5.0, 5.0]
    # the error names the last error only; the error mail is sent by cli.main()
    assert str(err.value) == "failed to get device data after 4 attempts: bad 3"
    assert err.value.__cause__ is errors[3]


def test_missing_place_is_asked_again(fake: Fake, sleeps: list[float], logs: LogRecords) -> None:
    without_place: dict[str, str | None] = {
        key: value for key, value in ANSWER.items() if key != "D_Y_2_5"
    }
    without_three: dict[str, str | None] = {
        key: value for key, value in ANSWER.items() if key not in MEMORY[:3]
    }
    fake.answers = [without_place, without_three, without_place]

    result = device.get_device_data("device.lan", 30, 5, 5.0)

    assert result == ANSWER
    assert len(fake.calls) == 4
    assert sleeps == [5.0, 5.0, 5.0]
    assert logs() == [
        ("WARNING", "invalid device response: device response lacks D_Y_2_5. Attempt 1/6"),
        (
            "WARNING",
            "invalid device response: device response lacks D_Y_2_1, D_Y_2_2, D_Y_2_3. Attempt 2/6",
        ),
        ("WARNING", "invalid device response: device response lacks D_Y_2_5. Attempt 3/6"),
        ("INFO", "Successfully retrieved data after 3 retry attempts"),
    ]


def test_missing_place_fails_after_all_attempts(fake: Fake, sleeps: list[float]) -> None:
    fake.answers = [{key: value for key, value in ANSWER.items() if key != "D_Y_2_14"}] * 3

    with pytest.raises(device.DeviceError) as err:
        device.get_device_data("device.lan", 30, 2, 5.0)

    assert str(err.value) == (
        "failed to get device data after 3 attempts: device response lacks D_Y_2_14"
    )
    assert isinstance(err.value.__cause__, ValueError)
    assert len(fake.calls) == 3
    assert sleeps == [5.0, 5.0]


def test_missing_device_clock_is_no_invalid_response(fake: Fake, sleeps: list[float]) -> None:
    # the clock only gives a warning, see check_device_clock()
    fake.answers = [{key: value for key, value in ANSWER.items() if key != "D_C_4_2"}]

    result = device.get_device_data("device.lan", 30, 5, 5.0)

    assert "D_C_4_2" not in result
    assert len(fake.calls) == 1
    assert sleeps == []


def test_extra_parameters_in_the_response_are_not_an_invalid_response(
    fake: Fake, sleeps: list[float]
) -> None:
    # read_consumption() reports an unknown consumption parameter
    fake.answers = [{**ANSWER, "D_Y_1": "5"}]

    assert device.get_device_data("device.lan", 30, 5, 5.0)["D_Y_1"] == "5"
    assert len(fake.calls) == 1


def test_number_of_retries_and_delay_are_parameters(fake: Fake, sleeps: list[float]) -> None:
    fake.errors = [ValueError("bad")] * 2

    with pytest.raises(device.DeviceError, match=r"^failed to get device data after 2 attempts"):
        device.get_device_data("device.lan", 30, 1, 0.5)

    assert len(fake.calls) == 2
    assert sleeps == [0.5]


def test_no_retry_with_retries_zero(fake: Fake, sleeps: list[float]) -> None:
    fake.errors = [ValueError("bad")]

    with pytest.raises(device.DeviceError, match=r"^failed to get device data after 1 attempts"):
        device.get_device_data("device.lan", 30, 0, 5.0)

    assert len(fake.calls) == 1
    assert sleeps == []


@pytest.mark.parametrize(
    "error, text",
    [
        (requests.exceptions.ConnectTimeout("connect timed out"), "connect timed out"),
        (requests.exceptions.ReadTimeout("read timed out"), "read timed out"),
        (requests.exceptions.HTTPError("404 Client Error"), "404 Client Error"),
        (requests.exceptions.InvalidURL("Invalid URL"), "Invalid URL"),
    ],
    ids=lambda value: value if isinstance(value, str) else type(value).__name__,
)
def test_request_error_is_not_asked_again_by_the_query(
    fake: Fake,
    sleeps: list[float],
    error: typing.Any,
    text: str,
) -> None:
    # the session repeated what is temporary already; InvalidURL is a ValueError as well
    fake.errors = [error]

    with pytest.raises(device.DeviceError) as err:
        device.get_device_data("device.lan", 30, 5, 5.0)

    assert str(err.value) == f"failed to get device data: {text}"
    assert err.value.__cause__ is error
    assert len(fake.calls) == 1
    assert sleeps == []


def test_unexpected_error_is_not_asked_again(fake: Fake, sleeps: list[float]) -> None:
    # up to P006-S6 any error was repeated; now only cli.main() reports it
    fake.errors = [KeyError("text")]

    with pytest.raises(KeyError):
        device.get_device_data("device.lan", 30, 5, 5.0)

    assert len(fake.calls) == 1
    assert sleeps == []


def test_error_text_of_the_last_attempt_has_no_pool_and_url() -> None:
    pool = urllib3.HTTPConnectionPool("device.lan")
    reason = urllib3.exceptions.ReadTimeoutError(pool, "/mux_http", "Read timed out.")
    wrapped = requests.exceptions.ConnectionError(
        urllib3.exceptions.MaxRetryError(pool, "/mux_http", reason)
    )

    assert "Max retries exceeded" in str(wrapped)
    assert device._describe(wrapped) == str(reason)
    assert device._describe(requests.exceptions.HTTPError("500 Server Error")) == (
        "500 Server Error"
    )


# --- the session ---------------------------------------------------------------------


def test_the_session_repeats_post_after_temporary_errors() -> None:
    session = device.create_session(4, 2.5)

    adapter = session.get_adapter("http://device.lan/mux_http")
    assert isinstance(adapter, requests.adapters.HTTPAdapter)
    retry = adapter.max_retries
    assert retry.total == 4
    assert retry.backoff_factor == 2.5
    assert retry.is_retry("POST", 503)
    assert retry.is_retry("POST", 500)
    assert not retry.is_retry("POST", 404)
    assert not retry.is_retry("POST", 200)
    assert not retry.raise_on_status


# --- a local web server -----------------------------------------------------------------


class Script:
    """answers of the local web server, one item per request; "ok" after the last one"""

    def __init__(self) -> None:
        self.items: list[str] = []
        self.bodies: list[bytes] = []
        self.release = threading.Event()  # ends the answers "slow"


@pytest.fixture
def server() -> collections.abc.Iterator[tuple[str, Script]]:
    """
    local web server for POST /mux_http; items of `script.items`:
    "ok" valid answer, "reset" close the connection, "slow" no answer until the end of the
    test, "503" and "404" HTTP status, "xml" answer that is not xml, "empty" no values,
    "partial" only the clock and D_Y_2_1
    :return: (host with port, script)
    """
    script = Script()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            script.bodies.append(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            item = script.items.pop(0) if script.items else "ok"
            if item == "reset":
                self.connection.close()
                return
            if item == "slow":
                script.release.wait(10)
                return
            status = {"503": 503, "404": 404}.get(item, 200)
            answers = {
                "ok": VALID_XML,
                "xml": "<data",
                "empty": "<data/>",
                "partial": "<data><D_C_4_2>16:00</D_C_4_2><D_Y_2_1>1</D_Y_2_1></data>",
            }
            body = answers.get(item, item).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: typing.Any) -> None:
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    # a short poll interval: shutdown() waits for it
    thread = threading.Thread(
        target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    yield f"127.0.0.1:{httpd.server_address[1]}", script
    script.release.set()
    httpd.shutdown()
    httpd.server_close()
    thread.join()


def test_success_needs_one_request(
    server: tuple[str, Script],
    sleeps: list[float],
    logs: LogRecords,
) -> None:
    host, script = server

    assert device.get_device_data(host, 5, 5, 5.0) == {
        key: str(value) for key, value in ANSWER.items()
    }

    assert len(script.bodies) == 1
    assert script.bodies[0].decode().endswith("&show=" + "|".join(["D_C_4_2", *MEMORY]) + "~")
    assert sleeps == []
    assert logs() == []


def test_aborted_connection_is_asked_again_at_once_then_with_growing_waits(
    server: tuple[str, Script],
    sleeps: list[float],
    logs: LogRecords,
) -> None:
    host, script = server
    script.items = ["reset", "reset", "reset", "reset"]

    assert device.get_device_data(host, 5, 5, 5.0)["D_C_4_2"] == "16:00"

    assert len(script.bodies) == 5
    # urllib3: no wait before the first repeat, then 2, 4, 8 times the backoff factor
    assert sleeps == [10.0, 20.0, 40.0]
    assert [message[:2] for _, message in logs()] == ["re"] * 4
    assert [message.split(". ")[-1] for _, message in logs()] == [
        "Retry 1/5 in 0 s",
        "Retry 2/5 in 10 s",
        "Retry 3/5 in 20 s",
        "Retry 4/5 in 40 s",
    ]
    assert all(level == "WARNING" for level, _ in logs())
    assert "Remote end closed connection without response" in logs()[0][1]


def test_repeated_requests_are_the_same_post(
    server: tuple[str, Script], sleeps: list[float]
) -> None:
    host, script = server
    script.items = ["reset", "503"]

    device.get_device_data(host, 5, 5, 5.0)

    assert len(script.bodies) == 3
    # only the request id may differ: it is random
    shows = {body.split(b"&show=")[1] for body in script.bodies}
    assert len(shows) == 1


def test_server_error_is_asked_again(
    server: tuple[str, Script],
    sleeps: list[float],
    logs: LogRecords,
) -> None:
    host, script = server
    script.items = ["503", "503"]

    device.get_device_data(host, 5, 5, 5.0)

    assert len(script.bodies) == 3
    assert sleeps == [10.0]
    assert [message for _, message in logs()] == [
        "request failed: HTTP status 503. Retry 1/5 in 0 s",
        "request failed: HTTP status 503. Retry 2/5 in 10 s",
    ]


def test_server_error_fails_after_all_attempts(
    server: tuple[str, Script], sleeps: list[float]
) -> None:
    host, script = server
    script.items = ["503"] * 10

    with pytest.raises(device.DeviceError) as err:
        device.get_device_data(host, 5, 2, 5.0)

    assert str(err.value) == (
        f"failed to get device data: 503 Server Error: Service Unavailable for url:"
        f" http://{host}/mux_http"
    )
    assert len(script.bodies) == 3
    assert sleeps == [10.0]


def test_client_error_is_not_asked_again(server: tuple[str, Script], sleeps: list[float]) -> None:
    host, script = server
    script.items = ["404"]

    with pytest.raises(device.DeviceError) as err:
        device.get_device_data(host, 5, 5, 5.0)

    assert str(err.value).startswith("failed to get device data: 404 Client Error")
    assert len(script.bodies) == 1
    assert sleeps == []


def test_aborted_connection_fails_after_all_attempts(
    server: tuple[str, Script], sleeps: list[float]
) -> None:
    host, script = server
    script.items = ["reset"] * 10

    with pytest.raises(device.DeviceError) as err:
        device.get_device_data(host, 5, 2, 5.0)

    # the last error, without the pool and url that urllib3 adds
    assert str(err.value) == (
        "failed to get device data: ('Connection aborted.', RemoteDisconnected("
        "'Remote end closed connection without response'))"
    )
    assert len(script.bodies) == 3
    assert sleeps == [10.0]


def test_no_answer_in_time_is_asked_again(
    server: tuple[str, Script],
    sleeps: list[float],
    logs: LogRecords,
) -> None:
    host, script = server
    script.items = ["slow"]

    device.get_device_data(host, 0.5, 5, 5.0)

    assert len(script.bodies) == 2
    assert "Read timed out" in logs()[0][1]
    assert sleeps == []


def test_unreachable_device_fails_after_all_attempts(sleeps: list[float]) -> None:
    # a port nothing listens on
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        host = f"127.0.0.1:{unused.getsockname()[1]}"

    with pytest.raises(device.DeviceError) as err:
        device.get_device_data(host, 5, 3, 5.0)

    assert str(err.value).startswith("failed to get device data: ")
    assert "Failed to establish a new connection" in str(err.value)
    assert "Max retries exceeded" not in str(err.value)
    assert sleeps == [10.0, 20.0]


@pytest.mark.parametrize("item", ["xml", "empty"])
def test_invalid_answer_is_asked_again_over_the_network(
    server: tuple[str, Script],
    sleeps: list[float],
    item: str,
) -> None:
    host, script = server
    script.items = [item, item]

    assert device.get_device_data(host, 5, 5, 5.0)["D_C_4_2"] == "16:00"

    assert len(script.bodies) == 3
    # the wait of the query itself, not of the session
    assert sleeps == [5.0, 5.0]


def test_answer_without_all_places_is_asked_again_over_the_network(
    server: tuple[str, Script], sleeps: list[float]
) -> None:
    host, script = server
    script.items = ["partial"]

    assert device.get_device_data(host, 5, 5, 5.0)["D_Y_2_14"] == "1"

    assert len(script.bodies) == 2
    assert sleeps == [5.0]


def test_invalid_answer_fails_after_all_attempts_over_the_network(
    server: tuple[str, Script], sleeps: list[float]
) -> None:
    host, script = server
    script.items = ["xml"] * 10

    with pytest.raises(device.DeviceError) as err:
        device.get_device_data(host, 5, 2, 5.0)

    assert str(err.value).startswith("failed to get device data after 3 attempts: failed to parse")
    assert len(script.bodies) == 3


def test_no_retry_with_retries_zero_over_the_network(
    server: tuple[str, Script], sleeps: list[float]
) -> None:
    host, script = server
    script.items = ["reset", "ok"]

    with pytest.raises(device.DeviceError):
        device.get_device_data(host, 5, 0, 5.0)

    assert len(script.bodies) == 1
    assert sleeps == []
