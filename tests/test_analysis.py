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

    files = analysis.get_data_files(tmp_path, "p")

    assert files == [tmp_path / "p_2025.csv", tmp_path / "p_2026.csv"]


def test_prefix_is_not_a_pattern(tmp_path):
    (tmp_path / "p.x_2026.csv").write_text("")
    (tmp_path / "pax_2026.csv").write_text("")

    files = analysis.get_data_files(str(tmp_path), "p.x")

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


@pytest.fixture
def plots(monkeypatch):
    """matplotlib without a window; records the plotted lines"""
    matplotlib = pytest.importorskip("matplotlib")
    pytest.importorskip("pandas")
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    lines = []
    monkeypatch.setattr(plt, "plot", lambda x, y, label: lines.append((list(x), list(y), label)))
    monkeypatch.setattr(plt, "show", lambda: None)
    monkeypatch.setattr(plt, "legend", lambda: None)
    return lines


def test_statistics_use_the_columns_and_the_date_pattern_of_the_configuration(
    plots, config_data, write_config, tmp_path, capsys
):
    # only with the extra "analysis" (uv sync --extra analysis)
    config_data["dataFile"].update(
        prefix="p", datePattern="%d.%m.%Y", fieldnames={"date": "day", "value": "litres"}
    )
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "p_2026.csv").write_text(
        "day,litres\n30.11.2026,100\n01.12.2026,50\n02.12.2026,70\n"
    )

    analysis.main(str(write_config(config_data)))

    out = capsys.readouterr().out.splitlines()
    assert out[0] == f"data folder: {tmp_path / 'data'}"
    assert [line.split() for line in out[2:5]] == [
        ["2026", "11", "100", "100", "100", "nan", "100"],
        ["2026", "12", "60", "50", "70", "14", "120"],
        ["2026", "-", "73", "50", "100", "25", "220"],
    ]
    assert plots == [([11, 12], [100.0, 60.0], "2026")]
