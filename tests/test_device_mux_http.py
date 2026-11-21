"""
characterization of gruenbeck.device.get_data_from_mux_http() (P006-S1)

The HTTP requests go to a mock of the requests library (responses), never to a device.
"""

import re
from collections.abc import Iterator

import pytest
import requests
import responses
from responses import matchers

# the fixture device is the mocked web server, so the module is used as gruenbeck.device
import gruenbeck.device

HOST = "device.lan"
URL = f"http://{HOST}/mux_http"
# answer of the device to a read request (P004, plan context)
ANSWER = (
    "<data><code>ok</code><D_Y_2_1>93</D_Y_2_1><D_Y_2_2>33</D_Y_2_2><D_Y_2_3>170</D_Y_2_3></data>"
)


@pytest.fixture
def device() -> Iterator[responses.RequestsMock]:
    """mocked web server of the device; every registered response must be requested"""
    with responses.RequestsMock() as mock:
        yield mock


def request_body(device: responses.RequestsMock, index: int = 0) -> str:
    body = device.calls[index].request.body
    assert body is not None
    return body.decode() if isinstance(body, bytes) else body


def test_values_of_the_answer_by_parameter_code(device):
    device.post(URL, body=ANSWER)

    result = gruenbeck.device.get_data_from_mux_http(HOST, ["D_Y_2_1", "D_Y_2_2", "D_Y_2_3"])

    assert result == {"D_Y_2_1": "93", "D_Y_2_2": "33", "D_Y_2_3": "170"}


def test_values_keep_the_order_of_the_answer(device):
    device.post(
        URL,
        body="<data><code>ok</code><D_Y_2_3>170</D_Y_2_3><D_Y_2_1>93</D_Y_2_1></data>",
    )

    result = gruenbeck.device.get_data_from_mux_http(HOST, ["D_Y_2_1", "D_Y_2_3"])

    assert list(result.items()) == [("D_Y_2_3", "170"), ("D_Y_2_1", "93")]


def test_request_is_a_form_post_with_id_and_parameter_list(device):
    device.post(
        URL,
        body=ANSWER,
        match=[matchers.header_matcher({"Content-Type": "application/x-www-form-urlencoded"})],
    )

    gruenbeck.device.get_data_from_mux_http(HOST, ["D_C_4_2", "D_Y_2_1", "D_Y_2_14"])

    assert len(device.calls) == 1
    assert device.calls[0].request.method == "POST"
    assert device.calls[0].request.url == URL
    match = re.fullmatch(r"id=([0-9]+)&show=D_C_4_2\|D_Y_2_1\|D_Y_2_14~", request_body(device))
    assert match is not None
    assert 4000 <= int(match.group(1)) <= 6000


def test_request_id_is_random_between_4000_and_6000(device, monkeypatch):
    calls = []

    def randint(low, high):
        calls.append((low, high))
        return 4711

    monkeypatch.setattr(gruenbeck.device.random, "randint", randint)
    device.post(URL, body=ANSWER)

    gruenbeck.device.get_data_from_mux_http(HOST, ["D_Y_2_1"])

    assert calls == [(4000, 6000)]
    assert request_body(device) == "id=4711&show=D_Y_2_1~"


def test_host_may_contain_a_port(device):
    device.post("http://192.0.2.10:8080/mux_http", body=ANSWER)

    assert (
        gruenbeck.device.get_data_from_mux_http("192.0.2.10:8080", ["D_Y_2_1"])["D_Y_2_1"] == "93"
    )


def test_default_timeout_is_30_seconds(device):
    assert gruenbeck.device.DEFAULT_TIMEOUT == 30
    device.post(URL, body=ANSWER, match=[matchers.request_kwargs_matcher({"timeout": 30})])

    gruenbeck.device.get_data_from_mux_http(HOST, ["D_Y_2_1"])


def test_timeout_is_passed_to_requests(device):
    device.post(URL, body=ANSWER, match=[matchers.request_kwargs_matcher({"timeout": 2.5})])

    gruenbeck.device.get_data_from_mux_http(HOST, ["D_Y_2_1"], timeout=2.5)


def test_code_element_is_not_a_value(device):
    device.post(URL, body="<data><code>error</code><D_Y_2_1>93</D_Y_2_1></data>")

    # the text of <code> is not checked
    assert gruenbeck.device.get_data_from_mux_http(HOST, ["D_Y_2_1"]) == {"D_Y_2_1": "93"}


def test_values_are_texts_as_sent_by_the_device(device):
    device.post(
        URL,
        body=(
            "<data><code>ok</code><D_C_4_2>16:00</D_C_4_2><D_Y_2_15>-</D_Y_2_15>"
            "<D_Y_2_1> 93 </D_Y_2_1><D_Y_2_2></D_Y_2_2><D_Y_2_3/></data>"
        ),
    )

    result = gruenbeck.device.get_data_from_mux_http(
        HOST, ["D_C_4_2", "D_Y_2_15", "D_Y_2_1", "D_Y_2_2", "D_Y_2_3"]
    )

    # no conversion, no stripping; an element without text gives None
    assert result == {
        "D_C_4_2": "16:00",
        "D_Y_2_15": "-",
        "D_Y_2_1": " 93 ",
        "D_Y_2_2": None,
        "D_Y_2_3": None,
    }


def test_answer_is_not_compared_with_the_requested_parameters(device):
    device.post(URL, body="<data><code>ok</code><D_Y_2_7>12</D_Y_2_7></data>")

    # D_Y_2_1 is missing in the answer, D_Y_2_7 was not requested
    assert gruenbeck.device.get_data_from_mux_http(HOST, ["D_Y_2_1"]) == {"D_Y_2_7": "12"}


def test_repeated_element_keeps_the_last_value(device):
    device.post(URL, body="<data><D_Y_2_1>1</D_Y_2_1><D_Y_2_1>2</D_Y_2_1></data>")

    assert gruenbeck.device.get_data_from_mux_http(HOST, ["D_Y_2_1"]) == {"D_Y_2_1": "2"}


def test_only_direct_children_of_the_root_are_values(device):
    device.post(URL, body="<data><code>ok</code><group><D_Y_2_1>93</D_Y_2_1></group></data>")

    assert gruenbeck.device.get_data_from_mux_http(HOST, ["D_Y_2_1"]) == {"group": None}


@pytest.mark.parametrize(
    "body",
    ["<data><code>ok</code></data>", "<data></data>", "<data/>", "<code>ok</code>"],
)
def test_answer_without_values_is_an_error(device, body):
    device.post(URL, body=body)

    with pytest.raises(ValueError) as err:
        gruenbeck.device.get_data_from_mux_http(HOST, ["D_Y_2_1"])

    assert str(err.value) == "[-] device response contains no values"


@pytest.mark.parametrize(
    "body",
    [
        "",
        "not xml",
        "<data><code>ok</code><D_Y_2_1>93</data>",
        "<data><code>ok</code></data><data></data>",
        "<html><body><p>busy<br></p></body></html>",
    ],
)
def test_invalid_xml_is_an_error(device, body):
    device.post(URL, body=body)

    with pytest.raises(ValueError, match=r"^\[-\] failed to parse xml: ") as err:
        gruenbeck.device.get_data_from_mux_http(HOST, ["D_Y_2_1"])

    assert type(err.value.__cause__).__name__ == "ParseError"


@pytest.mark.parametrize("status", [404, 500, 503])
def test_http_error_status_raises_http_error(device, status):
    device.post(URL, body=ANSWER, status=status)

    with pytest.raises(requests.exceptions.HTTPError) as err:
        gruenbeck.device.get_data_from_mux_http(HOST, ["D_Y_2_1"])

    assert err.value.response is not None
    assert err.value.response.status_code == status


@pytest.mark.parametrize(
    "error",
    [
        requests.exceptions.ConnectTimeout("connect timed out"),
        requests.exceptions.ReadTimeout("read timed out"),
        requests.exceptions.ConnectionError("no route to host"),
    ],
    ids=lambda error: type(error).__name__,
)
def test_timeout_and_connection_errors_are_raised(device, error):
    device.post(URL, body=error)

    with pytest.raises(type(error)) as err:
        gruenbeck.device.get_data_from_mux_http(HOST, ["D_Y_2_1"])

    assert err.value is error
    assert isinstance(err.value, requests.exceptions.RequestException)
