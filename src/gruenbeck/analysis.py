"""monthly statistics of the collected water consumption (extra "analysis")"""

import pathlib
import re

from gruenbeck import config as configuration
from gruenbeck import errors

print_pattern_headline = "{:<4} {:<5} {:<4} {:<3} {:<3} {:<3} {:<5}"
print_pattern = "{:>4} {:>5} {:>4.0f} {:>3.0f} {:>3.0f} {:>3.0f} {:>5.0f}"


class AnalysisError(errors.GruenbeckError):
    """nothing to analyse"""


def get_data_files(data_path, prefix):
    """
    find the yearly data files written by the data collector
    :param data_path: data folder (dataPath)
    :param prefix: dataFile.prefix
    :return: sorted list of pathlib.Path of '<prefix>_<year>.csv' in the data folder
    """
    data_path = pathlib.Path(data_path)
    year_file = re.compile(rf"{re.escape(prefix)}_\d{{4}}\.csv")
    return sorted(
        input_file for input_file in data_path.glob("*.csv") if year_file.fullmatch(input_file.name)
    )


def main(config_file):
    # pandas and matplotlib belong to the extra "analysis"; importing them here
    # keeps the module and the help of gruenbeck-analyse usable without it
    import matplotlib.pyplot as plt
    import pandas

    # FileNotFoundError and ConfigurationError go to the caller (gruenbeck.cli.analyse)
    config = configuration.load_configuration(config_file)
    data_file = config.data_file
    data_files = get_data_files(config.data_path, data_file.prefix)
    if not data_files:
        raise AnalysisError(f"no data files '{data_file.prefix}_<year>.csv' in {config.data_path}")

    print(f"data folder: {config.data_path}")
    for input_file in data_files:
        year = input_file.stem.split("_")[-1]
        b = pandas.read_csv(input_file)
        # the columns of dataFile.fieldnames as date and value
        b = b.rename(
            columns={data_file.fieldnames.date: "date", data_file.fieldnames.value: "value"}
        )
        b["date"] = pandas.to_datetime(b["date"], format=data_file.date_pattern)
        b.index = b["date"]
        grouped_df = b.groupby(by=[b.index.year, b.index.month])

        print(print_pattern_headline.format("year", "month", "mean", "min", "max", "std", "sum"))

        x = []
        y = []

        for key, _group in grouped_df:
            x.append(key[1])
            y.append(grouped_df.get_group(key).value.mean())

            print(
                print_pattern.format(
                    key[0],
                    key[1],
                    grouped_df.get_group(key).value.mean(),
                    grouped_df.get_group(key).value.min(),
                    grouped_df.get_group(key).value.max(),
                    grouped_df.get_group(key).value.std(),
                    grouped_df.get_group(key).value.sum(),
                )
            )

        plt.plot(x, y, label=year)

        print(
            print_pattern.format(
                year,
                "-",
                b.value.mean(),
                b.value.min(),
                b.value.max(),
                b.value.std(),
                b.value.sum(),
            )
        )
        print()

    plt.title(r"mean water consumption")
    plt.xlabel("month")
    plt.ylabel("liters")
    plt.grid(True)
    plt.legend()
    plt.show()
