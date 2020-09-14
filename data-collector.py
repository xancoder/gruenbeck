#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import pathlib


def main(config_file):
    config = get_configuration(config_file)

    if config:
        print("[*] configuration found")
    else:
        print("[-] no configuration found")


def get_configuration(configuration_file: str) -> dict:
    """
    load json into a dictionary from a given valid file path string, otherwise return empty dictionary
    :rtype: dict
    """
    config_path = pathlib.Path(configuration_file)
    if not config_path.exists():
        config = {}
    else:
        with config_path.open() as json_data_file:
            config = json.load(json_data_file)
    return config


if __name__ == '__main__':
    import argparse

    # parse commandline arguments
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--config-file', '-c',
        help='set config file',
        required=False,
        default='config.json'
    )
    args = parser.parse_args()

    CONFIG_file = args.config_file

    main(CONFIG_file)
