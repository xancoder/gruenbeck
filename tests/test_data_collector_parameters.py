import pytest

# the fixture device is the fake device, so the module is used as gruenbeck.device
import gruenbeck.device
from gruenbeck import mail

MEMORY = [f"D_Y_2_{n}" for n in range(1, 15)]


@pytest.fixture
def device(monkeypatch):
    """fake device; records the parameters of every request"""
    requests = []

    def fetch(host, parameters, timeout, session=None):
        requests.append(list(parameters))
        return {name: "1" for name in parameters}

    monkeypatch.setattr(gruenbeck.device, "get_data_from_mux_http", fetch)
    return requests


@pytest.fixture
def error_mails(monkeypatch):
    sent = []
    monkeypatch.setattr(
        mail,
        "send_mail",
        lambda settings, subject, text, attachments=(): sent.append(text),
    )
    return sent


def test_parameter_file_lists_all_consumption_rows_of_the_pdf(parameter_file):
    parameter = gruenbeck.device.Parameter(str(parameter_file))

    assert parameter.get_parameter_by_note("Wasserverbrauch") == [
        "D_Y_1",
        *MEMORY,
        "D_Y_2_27",
    ]


def test_parameter_file_has_no_commented_rows(parameter_file):
    lines = parameter_file.read_text(encoding="utf-8").splitlines()

    assert not [line for line in lines if line.startswith("#")]
    assert "D_Y_1,read" in "\n".join(lines)
    assert "D_Y_2_27,read" in "\n".join(lines)


def test_only_the_14_day_memory_is_requested(device, parameter_file):
    parameter = gruenbeck.device.Parameter(str(parameter_file))

    result = gruenbeck.device.get_device_data("device.lan", parameter, 30, 5, 5)

    # plus the device clock for check_device_clock() (P004-S8)
    assert device == [["D_C_4_2", *MEMORY]]
    assert list(result) == ["D_C_4_2", *MEMORY]


def test_missing_memory_parameter_fails_before_asking_the_device(
    device, error_mails, parameter_file, tmp_path, caplog
):
    rows = parameter_file.read_text(encoding="utf-8").splitlines(keepends=True)
    without = [row for row in rows if not row.startswith(("D_Y_2_5,", "D_Y_2_12,"))]
    assert len(without) == len(rows) - 2
    reduced = tmp_path / "parameters.csv"
    reduced.write_text("".join(without), encoding="utf-8")

    with pytest.raises(gruenbeck.device.DeviceError) as err:
        gruenbeck.device.get_device_data(
            "device.lan", gruenbeck.device.Parameter(str(reduced)), 30, 5, 5
        )

    assert device == []
    message = f"parameter file {reduced} lacks the consumption parameters: D_Y_2_5, D_Y_2_12"
    assert str(err.value) == message
    # the error mail is sent by main()
    assert error_mails == []
