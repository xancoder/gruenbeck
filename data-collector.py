#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import pathlib


def main():
    config = get_configuration()


def get_configuration():
    config_p = pathlib.Path("config.json")
    if not config_p.exists():
        print(f"[-] config file not found: {config_p}")
    else:
        print(f"[*] read config file: {config_p}")
        with config_p.open() as json_data_file:
            config = json.load(json_data_file)
    return config


if __name__ == '__main__':
    main()
