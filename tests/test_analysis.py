"""
analysis: gruenbeck-analyse, formerly src/data-analyse.py

pandas and matplotlib belong to the extra "analysis" and are not part of the dev
environment, so only the parts without them are tested here.
"""

import importlib.util
import pathlib
import subprocess
import sys

import pytest

from gruenbeck import analysis, cli

BIN = pathlib.Path(sys.executable).parent
HAS_ANALYSIS_EXTRA = importlib.util.find_spec("pandas") is not None


def run_command(cwd, *args):
    path = BIN / "gruenbeck-analyse"
    assert path.exists(), f"{path} is missing: install the package with uv sync"
    return subprocess.run(
        [str(path), *args], cwd=cwd, capture_output=True, text=True, timeout=60, check=False
    )


def test_data_files_are_the_yearly_files_of_the_prefix(tmp_path):
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

    files = analysis.get_data_files({"dataPath": str(tmp_path), "dataFile": {"prefix": "p"}})

    assert files == [tmp_path / "p_2025.csv", tmp_path / "p_2026.csv"]


def test_prefix_is_not_a_pattern(tmp_path):
    (tmp_path / "p.x_2026.csv").write_text("")
    (tmp_path / "pax_2026.csv").write_text("")

    files = analysis.get_data_files({"dataPath": str(tmp_path), "dataFile": {"prefix": "p.x"}})

    assert files == [tmp_path / "p.x_2026.csv"]


def test_help_works_without_the_analysis_extra(tmp_path):
    result = run_command(tmp_path, "--help")

    assert result.returncode == 0
    assert result.stdout.startswith("usage: gruenbeck-analyse ")
    assert "--config-file" in result.stdout
    assert "monthly statistics of the collected water consumption" in result.stdout


@pytest.mark.skipif(HAS_ANALYSIS_EXTRA, reason="the extra analysis is installed")
def test_run_without_the_analysis_extra_fails(tmp_path):
    result = run_command(tmp_path)

    assert result.returncode == 1
    assert "No module named 'matplotlib'" in result.stderr


@pytest.mark.parametrize(
    "argv, config_file",
    [([], "./src/config.json"), (["-c", "other.json"], "other.json")],
)
def test_command_passes_the_config_file_to_the_analysis(monkeypatch, argv, config_file):
    calls: list[str] = []
    monkeypatch.setattr(analysis, "main", calls.append)

    cli.analyse(argv)

    assert calls == [config_file]
