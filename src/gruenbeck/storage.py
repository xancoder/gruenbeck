"""yearly data files <prefix>_<year>.csv in the data folder"""

import csv
import logging
import os
import pathlib
import shutil

logger = logging.getLogger(__name__)


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


def get_data_file(config, data_path, year):
    """path of the yearly data file"""
    return pathlib.Path(f"{data_path}/{config['dataFile']['prefix']}_{year}.csv")


def read_data_file(file_obj, fieldnames):
    """
    stored values of one yearly file
    :return: dictionary of date text and value (int if numeric), empty without file
    """
    data = {}
    if file_obj.exists():
        with file_obj.open(mode="r", newline="", encoding="utf-8") as csv_file:
            for row in csv.DictReader(csv_file):
                value = row[fieldnames["value"]]
                data[row[fieldnames["date"]]] = int(value) if value.isnumeric() else value
    return data


def write_data(file_object: pathlib.Path, fieldnames: dict, data: dict) -> None:
    """
    write data to csv file
    :param file_object: pathlib.Path of output file
    :param fieldnames: fieldnames as column headers
    :param data: dictionary data to write
    """
    # build data structure to write
    write_list = []
    for item in sorted(data):
        write_list.append({fieldnames["date"]: item, fieldnames["value"]: data[item]})

    # write into a temporary file next to the target and replace the target
    # afterwards, so an interruption never leaves a truncated data file
    logger.info(f"[*] data to write: {data}")
    tmp_file = file_object.with_name(f".{file_object.name}.tmp")
    try:
        with tmp_file.open(mode="w", newline="", encoding="utf-8") as csv_out_file:
            writer = csv.DictWriter(csv_out_file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(write_list)
            csv_out_file.flush()
            os.fsync(csv_out_file.fileno())
        if file_object.exists():
            shutil.copymode(file_object, tmp_file)
        os.replace(tmp_file, file_object)
    except BaseException:
        tmp_file.unlink(missing_ok=True)
        raise
