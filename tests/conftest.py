import importlib.util
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def repo_root() -> pathlib.Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def config_example_file(repo_root) -> pathlib.Path:
    """example configuration; the real src/config.json is not versioned"""
    return repo_root / "src" / "config.example.json"


@pytest.fixture(scope="session")
def parameter_file(repo_root) -> pathlib.Path:
    return repo_root / "assets" / "Gruenbeck_Webserver_Dokumentation.csv"


@pytest.fixture
def data_collector():
    """
    src/data-collector.py as a module (the file name is not importable with 'import')
    """
    path = REPO_ROOT / "src" / "data-collector.py"
    spec = importlib.util.spec_from_file_location("data_collector", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
