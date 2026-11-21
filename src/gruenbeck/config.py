"""configuration file of the data collector"""

import json
import pathlib


def check_configuration(configuration_file: str) -> dict:
    """
    load json into a dictionary from a given valid file path string,
    otherwise throws FileNotFoundError exception
    :param configuration_file: string of path to configuration
    :return: dict
    """
    path_object = pathlib.Path(configuration_file)
    with path_object.open() as json_data_file:
        config = json.load(json_data_file)
    return config
