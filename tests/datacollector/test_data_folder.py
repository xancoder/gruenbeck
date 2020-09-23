import pathlib

import src.datacollector

DATA_FOLDER = '../data'


def test_check_data_folder_not_exists():
    data_folder_nonsense = './folderName'
    data_path = src.datacollector.check_data_folder(data_folder_nonsense)
    assert data_path.exists() == True
    # clean up
    data_path.rmdir()


def test_check_data_folder_exists():
    data_path = src.datacollector.check_data_folder(DATA_FOLDER)
    assert isinstance(data_path, pathlib.Path)
