import pathlib

import pytest

from gruenbeck import storage


def test_check_data_folder_not_exists(tmp_path: pathlib.Path) -> None:
    data_folder = tmp_path / "folderName"
    data_path = storage.check_data_folder(str(data_folder))
    assert data_path.exists()
    assert data_path == data_folder


def test_check_data_folder_exists(tmp_path: pathlib.Path) -> None:
    data_path = storage.check_data_folder(str(tmp_path))
    assert isinstance(data_path, pathlib.Path)
    assert data_path.exists()


def test_list_csv_files_gives_the_csv_files_of_the_folder_sorted_by_name(
    tmp_path: pathlib.Path,
) -> None:
    (tmp_path / "b_2026.csv").write_text("b")
    (tmp_path / "a_2026.csv").write_text("a")
    (tmp_path / "a_2025.csv").write_text("a")
    (tmp_path / "notes.txt").write_text("not a csv file")
    (tmp_path / "data.csv.bak").write_text("not a csv file")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "deeper.csv").write_text("in a subfolder")

    assert storage.list_csv_files(tmp_path) == [
        tmp_path / "a_2025.csv",
        tmp_path / "a_2026.csv",
        tmp_path / "b_2026.csv",
    ]


def test_list_csv_files_of_an_empty_folder_is_empty(tmp_path: pathlib.Path) -> None:
    assert storage.list_csv_files(tmp_path) == []


@pytest.mark.parametrize("kind", ["missing", "file"])
def test_list_csv_files_without_a_data_folder_is_an_error(
    tmp_path: pathlib.Path, kind: str
) -> None:
    folder = tmp_path / "data"
    if kind == "file":
        folder.write_text("")

    with pytest.raises(storage.StorageError) as err:
        storage.list_csv_files(folder)

    assert str(err.value) == f"data folder does not exist or is not a directory: {folder}"


def test_year_files_are_the_yearly_files_of_the_prefix(tmp_path: pathlib.Path) -> None:
    for name in (
        "p_2026.csv",
        "p_2025.csv",
        "p_2025.csv.20261121.bak",
        "p_26.csv",
        "q_2026.csv",
        "p_2026_copy.csv",
        "notes.txt",
    ):
        (tmp_path / name).write_text("date,value\n")

    files = storage.list_year_files(tmp_path, "p")

    assert files == [tmp_path / "p_2025.csv", tmp_path / "p_2026.csv"]


def test_prefix_is_not_a_pattern(tmp_path: pathlib.Path) -> None:
    (tmp_path / "p.x_2026.csv").write_text("")
    (tmp_path / "pax_2026.csv").write_text("")

    files = storage.list_year_files(str(tmp_path), "p.x")

    assert files == [tmp_path / "p.x_2026.csv"]


def test_year_files_of_a_missing_folder_is_empty(tmp_path: pathlib.Path) -> None:
    assert storage.list_year_files(tmp_path / "missing", "p") == []
