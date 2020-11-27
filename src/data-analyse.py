#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pathlib
import sys

import matplotlib.pyplot as plt
import pandas

print_pattern_headline = '{:<4} {:<5} {:<4} {:<3} {:<3} {:<3} {:<5}'
print_pattern = '{:>4} {:>5} {:>4.0f} {:>3.0f} {:>3.0f} {:>3.0f} {:>5.0f}'


def main():
    script_path = sys.argv[0]
    root_path = pathlib.Path(script_path).parent
    print(root_path)
    for input_file in sorted(root_path.glob('../data/*')):
        year = input_file.stem.split('_')[-1]
        b = pandas.read_csv(input_file)
        b['date'] = pandas.to_datetime(b['date'], format='%Y-%m-%d')
        b.index = b['date']
        grouped_df = b.groupby(by=[b.index.year, b.index.month])

        print(print_pattern_headline.format(
            'year',
            'month',
            'mean',
            'min',
            'max',
            'std',
            'sum'
        ))

        x = []
        y = []

        for key, item in grouped_df:
            x.append(key[1])
            y.append(grouped_df.get_group(key).value.mean())

            print(print_pattern.format(
                key[0],
                key[1],
                grouped_df.get_group(key).value.mean(),
                grouped_df.get_group(key).value.min(),
                grouped_df.get_group(key).value.max(),
                grouped_df.get_group(key).value.std(),
                grouped_df.get_group(key).value.sum()
            ))

        plt.plot(x, y, label=year)

        print(print_pattern.format(
            year,
            '-',
            b.value.mean(),
            b.value.min(),
            b.value.max(),
            b.value.std(),
            b.value.sum()
        ))
        print()

    plt.title(r'mean water consumption')
    plt.xlabel('month')
    plt.ylabel('liters')
    plt.grid(True)
    plt.legend()
    plt.show()


if __name__ == '__main__':
    main()
