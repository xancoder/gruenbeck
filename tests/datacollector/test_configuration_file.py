import pytest

import datacollector

CONFIGURATION_FILE = '../src/config.json'


def test_check_configuration_file_not_exists():
    configuration_file_nonsense = 'example.json'
    with pytest.raises(FileNotFoundError):
        config = datacollector.check_configuration(configuration_file_nonsense)


def test_check_configuration_file_type():
    config = datacollector.check_configuration(CONFIGURATION_FILE)
    assert isinstance(config, dict)


def test_check_configuration_parameter_not_exists():
    item = 'example'
    config = datacollector.check_configuration(CONFIGURATION_FILE)
    with pytest.raises(KeyError):
        tmp = config[item]


def test_check_configuration_parameter_parameter_file():
    item = 'parameterFile'
    config = datacollector.check_configuration(CONFIGURATION_FILE)
    tmp = config[item]
    assert isinstance(tmp, str)


def test_check_configuration_parameter_data_path():
    item = 'dataPath'
    config = datacollector.check_configuration(CONFIGURATION_FILE)
    tmp = config[item]
    assert isinstance(tmp, str)


def test_check_configuration_parameter_data_file():
    item = 'dataFile'
    config = datacollector.check_configuration(CONFIGURATION_FILE)
    tmp = config[item]
    assert isinstance(tmp, dict)


def test_check_configuration_parameter_softwatersystem():
    item = 'softWaterSystem'
    config = datacollector.check_configuration(CONFIGURATION_FILE)
    tmp = config[item]
    assert isinstance(tmp, dict)
