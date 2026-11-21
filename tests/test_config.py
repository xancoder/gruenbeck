import pytest

from gruenbeck import config as configuration


def test_check_configuration_file_not_exists(tmp_path):
    configuration_file_nonsense = str(tmp_path / "example.json")
    with pytest.raises(FileNotFoundError):
        configuration.check_configuration(configuration_file_nonsense)


def test_check_configuration_file_type(config_example_file):
    config = configuration.check_configuration(str(config_example_file))
    assert isinstance(config, dict)


def test_check_configuration_parameter_not_exists(config_example_file):
    item = "example"
    config = configuration.check_configuration(str(config_example_file))
    with pytest.raises(KeyError):
        config[item]


def test_check_configuration_parameter_parameter_file(config_example_file):
    item = "parameterFile"
    config = configuration.check_configuration(str(config_example_file))
    tmp = config[item]
    assert isinstance(tmp, str)


def test_check_configuration_parameter_data_path(config_example_file):
    item = "dataPath"
    config = configuration.check_configuration(str(config_example_file))
    tmp = config[item]
    assert isinstance(tmp, str)


def test_check_configuration_parameter_data_file(config_example_file):
    item = "dataFile"
    config = configuration.check_configuration(str(config_example_file))
    tmp = config[item]
    assert isinstance(tmp, dict)


def test_check_configuration_parameter_softwatersystem(config_example_file):
    item = "softWaterSystem"
    config = configuration.check_configuration(str(config_example_file))
    tmp = config[item]
    assert isinstance(tmp, dict)
