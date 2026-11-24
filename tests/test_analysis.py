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


def test_output_and_lines_of_two_years(
    plots: list[tuple[list[typing.Any], list[typing.Any], str]],
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """characterization (P009-S11): the exact output, whatever the code looks like inside"""
    prefix = config_data["dataFile"]["prefix"]
    data_folder = tmp_path / "data"
    data_folder.mkdir()
    (data_folder / f"{prefix}_2025.csv").write_text(
        "date,value\n2025-11-30,100\n2025-12-01,50\n2025-12-02,70\n2025-12-03,33\n"
    )
    (data_folder / f"{prefix}_2026.csv").write_text(
        "date,value\n2026-01-01,120\n2026-01-02,90\n2026-02-01,200\n"
        "2026-03-01,10\n2026-03-02,11\n2026-03-03,12\n"
    )
    (data_folder / "other_2026.csv").write_text("date,value\n2026-01-01,999\n")

    analysis.main(str(write_config(config_data)))

    assert capsys.readouterr().out.splitlines() == [
        f"data folder: {data_folder}",
        "year month mean min max std sum  ",
        "2025    11  100 100 100 nan   100",
        "2025    12   51  33  70  19   153",
        "2025     -   63  33 100  29   253",
        "",
        "year month mean min max std sum  ",
        "2026     1  105  90 120  21   210",
        "2026     2  200 200 200 nan   200",
        "2026     3   11  10  12   1    33",
        "2026     -   74  10 200  78   443",
        "",
    ]
    assert plots == [
        ([11, 12], [100.0, 51.0], "2025"),
        ([1, 2, 3], [105.0, 200.0, 11.0], "2026"),
    ]


def test_folder_without_yearly_files_is_an_error(
    plots: list[tuple[list[typing.Any], list[typing.Any], str]],
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
    tmp_path: pathlib.Path,
) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "other_2026.csv").write_text("date,value\n2026-01-01,1\n")

    with pytest.raises(analysis.AnalysisError) as excinfo:
        analysis.main(str(write_config(config_data)))

    prefix = config_data["dataFile"]["prefix"]
    assert str(excinfo.value) == f"no data files '{prefix}_<year>.csv' in {tmp_path / 'data'}"
    assert plots == []


def test_analysis_needs_no_smtp_password(
    plots: list[tuple[list[typing.Any], list[typing.Any], str]],
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """after the password moved into a credential, the command runs without it"""
    del config_data["mail"]["senderPassword"]
    prefix = config_data["dataFile"]["prefix"]
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / f"{prefix}_2026.csv").write_text("date,value\n2026-01-01,5\n")

    assert cli.analyse(["-c", str(write_config(config_data))]) == 0

    assert plots == [([1], [5.0], "2026")]
    assert capsys.readouterr().out.startswith("data folder: ")
