import pytest

import gruenbeck

PARAMETER_FILE = '../assets/Gruenbeck_Webserver_Dokumentation.csv'


def test_check_gruenbeck_parameter_not_exists():
    parameter_file_not_exists = './fileName.csv'
    with pytest.raises(FileNotFoundError):
        device_parameter = gruenbeck.Parameter(parameter_file_not_exists)


def test_gruenbeck_parameter_exists():
    device_parameter = gruenbeck.Parameter(PARAMETER_FILE)
    assert isinstance(device_parameter.path_file, str)
