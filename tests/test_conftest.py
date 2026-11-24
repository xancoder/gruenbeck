import pathlib


def test_path_fixtures_exist(
    repo_root: pathlib.Path, config_example_file: pathlib.Path, parameter_file: pathlib.Path
) -> None:
    assert (repo_root / "pyproject.toml").exists()
    assert config_example_file.exists()
    assert parameter_file.exists()
