#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging.handlers
import pathlib

# create main logger
logger = logging.getLogger('data-collector')
logger.setLevel(logging.INFO)

# create logging formatter
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    '%Y-%m-%d %H:%M:%S'
)


def main(config_file):
    config = get_configuration(config_file)

    if config:
        logger.info("[*] configuration found")
    else:
        logger.info("[-] no configuration found")

    logger.error("[-] error message")


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
    parser.add_argument(
        '--log-console', '-l',
        help="activate console logging",
        action='store_true'
    )
    parser.add_argument(
        '--log-error', '-e',
        help='error logging to file',
        required=False,
        default='./log/gruenbeck_error.log'
    )
    args = parser.parse_args()

    CONFIG_file = args.config_file

    if args.log_console:
        # create console handler
        sh = logging.StreamHandler()
        sh.setLevel(logging.INFO)
        # add formatter to the handlers
        sh.setFormatter(formatter)
        # add the handlers to the logger
        logger.addHandler(sh)

    log_rotate_file = logging.handlers.RotatingFileHandler(
        f'{args.log_error}',
        maxBytes=8000000,
        backupCount=5
    )
    log_rotate_file.setLevel(logging.ERROR)
    log_rotate_file.setFormatter(formatter)
    logger.addHandler(log_rotate_file)

    main(CONFIG_file)
