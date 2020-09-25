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


def check_data_folder(data_folder: str) -> pathlib.Path:
    """
    create an output folder if not exists
    :param data_folder: string of folder to store data
    :return: object: pathlib.Path of the given string
    """
    path_object = pathlib.Path(data_folder)
    if not path_object.exists():
        path_object.mkdir()
    return path_object
