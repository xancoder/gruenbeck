#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import datetime
import logging.handlers
import pathlib
import sys

import datacollector
import gruenbeck

# create main logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# create logging formatter
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    '%Y-%m-%d %H:%M:%S'
)


def main(config_file):
    logger.info(f'[*] run script: {sys.argv[0]}')

    config = get_configuration(config_file)
    data_path = get_data_folder(config)
    device_parameter = get_device_parameter(config)
    device_data = get_device_data(config, device_parameter)
    device_data = add_timestamp_as_key_device_data(device_data)

    # provides files per year and handle year change
    years = set([x.year for x in device_data])
    for year in years:
        # format date
        data_new = {}
        for timestamp in sorted(device_data):
            if timestamp.year == year:
                data_new.update({
                    timestamp.strftime(config['dataFile']['datePattern']): int(device_data[timestamp])
                })
        # get stored data
        data_existing = {}
        file_obj = pathlib.Path(f"{data_path}/{config['dataFile']['prefix']}_{year}.csv")
        if file_obj.exists():
            with file_obj.open(mode='r') as csv_file:
                csv_reader = csv.DictReader(csv_file)
                for row in csv_reader:
                    tmp_date = row[config['dataFile']['fieldnames']['date']]
                    tmp_value = row[config['dataFile']['fieldnames']['value']]
                    tmp_value = int(tmp_value) if tmp_value.isnumeric() else tmp_value
                    data_existing.update({tmp_date: tmp_value})
        # merge values
        data_existing.update(data_new)
        write_data(file_obj, config['dataFile']['fieldnames'], data_existing)
    get_mail(config, data_path)


def get_configuration(config_file):
    config = None
    try:
        config = datacollector.check_configuration(config_file)
    except FileNotFoundError as err:
        logger.error(f'[-] no configuration: {err}')
        sys.exit(1)
    logger.info(f'[*] config: {config}')
    return config


def get_data_folder(config):
    data_path = None
    try:
        data_path = datacollector.check_data_folder(config['dataPath'])
    except KeyError as err:
        handle_error(config, f'[-] no config parameter: {err}')
    except PermissionError as err:
        handle_error(config, f'[-] creation data folder failed: {err}')
    logger.info(f'[*] data_path: {data_path}')
    return data_path


def get_device_parameter(config):
    parameter = None
    try:
        parameter = gruenbeck.Parameter(config['parameterFile'])
    except KeyError as err:
        handle_error(config, f'[-] no config parameter: {err}')
    except FileNotFoundError as err:
        handle_error(config, f'{err}')
    logger.info(f'[*] parameter: {parameter.parameters}')
    return parameter


def get_device_data(config, parameter):
    result = None
    try:
        result = gruenbeck.get_data_from_mux_http(
            config['softWaterSystem']['host'],
            parameter.get_parameter_by_note('Wasserverbrauch')
        )
    except KeyError as err:
        handle_error(config, f'[-] no config parameter: {err}')
    except ValueError as err:
        handle_error(config, f'[-] failed to parse xml: {err}')
    return result


def handle_error(config, error_text: str) -> None:
    logger.error(error_text)
    datacollector.send_mail_text(config, 'gruenbeck data collector failure', error_text)
    sys.exit(1)


def add_timestamp_as_key_device_data(device_data):
    # get current timestamp to be able to calculate 14 days backward
    now = datetime.datetime.now()
    # replace parameter code with dates for last 14 days backward
    device_data = {now - datetime.timedelta(days=idx): device_data[param] for idx, param in enumerate(device_data)}
    return device_data


def write_data(file_object: pathlib.Path, fieldnames: dict, data: dict) -> None:
    """
    write data to csv file
    :param file_object: pathlib.Path of output file
    :param fieldnames: fieldnames as column headers
    :param data: dictionary data to write
    """
    # build data structure to write
    write_list = []
    for item in sorted(data):
        write_list.append({
            fieldnames['date']: item,
            fieldnames['value']: data[item]
        })

    # write file
    logger.info(f'[*] data to write: {data}')
    with file_object.open(mode='w') as csv_out_file:
        writer = csv.DictWriter(csv_out_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(write_list)


def get_mail(config, data_path):
    try:
        datacollector.send_mail(config['mail'], data_path)
        logger.info('[*] mail send')
    except KeyError as error:
        logger.error(f'[-] no mail configured: {error}')
        sys.exit(1)
    except ValueError as error:
        logger.error(f'[-] wrong configuration: {error}')
        sys.exit(1)


if __name__ == '__main__':
    import argparse

    # parse commandline arguments
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--config-file', '-c',
        help='set config file',
        required=False,
        default='./src/config.json'
    )
    parser.add_argument(
        '--log-console', '-l',
        help='activate console logging',
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
