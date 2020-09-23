import json
import pathlib


def check_configuration(configuration_file: str) -> dict:
    """
    load json into a dictionary from a given valid file path string,
    otherwise throws FileNotFoundError exception
    :rtype: dict
    """
    config_path = pathlib.Path(configuration_file)
    with config_path.open() as json_data_file:
        config = json.load(json_data_file)
    return config
