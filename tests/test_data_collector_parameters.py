import gruenbeck
import pytest

MEMORY = [f"D_Y_2_{n}" for n in range(1, 15)]
CONFIG = {"softWaterSystem": {"host": "device.lan"}, "mail": {}}


@pytest.fixture
def device(data_collector, monkeypatch):
    """fake device; records the parameters of every request"""
    requests = []

    def fetch(host, parameters, timeout):
        requests.append(list(parameters))
        return {name: "1" for name in parameters}

    monkeypatch.setattr(data_collector.gruenbeck, "get_data_from_mux_http", fetch)
    return requests


@pytest.fixture
def error_mails(data_collector, monkeypatch):
    sent = []
    monkeypatch.setattr(
        data_collector.datacollector, "send_mail_text",
        lambda param, subject, text: sent.append(text),
    )
    return sent


def test_parameter_file_lists_all_consumption_rows_of_the_pdf(parameter_file):
    parameter = gruenbeck.Parameter(str(parameter_file))

    assert parameter.get_parameter_by_note("Wasserverbrauch") == [
        "D_Y_1", *MEMORY, "D_Y_2_27",
    ]


@pytest.mark.parametrize("suffix, separator", [(".csv", ","), (".tsv", "\t")])
def test_parameter_files_have_no_commented_rows(parameter_file, suffix, separator):
    lines = parameter_file.with_suffix(suffix).read_text(encoding="utf-8").splitlines()

    assert not [line for line in lines if line.startswith("#")]
    assert f"D_Y_1{separator}read" in "\n".join(lines)
    assert f"D_Y_2_27{separator}read" in "\n".join(lines)


def test_only_the_14_day_memory_is_requested(data_collector, device, parameter_file):
    parameter = gruenbeck.Parameter(str(parameter_file))

    result = data_collector.get_device_data(CONFIG, parameter)

    # plus the device clock for check_device_clock() (P004-S8)
    assert device == [["D_C_4_2", *MEMORY]]
    assert list(result) == ["D_C_4_2", *MEMORY]


def test_missing_memory_parameter_fails_before_asking_the_device(
    data_collector, device, error_mails, parameter_file, tmp_path, caplog
):
    rows = parameter_file.read_text(encoding="utf-8").splitlines(keepends=True)
    without = [row for row in rows if not row.startswith(("D_Y_2_5,", "D_Y_2_12,"))]
    assert len(without) == len(rows) - 2
    reduced = tmp_path / "parameters.csv"
    reduced.write_text("".join(without), encoding="utf-8")

    with pytest.raises(SystemExit) as exit_info:
        data_collector.get_device_data(CONFIG, gruenbeck.Parameter(str(reduced)))

    assert exit_info.value.code == 1
    assert device == []
    message = (
        f"[-] parameter file {reduced} lacks the consumption parameters:"
        " D_Y_2_5, D_Y_2_12"
    )
    assert message in caplog.text
    assert error_mails == [message]
