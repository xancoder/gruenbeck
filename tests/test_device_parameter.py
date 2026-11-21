import pytest

from gruenbeck import device

HEADER = "parameter,access,device,value,unit,code,note\n"


def test_check_gruenbeck_parameter_not_exists(tmp_path):
    parameter_file_not_exists = str(tmp_path / "fileName.csv")
    with pytest.raises(FileNotFoundError):
        device.Parameter(parameter_file_not_exists)


def test_gruenbeck_parameter_exists(parameter_file):
    device_parameter = device.Parameter(str(parameter_file))
    assert isinstance(device_parameter.path_file, str)


# --- characterization of device.Parameter (P006-S1) ------------------------------


@pytest.fixture
def write_parameters(tmp_path):
    """writes a parameter file with the header of the assets file and the given rows"""

    def write(*rows):
        path = tmp_path / "parameters.csv"
        path.write_text(HEADER + "".join(f"{row}\n" for row in rows), encoding="utf-8")
        return path

    return write


def test_rows_become_parameters_with_all_columns(write_parameters):
    path = write_parameters(
        "D_Y_2_1,read,,Int,[l],,Wasserverbrauch gestern",
        "D_C_4_2,read/write,dev,String,(XX:XX),c1,Uhrzeit",
    )

    parameter = device.Parameter(str(path))

    assert parameter.parameters == {
        "D_Y_2_1": {
            "access": "read",
            "device": "",
            "value": "Int",
            "unit": "[l]",
            "code": "",
            "note": "Wasserverbrauch gestern",
        },
        "D_C_4_2": {
            "access": "read/write",
            "device": "dev",
            "value": "String",
            "unit": "(XX:XX)",
            "code": "c1",
            "note": "Uhrzeit",
        },
    }
    assert parameter.get_parameter("D_C_4_2") is parameter.parameters["D_C_4_2"]


def test_path_is_kept_as_given(write_parameters):
    path = write_parameters("D_Y_2_1,read,,Int,[l],,gestern")

    assert device.Parameter(str(path)).path_file == str(path)
    assert device.Parameter(path).path_file is path


def test_empty_and_commented_rows_are_skipped(write_parameters):
    path = write_parameters(
        "D_Y_2_1,read,,Int,[l],,gestern",
        ",read,,Int,[l],,without code",
        ",,,,,,",
        "#D_Y_2_2,read,,Int,[l],,commented",
        "# a comment",
        "",
        "D_Y_2_3,read,,Int,[l],,vor 3 Tagen",
    )

    parameter = device.Parameter(str(path))

    assert list(parameter.get_parameter_list()) == ["D_Y_2_1", "D_Y_2_3"]
    assert parameter.get_count() == 2


def test_list_count_and_lookup(write_parameters):
    path = write_parameters(
        "D_D_1,read/write,,Double,[°dH],,Rohwasserhärte",
        "D_Y_2_1,read,,Int,[l],,Wasserverbrauch gestern",
        "D_Y_2_2,read,,Int,[l],,Wasserverbrauch vor 2 Tagen",
    )

    parameter = device.Parameter(str(path))

    assert parameter.get_count() == 3
    # the keys of the dictionary, in the order of the file
    assert parameter.get_parameter_list() == parameter.parameters.keys()
    assert list(parameter.get_parameter_list()) == ["D_D_1", "D_Y_2_1", "D_Y_2_2"]
    assert "D_Y_2_2" in parameter.get_parameter_list()
    assert parameter.get_parameter("D_D_1")["unit"] == "[°dH]"


def test_unknown_parameter_raises_key_error(write_parameters):
    parameter = device.Parameter(str(write_parameters("D_Y_2_1,read,,Int,[l],,gestern")))

    with pytest.raises(KeyError):
        parameter.get_parameter("D_Y_2_2")


def test_parameters_by_note_are_a_case_sensitive_substring_match(write_parameters):
    path = write_parameters(
        "D_Y_2_2,read,,Int,[l],,Wasserverbrauch vor 2 Tagen",
        "D_D_1,read/write,,Double,[°dH],,Rohwasserhärte",
        "D_Y_2_1,read,,Int,[l],,Wasserverbrauch gestern",
        "D_Y_1,read,,Int,[l],,Wasserverbrauch",
    )

    parameter = device.Parameter(str(path))

    assert parameter.get_parameter_by_note("Wasserverbrauch") == ["D_Y_2_2", "D_Y_2_1", "D_Y_1"]
    assert parameter.get_parameter_by_note("gestern") == ["D_Y_2_1"]
    assert parameter.get_parameter_by_note("wasserverbrauch") == []
    assert parameter.get_parameter_by_note("") == ["D_Y_2_2", "D_D_1", "D_Y_2_1", "D_Y_1"]


def test_repeated_parameter_keeps_the_last_row_at_the_first_place(write_parameters):
    path = write_parameters(
        "D_Y_2_1,read,,Int,[l],,first",
        "D_Y_2_2,read,,Int,[l],,other",
        "D_Y_2_1,read,,Int,[l],,second",
    )

    parameter = device.Parameter(str(path))

    assert list(parameter.get_parameter_list()) == ["D_Y_2_1", "D_Y_2_2"]
    assert parameter.get_parameter("D_Y_2_1")["note"] == "second"
    assert parameter.get_count() == 2


def test_short_row_gives_none_for_the_missing_columns(write_parameters):
    parameter = device.Parameter(str(write_parameters("D_Y_2_1,read")))

    assert parameter.get_parameter("D_Y_2_1") == {
        "access": "read",
        "device": None,
        "value": None,
        "unit": None,
        "code": None,
        "note": None,
    }


def test_missing_column_raises_key_error(tmp_path):
    path = tmp_path / "parameters.csv"
    path.write_text("parameter,access,value\nD_Y_2_1,read,Int\n", encoding="utf-8")

    with pytest.raises(KeyError, match="device"):
        device.Parameter(str(path))


def test_empty_file_has_no_parameters(tmp_path):
    path = tmp_path / "parameters.csv"
    path.write_text("", encoding="utf-8")

    parameter = device.Parameter(str(path))

    assert parameter.get_count() == 0
    assert parameter.get_parameter_by_note("Wasserverbrauch") == []


def test_instances_do_not_share_their_parameters(write_parameters, tmp_path):
    first = device.Parameter(str(write_parameters("D_Y_2_1,read,,Int,[l],,gestern")))
    other_file = tmp_path / "other.csv"
    other_file.write_text(HEADER + "D_Y_2_2,read,,Int,[l],,vor 2 Tagen\n", encoding="utf-8")
    second = device.Parameter(str(other_file))

    assert list(first.get_parameter_list()) == ["D_Y_2_1"]
    assert list(second.get_parameter_list()) == ["D_Y_2_2"]
    # the class attribute count is not used
    assert device.Parameter.count == 0


def test_assets_file_has_the_parameters_the_collector_reads(parameter_file):
    parameter = device.Parameter(str(parameter_file))

    assert parameter.get_parameter("D_C_4_2") == {
        "access": "read/write",
        "device": "",
        "value": "String",
        "unit": "(XX:XX)",
        "code": "",
        "note": "Uhrzeit",
    }
    for n in range(1, 15):
        assert parameter.get_parameter(f"D_Y_2_{n}")["access"] == "read"
        assert parameter.get_parameter(f"D_Y_2_{n}")["unit"] == "[l]"
