"""
analysis: gruenbeck-analyse, formerly src/data-analyse.py

pandas and matplotlib belong to the extra "analysis". The tests that really need them skip
without the extra (uv sync); CI installs it (uv sync --all-extras). A missing extra is
simulated in-process, so that test runs in both environments.
"""

import collections.abc
import pathlib
import subprocess
import sys
import typing

import pytest

from gruenbeck import analysis, cli

BIN = pathlib.Path(sys.executable).parent


def run_command(cwd: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    path = BIN / "gruenbeck-analyse"
    assert path.exists(), f"{path} is missing: install the package with uv sync"
    return subprocess.run(
        [str(path), *args], cwd=cwd, capture_output=True, text=True, timeout=60, check=False
    )


def test_help_works_without_the_analysis_extra(tmp_path: pathlib.Path) -> None:
    result = run_command(tmp_path, "--help")

    assert result.returncode == 0
    assert result.stdout.startswith("usage: gruenbeck-analyse ")
    assert "--config-file" in result.stdout
    assert "monthly statistics of the collected water consumption" in result.stdout


def test_run_without_the_analysis_extra_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    # None in sys.modules makes the import fail as if the package was not installed, also
    # if the extra is installed and the modules are already imported
    for name in ("matplotlib", "matplotlib.pyplot", "pandas"):
        monkeypatch.setitem(sys.modules, name, None)

    with pytest.raises(ModuleNotFoundError) as excinfo:
        cli.analyse(["--config-file", str(tmp_path / "config.json")])

    # the import comes before the configuration is read: no configuration file is needed
    assert (excinfo.value.name or "").split(".")[0] == "matplotlib"


@pytest.mark.parametrize(
    "argv, config_file",
    [([], "./src/config.json"), (["-c", "other.json"], "other.json")],
)
def test_command_passes_the_config_file_to_the_analysis(
    monkeypatch: pytest.MonkeyPatch, argv: typing.Any, config_file: str
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(analysis, "main", calls.append)

    cli.analyse(argv)

    assert calls == [config_file]


@pytest.fixture
def plots(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[list[typing.Any], list[typing.Any], str]]:
    """matplotlib without a window; records the plotted lines"""
    matplotlib = pytest.importorskip("matplotlib")
    pytest.importorskip("pandas")
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    lines: list[tuple[list[typing.Any], list[typing.Any], str]] = []
    monkeypatch.setattr(plt, "plot", lambda x, y, label: lines.append((list(x), list(y), label)))
    monkeypatch.setattr(plt, "show", lambda: None)
    monkeypatch.setattr(plt, "legend", lambda: None)
    return lines


def test_statistics_use_the_columns_and_the_date_pattern_of_the_configuration(
    plots: list[tuple[list[typing.Any], list[typing.Any], str]],
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
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
