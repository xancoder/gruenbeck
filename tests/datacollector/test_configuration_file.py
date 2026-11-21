import pytest

import datacollector


def test_check_configuration_file_not_exists(tmp_path):
    configuration_file_nonsense = str(tmp_path / "example.json")
    with pytest.raises(FileNotFoundError):
        datacollector.check_configuration(configuration_file_nonsense)


def test_check_configuration_file_type(config_example_file):
    config = datacollector.check_configuration(str(config_example_file))
    assert isinstance(config, dict)


def test_check_configuration_parameter_not_exists(config_example_file):
    item = "example"
    config = datacollector.check_configuration(str(config_example_file))
    with pytest.raises(KeyError):
        config[item]


def test_check_configuration_parameter_parameter_file(config_example_file):
    item = "parameterFile"
    config = datacollector.check_configuration(str(config_example_file))
    tmp = config[item]
    assert isinstance(tmp, str)


def test_check_configuration_parameter_data_path(config_example_file):
    item = "dataPath"
    config = datacollector.check_configuration(str(config_example_file))
    tmp = config[item]
    assert isinstance(tmp, str)


def test_check_configuration_parameter_data_file(config_example_file):
    item = "dataFile"
    config = datacollector.check_configuration(str(config_example_file))
    tmp = config[item]
    assert isinstance(tmp, dict)


def test_check_configuration_parameter_softwatersystem(config_example_file):
    item = "softWaterSystem"
    config = datacollector.check_configuration(str(config_example_file))
    tmp = config[item]
    assert isinstance(tmp, dict)
