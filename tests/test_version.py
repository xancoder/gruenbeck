"""version of the package: --version of every command and the first line of the log (P009-S15)"""

import importlib.metadata
import pathlib
import subprocess
import sys
import tomllib

import pytest

from gruenbeck import version

BIN = pathlib.Path(sys.executable).parent
COMMANDS = [
    "gruenbeck-collect",
    "gruenbeck-analyse",
    "gruenbeck-preview-mail",
    "gruenbeck-log-rollover",
]


def project_version(repo_root: pathlib.Path) -> str:
    with (repo_root / "pyproject.toml").open("rb") as pyproject:
        return str(tomllib.load(pyproject)["project"]["version"])


def test_version_is_the_one_of_the_installed_package(repo_root: pathlib.Path) -> None:
    assert version.get_version() == importlib.metadata.version("gruenbeck")
    # uv sync installs the version of pyproject.toml (the release step raises it)
    assert version.get_version() == project_version(repo_root)


def test_version_without_the_installed_package_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", missing)

    assert version.get_version() == "unknown"


@pytest.mark.parametrize("command", COMMANDS)
def test_every_command_prints_its_version(
    command: str, repo_root: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    path = BIN / command
    assert path.exists(), f"{path} is missing: install the package with uv sync"

    result = subprocess.run(
        [str(path), "--version"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == f"{command} {project_version(repo_root)}\n"
    assert result.stderr == ""


@pytest.mark.parametrize("command", COMMANDS)
def test_help_lists_the_version_option(command: str, tmp_path: pathlib.Path) -> None:
    result = subprocess.run(
        [str(BIN / command), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0
    assert "--version" in result.stdout
