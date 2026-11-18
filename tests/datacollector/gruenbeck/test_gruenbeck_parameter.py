import pytest

import gruenbeck


def test_check_gruenbeck_parameter_not_exists(tmp_path):
    parameter_file_not_exists = str(tmp_path / 'fileName.csv')
    with pytest.raises(FileNotFoundError):
        device_parameter = gruenbeck.Parameter(parameter_file_not_exists)


def test_gruenbeck_parameter_exists(parameter_file):
    device_parameter = gruenbeck.Parameter(str(parameter_file))
    assert isinstance(device_parameter.path_file, str)
