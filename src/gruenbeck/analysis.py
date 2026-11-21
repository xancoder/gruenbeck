"""monthly statistics of the collected water consumption (extra "analysis")"""

import pathlib
import re
import sys

from gruenbeck import config as configuration

print_pattern_headline = "{:<4} {:<5} {:<4} {:<3} {:<3} {:<3} {:<5}"
print_pattern = "{:>4} {:>5} {:>4.0f} {:>3.0f} {:>3.0f} {:>3.0f} {:>5.0f}"


def get_data_files(config):
    """
    find the yearly data files written by the data collector
    :param config: dictionary of the configuration
    :return: sorted list of pathlib.Path of '<prefix>_<year>.csv' in the data folder
    """
    data_path = pathlib.Path(config["dataPath"])
    year_file = re.compile(rf"{re.escape(config['dataFile']['prefix'])}_\d{{4}}\.csv")
    return sorted(
        input_file for input_file in data_path.glob("*.csv") if year_file.fullmatch(input_file.name)
    )


def main(config_file):
    # pandas and matplotlib belong to the extra "analysis"; importing them here
    # keeps the module and the help of gruenbeck-analyse usable without it
    import matplotlib.pyplot as plt
    import pandas

    try:
        config = configuration.check_configuration(config_file)
        data_files = get_data_files(config)
    except FileNotFoundError as err:
        sys.exit(f"[-] no configuration: {err}")
    except KeyError as err:
        sys.exit(f"[-] no config parameter: {err}")
    if not data_files:
        sys.exit(
            f"[-] no data files '{config['dataFile']['prefix']}_<year>.csv' in {config['dataPath']}"
        )

    print(f"data folder: {config['dataPath']}")
    for input_file in data_files:
        year = input_file.stem.split("_")[-1]
        b = pandas.read_csv(input_file)
        b["date"] = pandas.to_datetime(b["date"], format="%Y-%m-%d")
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
