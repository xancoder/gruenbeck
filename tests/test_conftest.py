def test_path_fixtures_exist(repo_root, config_example_file, parameter_file):
    assert (repo_root / "pyproject.toml").exists()
    assert config_example_file.exists()
    assert parameter_file.exists()
