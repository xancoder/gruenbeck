"""sending mails: the data mail with attachments and the error mail"""

import email.message
import logging
import pathlib
import smtplib
import socket
import ssl
import time
from collections.abc import Iterable
from html import escape

from gruenbeck import config, errors

logger = logging.getLogger(__name__)


class MailError(errors.GruenbeckError):
    """a mail could not be built or sent (connection, login, rejected mail)"""


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


def get_smtp_security(settings: config.Mail) -> str:
    """
    connection security of the smtp server

    The optional key "smtpSecurity" of the mail section is "ssl" (SMTP_SSL) or "starttls"
    (SMTP + STARTTLS). Without it, port 465 means "ssl", every other port means "starttls".

    :return: "ssl" or "starttls"
    """
    if settings.smtp_security is not None:
        return settings.smtp_security
    return "ssl" if settings.smtp_port == 465 else "starttls"


def build_message(
    settings: config.Mail,
    subject: str,
    text: str,
    attachments: Iterable[pathlib.Path] = (),
    html: str | None = None,
) -> email.message.EmailMessage:
    """
    build the mail from the sender and the recipients of the configuration

    Text only is a text/plain mail. With `html` it is multipart/alternative (the text first,
    the HTML as the preferred part), and with attachments multipart/mixed with that as its
    first part.

    :param settings: mail section of the configuration
    :param subject: subject of the mail
    :param text: body of the mail
    :param attachments: files to attach; a file that cannot be read is left out and named
        at the end of the body (and of the HTML)
    :param html: the same mail as a complete HTML document (None for no HTML part)
    :raises MailError: a header is invalid (e.g. a line break in the subject)
    """
    files = []
    notes = []
    for path in attachments:
        try:
            files.append((path.name, path.read_bytes()))
        except OSError as error:
            logger.warning("cannot attach %s: %s", path.name, error)
            notes.append(f"Error attaching file {path.name}: {error}")

    message = email.message.EmailMessage()
    try:
        message["Subject"] = subject
        message["From"] = settings.sender_email
        message["To"] = ", ".join(settings.recipients)
    except ValueError as error:
        raise MailError(f"Cannot build the email: {error}") from error
    message.set_content("\n\n".join([text, *notes]))
    if html is not None:
        message.add_alternative(add_notes_to_html(html, notes), subtype="html")
    for name, data in files:
        message.add_attachment(data, maintype="application", subtype="octet-stream", filename=name)
    return message


def add_notes_to_html(html: str, notes: Iterable[str]) -> str:
    """the notes (plain texts) as paragraphs at the end of the body of a HTML document"""
    paragraphs = "".join(
        f'<p style="margin:12px 16px;font-size:13px;">{escape(note)}</p>' for note in notes
    )
    if not paragraphs:
        return html
    before, found, after = html.rpartition("</body>")
    return f"{before}{paragraphs}</body>{after}" if found else html + paragraphs


def send_mail(
    settings: config.Mail,
    subject: str,
    text: str,
    attachments: Iterable[pathlib.Path] = (),
    html: str | None = None,
) -> None:
    """
    send a mail to the recipients of the configuration, with or without attachments

    Temporary errors (connection lost, timeout) are retried settings.retries times, with
    settings.retry_delay seconds in between. A wrong login, a rejected sender or recipient
    and other errors fail at once.

    :param settings: mail section of the configuration
    :param subject: subject of the mail
    :param text: body of the mail
    :param attachments: files to attach (see build_message)
    :param html: the mail as HTML document, sent next to the text (see build_message)
    :raises MailError: the mail cannot be built or sent
    """
    message = build_message(settings, subject, text, attachments, html)
    security = get_smtp_security(settings)

    attempts = 0
    while True:
        attempts += 1
        try:
            context = ssl.create_default_context()
            server: smtplib.SMTP
            if security == "ssl":
                server = smtplib.SMTP_SSL(
                    settings.smtp_server, settings.smtp_port, context=context, timeout=30
                )
            else:
                server = smtplib.SMTP(settings.smtp_server, settings.smtp_port, timeout=30)
            with server:
                if security == "starttls":
                    server.starttls(context=context)
                server.login(settings.sender_email, settings.sender_password)
                server.send_message(message)
                server.quit()
                return  # Success, exit the function
        except smtplib.SMTPAuthenticationError as error:
            # Authentication errors are not retryable
            raise MailError(f"Authentication failed: {error}") from error
        except TRANSIENT_SMTP_ERRORS as error:
            if attempts > settings.retries:
                raise MailError(
                    f"Failed to send email after {attempts} attempts: {error}"
                ) from error
            time.sleep(settings.retry_delay)  # Wait before retrying
        except PERMANENT_SMTP_ERRORS as error:
            # Permanent errors, retrying does not help
            raise MailError(f"Email rejected: {error}") from error
        except Exception as error:
            # Unexpected errors
            raise MailError(f"Unexpected error while sending email: {error}") from error
