import email.mime.application
import email.mime.multipart
import email.mime.text
import json
import pathlib
import smtplib
import socket
import ssl
import time


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
    Send an email with static text and files from given folder as attachments

    :param param: Dictionary containing mail configuration
    :param data_folder: Path to the folder containing files to attach
    :raises ValueError: If mail configuration is invalid or sending fails
    """
    try:
        smtp_server = param["smtpServer"]
        smtp_port = param["smtpPort"]
        sender_email = param["senderEmail"]
        sender_password = param["senderPassword"]
        receiver_email = ",".join(param["recipients"])

        message = email.mime.multipart.MIMEMultipart("mixed")
        message["Subject"] = param["subject"]
        message["From"] = sender_email
        message["To"] = receiver_email

        # Turn these into plain/html MIMEText objects
        # text email
        text = f"your stored data"
        part_text = email.mime.text.MIMEText(text, "plain")
        message.attach(part_text)

        # Check if data_folder exists and is a directory
        if not data_folder.exists() or not data_folder.is_dir():
            raise ValueError(
                f"Data folder does not exist or is not a directory: {data_folder}"
            )

        # Attach files
        files_to_send = list(data_folder.glob("*.csv"))
        if not files_to_send:
            # No files to send, but continue with just the text message
            part_text = email.mime.text.MIMEText(
                "No data files found to attach.", "plain"
            )
            message.attach(part_text)
        else:
            for f in sorted(files_to_send):
                try:
                    with f.open(mode="rb") as fil:
                        part_file = email.mime.application.MIMEApplication(
                            fil.read(), Name=f.name
                        )
                    # After the file is closed
                    part_file["Content-Disposition"] = (
                        f'attachment; filename="{f.name}"'
                    )
                    message.attach(part_file)
                except (IOError, PermissionError) as error:
                    # Log the error but continue with other files
                    part_text = email.mime.text.MIMEText(
                        f"Error attaching file {f.name}: {error}", "plain"
                    )
                    message.attach(part_text)

        mail_sending(
            message, param, sender_email, sender_password, smtp_port, smtp_server
        )
    except KeyError as error:
        # Missing configuration parameter
        raise ValueError(f"Invalid mail configuration: {error}")
    except Exception as error:
        # Re-raise any other exceptions as ValueError for consistent error handling
        raise ValueError(f"Error preparing email: {error}")


def send_mail_text(param: dict, subject: str, text: str) -> None:
    """
    Send an email with text content only

    :param param: Dictionary containing mail configuration
    :param subject: Email subject
    :param text: Email body text
    :raises ValueError: If mail configuration is invalid or sending fails
    """
    try:
        smtp_server = param["smtpServer"]
        smtp_port = param["smtpPort"]
        sender_email = param["senderEmail"]
        sender_password = param["senderPassword"]
        receiver_email = ",".join(param["recipients"])

        message = email.mime.multipart.MIMEMultipart("mixed")
        message["Subject"] = subject
        message["From"] = sender_email
        message["To"] = receiver_email

        # Turn these into plain/html MIMEText objects
        # text email
        part_text = email.mime.text.MIMEText(text, "plain")
        message.attach(part_text)

        mail_sending(
            message, param, sender_email, sender_password, smtp_port, smtp_server
        )
    except KeyError as error:
        # Missing configuration parameter
        raise ValueError(f"Invalid mail configuration: {error}")
    except Exception as error:
        # Re-raise any other exceptions as ValueError for consistent error handling
        raise ValueError(f"Error preparing email: {error}")


def mail_sending(
    message,
    param,
    sender_email,
    sender_password,
    smtp_port,
    smtp_server,
    max_retries=3,
    retry_delay=5,
):
    retries = 0
    last_error = None

    while retries <= max_retries:
        try:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(
                smtp_server, smtp_port, context=context, timeout=30
            ) as server:
                server.login(sender_email, sender_password)
                server.sendmail(sender_email, param["recipients"], message.as_string())
                server.quit()
                return  # Success, exit the function
        except smtplib.SMTPAuthenticationError as error:
            # Authentication errors are not retryable
            raise ValueError(f"Authentication failed: {error}")
        except (
            smtplib.SMTPServerDisconnected,
            smtplib.SMTPSenderRefused,
            smtplib.SMTPRecipientsRefused,
            smtplib.SMTPDataError,
            smtplib.SMTPConnectError,
            smtplib.SMTPHeloError,
            smtplib.SMTPNotSupportedError,
            socket.timeout,
            socket.gaierror,
            ConnectionRefusedError,
            ConnectionResetError,
            TimeoutError,
        ) as error:
            # These are potentially transient errors, so we can retry
            last_error = error
            retries += 1
            if retries <= max_retries:
                time.sleep(retry_delay)  # Wait before retrying
            else:
                # Max retries reached, raise the error
                raise ValueError(
                    f"Failed to send email after {max_retries} attempts: {error}"
                )
        except Exception as error:
            # Unexpected errors
            raise ValueError(f"Unexpected error while sending email: {error}")
