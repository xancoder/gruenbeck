import pathlib

from gruenbeck import storage


def test_check_data_folder_not_exists(tmp_path):
    data_folder = tmp_path / "folderName"
    data_path = storage.check_data_folder(str(data_folder))
    assert data_path.exists()
    assert data_path == data_folder


def test_check_data_folder_exists(tmp_path):
    data_path = storage.check_data_folder(str(tmp_path))
    assert isinstance(data_path, pathlib.Path)
    assert data_path.exists()
