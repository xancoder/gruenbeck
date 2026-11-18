def test_data_collector_fixture_loads_script(data_collector):
    assert callable(data_collector.main)
    assert callable(data_collector.handle_error)


def test_data_collector_fixture_works_from_any_cwd(data_collector, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert data_collector.logger.name == "data_collector"


def test_path_fixtures_exist(repo_root, config_example_file, parameter_file):
    assert (repo_root / "pyproject.toml").exists()
    assert config_example_file.exists()
    assert parameter_file.exists()
