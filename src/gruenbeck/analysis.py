"""
monthly statistics of the collected water consumption (extra "analysis")

For every yearly file it prints the statistics of each month and of the whole year, and it
plots the mean consumption per month with one line per year. pandas and matplotlib belong to
the extra "analysis" and ship no type information, so the data frames and the plot module are
typed as `typing.Any`.
"""

import dataclasses
import os
import pathlib
import types
import typing

from gruenbeck import config as configuration
from gruenbeck import errors, storage

# the statistics of one period, in the order of the columns of the table
STATISTIC_NAMES = ("mean", "min", "max", "std", "sum")
HEADLINE_COLUMNS = ("year", "month", *STATISTIC_NAMES)
HEADLINE_FORMAT = "{:<4} {:<5} {:<4} {:<3} {:<3} {:<3} {:<5}"
ROW_FORMAT = "{:>4} {:>5} {:>4.0f} {:>3.0f} {:>3.0f} {:>3.0f} {:>5.0f}"

# a pandas data frame with the columns "date" (datetime) and "value"
Frame = typing.Any


class AnalysisError(errors.GruenbeckError):
    """nothing to analyse"""


@dataclasses.dataclass(frozen=True)
class Statistics:
    """mean, minimum, maximum, standard deviation and sum of the values of a period"""

    mean: float
    minimum: float
    maximum: float
    std: float
    total: float


@dataclasses.dataclass(frozen=True)
class MonthStatistics:
    """the statistics of one month; the year comes from the dates, not from the file name"""

    year: int
    month: int
    statistics: Statistics


@dataclasses.dataclass(frozen=True)
class YearStatistics:
    """the statistics of the months and of the whole yearly file"""

    label: str
    months: list[MonthStatistics]
    total: Statistics


def read_year_file(
    pandas: types.ModuleType, path: pathlib.Path, data_file: configuration.DataFile
) -> Frame:
    """
    read a yearly file
    :return: the data frame with the columns of dataFile.fieldnames as "date" and "value"
    """
    frame = pandas.read_csv(path).rename(
        columns={data_file.fieldnames.date: "date", data_file.fieldnames.value: "value"}
    )
    frame["date"] = pandas.to_datetime(frame["date"], format=data_file.date_pattern)
    return frame


def calculate(frame: Frame, label: str) -> YearStatistics:
    """the statistics of every month and of the whole file; one aggregation each"""
    dates = frame["date"].dt
    per_month = frame["value"].groupby([dates.year, dates.month]).agg(list(STATISTIC_NAMES))
    months = [
        MonthStatistics(int(year), int(month), Statistics(*row))
        for (year, month), row in per_month.iterrows()
    ]
    return YearStatistics(label, months, Statistics(*frame["value"].agg(list(STATISTIC_NAMES))))


def format_row(year: int | str, month: int | str, statistics: Statistics) -> str:
    """one line of the table; the whole year has "-" instead of the month"""
    return ROW_FORMAT.format(
        year,
        month,
        statistics.mean,
        statistics.minimum,
        statistics.maximum,
        statistics.std,
        statistics.total,
    )


def format_year(year: YearStatistics) -> list[str]:
    """the lines printed for a file: headline, the months, the whole year and an empty line"""
    return [
        HEADLINE_FORMAT.format(*HEADLINE_COLUMNS),
        *(format_row(m.year, m.month, m.statistics) for m in year.months),
        format_row(year.label, "-", year.total),
        "",
    ]


def draw_chart(plt: types.ModuleType, years: list[YearStatistics]) -> None:
    """plot the mean per month, one line per year, and show the chart"""
    for year in years:
        plt.plot(
            [m.month for m in year.months],
            [m.statistics.mean for m in year.months],
            label=year.label,
        )
    plt.title(r"mean water consumption")
    plt.xlabel("month")
    plt.ylabel("liters")
    plt.grid(True)
    plt.legend()
    plt.show()


def main(config_file: str | os.PathLike[str]) -> None:
    # pandas and matplotlib belong to the extra "analysis"; importing them here
    # keeps the module and the help of gruenbeck-analyse usable without it
    import matplotlib.pyplot as plt
    import pandas

    # FileNotFoundError and ConfigurationError go to the caller (gruenbeck.cli.analyse)
    config = configuration.load_configuration(config_file)
    data_file = config.data_file
    paths = storage.list_year_files(config.data_path, data_file.prefix)
    if not paths:
        raise AnalysisError(f"no data files '{data_file.prefix}_<year>.csv' in {config.data_path}")

    print(f"data folder: {config.data_path}")
    years = []
    for path in paths:
        frame = read_year_file(pandas, path, data_file)
        year = calculate(frame, path.stem.split("_")[-1])
        print("\n".join(format_year(year)))
        years.append(year)

    draw_chart(plt, years)
