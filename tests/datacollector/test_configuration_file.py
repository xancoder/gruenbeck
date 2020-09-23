import pytest

import src.datacollector

CONFIGURATION_FILE = '../src/config.json'


def test_check_configuration_file_not_exists():
    configuration_file_nonsense = 'example.json'
    with pytest.raises(FileNotFoundError):
        config = src.datacollector.check_configuration(configuration_file_nonsense)


def test_check_configuration_file_type():
    config = src.datacollector.check_configuration(CONFIGURATION_FILE)
    assert isinstance(config, dict)
