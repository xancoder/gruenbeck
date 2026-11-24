"""yearly data files <prefix>_<year>.csv in the data folder"""

import collections.abc
import csv
import datetime
import logging
import os
import pathlib
import shutil

from gruenbeck import config, errors

logger = logging.getLogger(__name__)


class StorageError(errors.GruenbeckError):
    """the data folder or a yearly data file is not usable (e.g. columns, dates)"""


def date_of(text: str, date_pattern: str) -> datetime.date:
    """
    the day of a date text of the yearly files
    :raises ValueError: the text is not exactly what date_pattern gives for a day
    """
    day = datetime.datetime.strptime(text, date_pattern).date()
    if day.strftime(date_pattern) != text:
        raise ValueError(f"{text!r} is not written as {date_pattern!r}")
    return day


def check_data_folder(data_folder: str | os.PathLike[str]) -> pathlib.Path:
    """
    create an output folder if not exists
    :param data_folder: folder to store data
    :return: object: pathlib.Path of the given string
    """
    path_object = pathlib.Path(data_folder)
    if not path_object.exists():
        path_object.mkdir()
    return path_object


def get_data_file(data_path: str | os.PathLike[str], prefix: str, year: int | str) -> pathlib.Path:
    """path of the yearly data file"""
    return pathlib.Path(f"{data_path}/{prefix}_{year}.csv")


def list_csv_files(data_folder: pathlib.Path) -> list[pathlib.Path]:
    """
    the csv files directly in the data folder (not in subfolders), sorted by name
    :raises StorageError: the data folder does not exist or is not a folder
    """
    if not data_folder.is_dir():
        raise StorageError(f"data folder does not exist or is not a directory: {data_folder}")
    return sorted(data_folder.glob("*.csv"))


def read_data_file(
    file_obj: pathlib.Path, fieldnames: config.FieldNames, date_pattern: str
) -> dict[str, int | str]:
    """
    stored values of one yearly file
    :param fieldnames: column names of date and value (dataFile.fieldnames)
    :param date_pattern: format of the dates (dataFile.datePattern)
    :return: dictionary of date text and value (int if numeric), empty without file
    :raises StorageError: a column is missing, or a date does not match date_pattern
    """
    data: dict[str, int | str] = {}
    if file_obj.exists():
        with file_obj.open(mode="r", newline="", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            columns = reader.fieldnames or []
            missing = [name for name in (fieldnames.date, fieldnames.value) if name not in columns]
            # an empty file has no header and no values
            if missing and columns:
                raise StorageError(
                    f"{file_obj} has no column {', '.join(map(repr, missing))} of"
                    f" dataFile.fieldnames (columns: {', '.join(columns)})"
                )
            for row in reader:
                text = row[fieldnames.date]
                try:
                    date_of(text, date_pattern)
                except (TypeError, ValueError):  # TypeError: short row without date
                    raise StorageError(
                        f"{file_obj}, line {reader.line_num}: the date {text!r} does not match"
                        f" dataFile.datePattern {date_pattern!r}"
                    ) from None
                value = row[fieldnames.value]
                data[text] = int(value) if value.isnumeric() else value
    return data


def write_data(
    file_object: pathlib.Path,
    fieldnames: config.FieldNames,
    data: collections.abc.Mapping[str, int | str],
    date_pattern: str,
) -> None:
    """
    write data to csv file, sorted by date
    :param file_object: pathlib.Path of output file
    :param fieldnames: column names of date and value (dataFile.fieldnames)
    :param data: dictionary of date text and value
    :param date_pattern: format of the date texts (dataFile.datePattern)
    :raises StorageError: a date text does not match date_pattern (nothing is written)
    """
    days = {}
    for text in data:
        try:
            days[text] = date_of(text, date_pattern)
        except ValueError:
            raise StorageError(
                f"the date {text!r} does not match dataFile.datePattern {date_pattern!r}"
            ) from None
    # build data structure to write
    write_list = [
        {fieldnames.date: text, fieldnames.value: data[text]}
        for text in sorted(data, key=days.__getitem__)
    ]

    # write into a temporary file next to the target and replace the target
    # afterwards, so an interruption never leaves a truncated data file
    logger.info("data to write: %s", data)
    tmp_file = file_object.with_name(f".{file_object.name}.tmp")
    try:
        with tmp_file.open(mode="w", newline="", encoding="utf-8") as csv_out_file:
            writer = csv.DictWriter(csv_out_file, fieldnames=[fieldnames.date, fieldnames.value])
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
