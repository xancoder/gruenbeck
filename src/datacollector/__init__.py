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
        text = "your stored data"
        part_text = email.mime.text.MIMEText(text, "plain")
        message.attach(part_text)

        # Check if data_folder exists and is a directory
        if not data_folder.exists() or not data_folder.is_dir():
            raise ValueError(f"Data folder does not exist or is not a directory: {data_folder}")

        # Attach files
        files_to_send = list(data_folder.glob("*.csv"))
        if not files_to_send:
            # No files to send, but continue with just the text message
            part_text = email.mime.text.MIMEText("No data files found to attach.", "plain")
            message.attach(part_text)
        else:
            for f in sorted(files_to_send):
                try:
                    with f.open(mode="rb") as fil:
                        part_file = email.mime.application.MIMEApplication(fil.read(), Name=f.name)
                    # After the file is closed
                    part_file["Content-Disposition"] = f'attachment; filename="{f.name}"'
                    message.attach(part_file)
                except OSError as error:
                    # Log the error but continue with other files
                    part_text = email.mime.text.MIMEText(
                        f"Error attaching file {f.name}: {error}", "plain"
                    )
                    message.attach(part_text)

        mail_sending(message, param, sender_email, sender_password, smtp_port, smtp_server)
    except KeyError as error:
        # Missing configuration parameter
        raise ValueError(f"Invalid mail configuration: {error}") from error
    except Exception as error:
        # Re-raise any other exceptions as ValueError for consistent error handling
        raise ValueError(f"Error preparing email: {error}") from error


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

        mail_sending(message, param, sender_email, sender_password, smtp_port, smtp_server)
    except KeyError as error:
        # Missing configuration parameter
        raise ValueError(f"Invalid mail configuration: {error}") from error
    except Exception as error:
        # Re-raise any other exceptions as ValueError for consistent error handling
        raise ValueError(f"Error preparing email: {error}") from error


# Errors that may disappear on a later attempt (connection problems, timeouts)
TRANSIENT_SMTP_ERRORS = (
    smtplib.SMTPServerDisconnected,
    smtplib.SMTPConnectError,
    socket.timeout,
    socket.gaierror,
    ConnectionError,
    TimeoutError,
)

# Errors that will not change by retrying (rejected mail, missing server feature)
PERMANENT_SMTP_ERRORS = (
    smtplib.SMTPSenderRefused,
    smtplib.SMTPRecipientsRefused,
    smtplib.SMTPDataError,
    smtplib.SMTPHeloError,
    smtplib.SMTPNotSupportedError,
)


def get_smtp_connection_settings(param: dict, smtp_port) -> tuple:
    """
    Determine port and connection security of the smtp server

    The optional key "smtpSecurity" of the mail configuration is "ssl" (SMTP_SSL)
    or "starttls" (SMTP + STARTTLS). Without it, port 465 means "ssl", every
    other port means "starttls".

    :param param: Dictionary containing mail configuration
    :param smtp_port: port as int or numeric string
    :return: tuple of port (int) and security ("ssl" or "starttls")
    :raises ValueError: If port or smtpSecurity is invalid
    """
    try:
        port = int(smtp_port)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Invalid smtpPort: {smtp_port!r}") from error

    security = param.get("smtpSecurity")
    if security is None:
        return port, "ssl" if port == 465 else "starttls"
    if isinstance(security, str) and security.strip().lower() in ("ssl", "starttls"):
        return port, security.strip().lower()
    raise ValueError(f"Invalid smtpSecurity: {security!r} (expected 'ssl' or 'starttls')")


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
    port, security = get_smtp_connection_settings(param, smtp_port)

    attempts = 0
    while True:
        attempts += 1
        try:
            context = ssl.create_default_context()
            if security == "ssl":
                server = smtplib.SMTP_SSL(smtp_server, port, context=context, timeout=30)
            else:
                server = smtplib.SMTP(smtp_server, port, timeout=30)
            with server:
                if security == "starttls":
                    server.starttls(context=context)
                server.login(sender_email, sender_password)
                server.sendmail(sender_email, param["recipients"], message.as_string())
                server.quit()
                return  # Success, exit the function
        except smtplib.SMTPAuthenticationError as error:
            # Authentication errors are not retryable
            raise ValueError(f"Authentication failed: {error}") from error
        except TRANSIENT_SMTP_ERRORS as error:
            if attempts > max_retries:
                raise ValueError(
                    f"Failed to send email after {attempts} attempts: {error}"
                ) from error
            time.sleep(retry_delay)  # Wait before retrying
        except PERMANENT_SMTP_ERRORS as error:
            # Permanent errors, retrying does not help
            raise ValueError(f"Email rejected: {error}") from error
        except Exception as error:
            # Unexpected errors
            raise ValueError(f"Unexpected error while sending email: {error}") from error
