#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import datetime
import email.mime.application
import email.mime.multipart
import email.mime.text
import json
import logging.handlers
import pathlib
import smtplib
import ssl
import sys

import gruenbeck
import gruenbeck.requests

# create main logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# create logging formatter
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    '%Y-%m-%d %H:%M:%S'
)


def main(config_file):
    logger.info(f"[*] run script: {sys.argv[0]}")
    config = get_configuration(config_file)

    if config:
        logger.info(f"[*] configuration found: {config_file}")
    else:
        logger.error(f"[-] no configuration found: {config_file}")
        sys.exit(1)

    try:
        data_path = check_output_folder(config['dataPath'])
    except KeyError as err:
        logger.error(f"[-] no config parameter: {err}")
        sys.exit(1)
    except PermissionError as err:
        logger.error(f"[-] creation data folder failed: {err}")
        sys.exit(1)

    try:
        gb_param = gruenbeck.Parameter(config['parameterFile'])
    except KeyError as err:
        logger.error(f"[-] no config parameter: {err}")
        sys.exit(1)
    except IOError as err:
        logger.error(err)
        sys.exit(1)

    try:
        gb_result = gruenbeck.requests.get_data(
            config['softWaterSystem']['host'],
            gb_param.get_parameter_by_note('Wasserverbrauch')
        )
    except KeyError as err:
        logger.error(f"[-] no config parameter: {err}")
        sys.exit(1)
    except ValueError as err:
        logger.error(f"[-] failed to parse xml: {err}")
        sys.exit(1)

    # get current timestamp to be able to calculate 14 days backward
    now = datetime.datetime.now()
    # replace parameter code with dates for last 14 days backward
    gb_result = {now - datetime.timedelta(days=idx): gb_result[parameter] for idx, parameter in enumerate(gb_result)}

    # provides files per year and handle year change
    years = set([x.year for x in gb_result])
    for year in years:

        # format date
        data_new = {}
        for timestamp in sorted(gb_result):
            if timestamp.year == year:
                data_new.update({
                    timestamp.strftime(config['dataFile']['datePattern']): int(gb_result[timestamp])
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

        logger.info(f"[*] data to write: {data_existing}")
        write_data(file_obj, config['dataFile']['fieldnames'], data_existing)

        send_mail(config['mail'], data_path)


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


def check_output_folder(data_folder: str) -> pathlib.Path:
    """
    create an output folder if not exists
    :param data_folder: string of folder to store data
    :return: object: pathlib.Path of the given string
    """
    path_object = pathlib.Path(data_folder)
    if not path_object.exists():
        path_object.mkdir()
        logger.info(f"[+] path created: {path_object.absolute()}")
    else:
        logger.info(f"[*] path exists: {path_object.absolute()}")
    return path_object


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
    with file_object.open(mode='w') as csv_out_file:
        writer = csv.DictWriter(csv_out_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(write_list)


def send_mail(param: dict, data_folder: pathlib.Path) -> None:
    """
    send an email with static text and files from given folder as attachments
    :param param: needed mail configuration
    :param data_folder:
    """
    smtp_server = param['smtpServer']
    smtp_port = param['smtpPort']
    sender_email = param['senderEmail']
    sender_password = param['senderPassword']
    receiver_email = ",".join(param['recipients'])

    message = email.mime.multipart.MIMEMultipart("alternative")
    message["Subject"] = param['subject']
    message["From"] = sender_email
    message["To"] = receiver_email

    text = "your stored data"
    html = "<html><head></head><body>your stored data</body></html>"

    # Turn these into plain/html MIMEText objects
    part_text = email.mime.text.MIMEText(text, "plain")
    part_html = email.mime.text.MIMEText(html, "html")
    message.attach(part_text)
    message.attach(part_html)

    for f in data_folder.glob('*.csv') or []:
        with f.open(mode="rb") as fil:
            part = email.mime.application.MIMEApplication(
                fil.read(),
                Name=f.name
            )
        # After the file is closed
        part['Content-Disposition'] = f'attachment; filename="{f.name}"'
        message.attach(part)

    context = ssl.create_default_context()
    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, param['recipients'], message.as_string())


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
