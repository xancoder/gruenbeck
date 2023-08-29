import email.mime.application
import email.mime.multipart
import email.mime.text
import json
import pathlib
import smtplib
import ssl


def check_configuration(configuration_file: str) -> dict:
    """
    load json into a dictionary from a given valid file path string,
    otherwise throws FileNotFoundError exception
    :param configuration_file: string of path to configuration
    :return: dict
    """
    path_object = pathlib.Path(configuration_file)
    with path_object.open() as json_data_file:
        config = json.load(json_data_file)
    return config


def check_data_folder(data_folder: str) -> pathlib.Path:
    """
    create an output folder if not exists
    :param data_folder: string of folder to store data
    :return: object: pathlib.Path of the given string
    """
    path_object = pathlib.Path(data_folder)
    if not path_object.exists():
        path_object.mkdir()
    return path_object


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
    receiver_email = ','.join(param['recipients'])

    message = email.mime.multipart.MIMEMultipart('mixed')
    message['Subject'] = param['subject']
    message['From'] = sender_email
    message['To'] = receiver_email

    # Turn these into plain/html MIMEText objects
    # text email
    text = f'your stored data'
    part_text = email.mime.text.MIMEText(text, 'plain')
    message.attach(part_text)

    files_to_send = data_folder.glob('*.csv') or []
    for f in sorted(files_to_send):
        with f.open(mode='rb') as fil:
            part_file = email.mime.application.MIMEApplication(
                fil.read(),
                Name=f.name
            )
        # After the file is closed
        part_file['Content-Disposition'] = f'attachment; filename="{f.name}"'
        message.attach(part_file)

    mail_sending(message, param, sender_email, sender_password, smtp_port, smtp_server)


def send_mail_text(param: dict, subject: str, text: str) -> None:
    """
    send an email with static text and files from given folder as attachments
    :param param: needed mail configuration
    :param subject:
    :param body text:
    """
    smtp_server = param['smtpServer']
    smtp_port = param['smtpPort']
    sender_email = param['senderEmail']
    sender_password = param['senderPassword']
    receiver_email = ','.join(param['recipients'])

    message = email.mime.multipart.MIMEMultipart('mixed')
    message['Subject'] = subject
    message['From'] = sender_email
    message['To'] = receiver_email

    # Turn these into plain/html MIMEText objects
    # text email
    part_text = email.mime.text.MIMEText(text, 'plain')
    message.attach(part_text)

    mail_sending(message, param, sender_email, sender_password, smtp_port, smtp_server)


def mail_sending(message, param, sender_email, sender_password, smtp_port, smtp_server):
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(smtp_server, smtp_port, context=context) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, param['recipients'], message.as_string())
            server.quit()
    except smtplib.SMTPAuthenticationError as error:
        raise ValueError(error)
