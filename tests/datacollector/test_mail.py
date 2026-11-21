"""
characterization of the mails of datacollector (P006-S1)

smtplib.SMTP and smtplib.SMTP_SSL are replaced by the fake server of the fixture smtp
(conftest.py); no connection leaves the test.
"""

import email.message
import email.mime.text
import smtplib
import socket
import ssl

import pytest

import datacollector

MAIL = {
    "recipients": ["one@example.com", "two@example.com"],
    "senderEmail": "sender@example.com",
    "senderPassword": "test-password",
    "smtpPort": 587,
    "smtpServer": "smtp.example.com",
    "subject": "[data collector] - gruenbeck",
}


@pytest.fixture
def data_folder(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    return folder


def parts(message):
    """(content type, filename, content) of every part of a multipart mail"""
    return [
        (part.get_content_type(), part.get_filename(), part.get_content())
        for part in message.iter_parts()
    ]


# --- data mail: send_mail -----------------------------------------------------------


def test_data_mail_attaches_the_csv_files_of_the_data_folder(smtp, sleeps, data_folder):
    (data_folder / "gruenbeck_2026.csv").write_text("date,value\n2026-11-22,101\n")
    (data_folder / "gruenbeck_2025.csv").write_bytes(b"date,value\r\n2025-12-31,3\r\n")
    (data_folder / "notes.txt").write_text("not attached")
    (data_folder / "sub").mkdir()
    (data_folder / "sub" / "deeper.csv").write_text("not attached")

    datacollector.send_mail(MAIL, data_folder)

    (message,) = smtp.messages()
    assert message["Subject"] == "[data collector] - gruenbeck"
    assert message["From"] == "sender@example.com"
    # the parsed header adds a space after the comma
    assert "\nTo: one@example.com,two@example.com\n" in smtp.raw_messages()[0]
    assert message.get_content_type() == "multipart/mixed"
    # attachments sorted by name
    assert parts(message) == [
        ("text/plain", None, "your stored data"),
        ("application/octet-stream", "gruenbeck_2025.csv", b"date,value\r\n2025-12-31,3\r\n"),
        ("application/octet-stream", "gruenbeck_2026.csv", b"date,value\n2026-11-22,101\n"),
    ]
    attachment = list(message.iter_parts())[1]
    assert attachment["Content-Disposition"] == 'attachment; filename="gruenbeck_2025.csv"'
    assert attachment.get_param("Name") == "gruenbeck_2025.csv"
    assert sleeps == []


def test_data_mail_goes_to_every_recipient_after_login(smtp, data_folder):
    datacollector.send_mail(MAIL, data_folder)

    (connection,) = smtp.connections
    assert connection["kind"] == "SMTP"
    assert (connection["host"], connection["port"]) == ("smtp.example.com", 587)
    assert [call[0] for call in connection["calls"]] == [
        "starttls",
        "login",
        "sendmail",
        "quit",
        "exit",
    ]
    assert connection["calls"][1] == ("login", "sender@example.com", "test-password")
    sendmail = connection["calls"][2]
    assert sendmail[1:3] == ("sender@example.com", ["one@example.com", "two@example.com"])


def test_data_mail_without_csv_files_says_so(smtp, data_folder):
    (data_folder / "notes.txt").write_text("not attached")

    datacollector.send_mail(MAIL, data_folder)

    (message,) = smtp.messages()
    assert parts(message) == [
        ("text/plain", None, "your stored data"),
        ("text/plain", None, "No data files found to attach."),
    ]


def test_unreadable_csv_file_becomes_a_text_part(smtp, data_folder):
    (data_folder / "a.csv").write_text("date,value\n")
    (data_folder / "b.csv").mkdir()  # matches *.csv, but cannot be read
    (data_folder / "c.csv").write_text("date,value\n")

    datacollector.send_mail(MAIL, data_folder)

    (message,) = smtp.messages()
    found = parts(message)
    assert [(kind, name) for kind, name, _ in found] == [
        ("text/plain", None),
        ("application/octet-stream", "a.csv"),
        ("text/plain", None),
        ("application/octet-stream", "c.csv"),
    ]
    assert found[2][2].startswith("Error attaching file b.csv: [Errno 21] Is a directory:")


@pytest.mark.parametrize("kind", ["missing", "file"])
def test_data_mail_without_data_folder_is_an_error(smtp, tmp_path, kind):
    folder = tmp_path / "data"
    if kind == "file":
        folder.write_text("")

    with pytest.raises(ValueError) as err:
        datacollector.send_mail(MAIL, folder)

    assert str(err.value) == (
        f"Error preparing email: Data folder does not exist or is not a directory: {folder}"
    )
    assert smtp.connections == []


@pytest.mark.parametrize(
    "key", ["smtpServer", "smtpPort", "senderEmail", "senderPassword", "recipients", "subject"]
)
def test_data_mail_with_missing_configuration_is_an_error(smtp, data_folder, key):
    config = {name: value for name, value in MAIL.items() if name != key}

    with pytest.raises(ValueError) as err:
        datacollector.send_mail(config, data_folder)

    assert str(err.value) == f"Invalid mail configuration: '{key}'"
    assert isinstance(err.value.__cause__, KeyError)
    assert smtp.connections == []


def test_data_mail_wraps_the_send_errors_again(smtp, sleeps, data_folder):
    smtp.errors = [("login", smtplib.SMTPAuthenticationError(535, b"bad credentials"))]

    with pytest.raises(ValueError) as err:
        datacollector.send_mail(MAIL, data_folder)

    assert str(err.value) == (
        "Error preparing email: Authentication failed: (535, b'bad credentials')"
    )
    assert isinstance(err.value.__cause__, ValueError)
    assert isinstance(err.value.__cause__.__cause__, smtplib.SMTPAuthenticationError)


# --- text mail: send_mail_text ------------------------------------------------------


def test_text_mail_has_the_given_subject_and_text(smtp, sleeps):
    datacollector.send_mail_text(MAIL, "gruenbeck data collector failure", "[-] an error")

    (message,) = smtp.messages()
    assert message["Subject"] == "gruenbeck data collector failure"
    assert message["From"] == "sender@example.com"
    # the parsed header adds a space after the comma
    assert "\nTo: one@example.com,two@example.com\n" in smtp.raw_messages()[0]
    assert message.get_content_type() == "multipart/mixed"
    assert parts(message) == [("text/plain", None, "[-] an error")]
    (connection,) = smtp.connections
    assert [call[0] for call in connection["calls"]] == [
        "starttls",
        "login",
        "sendmail",
        "quit",
        "exit",
    ]
    assert connection["calls"][2][2] == ["one@example.com", "two@example.com"]


def test_text_mail_needs_no_subject_in_the_configuration(smtp):
    config = {name: value for name, value in MAIL.items() if name != "subject"}

    datacollector.send_mail_text(config, "subject", "text")

    (message,) = smtp.messages()
    assert message["Subject"] == "subject"


@pytest.mark.parametrize(
    "key", ["smtpServer", "smtpPort", "senderEmail", "senderPassword", "recipients"]
)
def test_text_mail_with_missing_configuration_is_an_error(smtp, key):
    config = {name: value for name, value in MAIL.items() if name != key}

    with pytest.raises(ValueError) as err:
        datacollector.send_mail_text(config, "subject", "text")

    assert str(err.value) == f"Invalid mail configuration: '{key}'"
    assert smtp.connections == []


def test_text_mail_wraps_the_send_errors_again(smtp, sleeps):
    smtp.errors = [("connect", ConnectionRefusedError(111, "Connection refused"))] * 4

    with pytest.raises(ValueError) as err:
        datacollector.send_mail_text(MAIL, "subject", "text")

    assert str(err.value) == (
        "Error preparing email: Failed to send email after 4 attempts:"
        " [Errno 111] Connection refused"
    )


# --- port and connection security ---------------------------------------------------


@pytest.mark.parametrize(
    "param, port, expected",
    [
        ({}, 465, (465, "ssl")),
        ({}, 587, (587, "starttls")),
        ({}, 25, (25, "starttls")),
        ({}, "465", (465, "ssl")),
        ({}, " 587 ", (587, "starttls")),
        ({}, 465.0, (465, "ssl")),
        ({"smtpSecurity": None}, 465, (465, "ssl")),
        ({"smtpSecurity": "ssl"}, 587, (587, "ssl")),
        ({"smtpSecurity": "starttls"}, 465, (465, "starttls")),
        ({"smtpSecurity": " SSL "}, 2525, (2525, "ssl")),
        ({"smtpSecurity": "StartTLS"}, 2525, (2525, "starttls")),
    ],
)
def test_connection_settings(param, port, expected):
    assert datacollector.get_smtp_connection_settings(param, port) == expected


@pytest.mark.parametrize("port", ["abc", "", None, [587], "587.0"], ids=repr)
def test_invalid_port_is_an_error(port):
    with pytest.raises(ValueError) as err:
        datacollector.get_smtp_connection_settings({}, port)

    assert str(err.value) == f"Invalid smtpPort: {port!r}"


@pytest.mark.parametrize("security", ["tls", "", "none", 1, ["ssl"]], ids=repr)
def test_invalid_security_is_an_error(security):
    with pytest.raises(ValueError) as err:
        datacollector.get_smtp_connection_settings({"smtpSecurity": security}, 587)

    assert str(err.value) == f"Invalid smtpSecurity: {security!r} (expected 'ssl' or 'starttls')"


# --- sending: mail_sending ----------------------------------------------------------


def send(param=None, port=587, **kwargs):
    message = email.mime.text.MIMEText("text", "plain")
    datacollector.mail_sending(
        message,
        MAIL if param is None else param,
        "sender@example.com",
        "test-password",
        port,
        "smtp.example.com",
        **kwargs,
    )


def test_ssl_connects_with_smtp_ssl_and_without_starttls(smtp):
    send(port=465)

    (connection,) = smtp.connections
    assert connection["kind"] == "SMTP_SSL"
    assert (connection["host"], connection["port"]) == ("smtp.example.com", 465)
    assert connection["kwargs"]["timeout"] == 30
    assert isinstance(connection["kwargs"]["context"], ssl.SSLContext)
    assert [call[0] for call in connection["calls"]] == ["login", "sendmail", "quit", "exit"]


def test_starttls_connects_with_smtp_and_starts_tls_first(smtp):
    send(port="587")

    (connection,) = smtp.connections
    assert connection["kind"] == "SMTP"
    assert connection["port"] == 587
    assert connection["kwargs"] == {"timeout": 30}
    assert connection["calls"][0][0] == "starttls"
    assert isinstance(connection["calls"][0][1], ssl.SSLContext)


def test_smtp_security_overrides_the_port(smtp):
    send(param={**MAIL, "smtpSecurity": "ssl"}, port=587)

    assert [connection["kind"] for connection in smtp.connections] == ["SMTP_SSL"]


def test_invalid_port_fails_before_connecting(smtp):
    with pytest.raises(ValueError, match="Invalid smtpPort: 'abc'"):
        send(port="abc")

    assert smtp.connections == []


@pytest.mark.parametrize(
    "error",
    [
        smtplib.SMTPServerDisconnected("Connection unexpectedly closed"),
        smtplib.SMTPConnectError(421, b"busy"),
        # socket.timeout is TimeoutError since Python 3.10
        TimeoutError("timed out"),
        socket.gaierror(-2, "Name or service not known"),
        ConnectionRefusedError(111, "Connection refused"),
    ],
    ids=lambda error: type(error).__name__,
)
def test_transient_error_is_retried_three_times(smtp, sleeps, error):
    smtp.errors = [("connect", error)] * 3

    send()

    assert len(smtp.connections) == 1  # the fourth attempt connects
    assert sleeps == [5, 5, 5]


def test_transient_error_while_sending_is_retried(smtp, sleeps):
    smtp.errors = [("sendmail", smtplib.SMTPServerDisconnected("closed"))]

    send()

    assert len(smtp.connections) == 2
    assert len(smtp.messages()) == 1
    assert sleeps == [5]


def test_transient_error_fails_after_four_attempts(smtp, sleeps):
    smtp.errors = [("connect", TimeoutError("timed out"))] * 5

    with pytest.raises(ValueError) as err:
        send()

    assert str(err.value) == "Failed to send email after 4 attempts: timed out"
    assert isinstance(err.value.__cause__, TimeoutError)
    assert sleeps == [5, 5, 5]
    assert len(smtp.errors) == 1


def test_number_of_retries_and_delay_are_parameters(smtp, sleeps):
    smtp.errors = [("connect", TimeoutError("timed out"))] * 2

    send(max_retries=2, retry_delay=0.5)

    assert sleeps == [0.5, 0.5]
    assert len(smtp.connections) == 1


def test_no_retry_with_max_retries_zero(smtp, sleeps):
    smtp.errors = [("connect", TimeoutError("timed out"))]

    with pytest.raises(ValueError, match=r"^Failed to send email after 1 attempts: timed out$"):
        send(max_retries=0)

    assert sleeps == []


def test_authentication_error_is_not_retried(smtp, sleeps):
    smtp.errors = [("login", smtplib.SMTPAuthenticationError(535, b"bad credentials"))]

    with pytest.raises(ValueError) as err:
        send()

    assert str(err.value) == "Authentication failed: (535, b'bad credentials')"
    assert len(smtp.connections) == 1
    assert sleeps == []


@pytest.mark.parametrize(
    "step, error",
    [
        ("sendmail", smtplib.SMTPSenderRefused(550, b"sender refused", "sender@example.com")),
        ("sendmail", smtplib.SMTPRecipientsRefused({"one@example.com": (550, b"unknown")})),
        ("sendmail", smtplib.SMTPDataError(554, b"rejected")),
        ("login", smtplib.SMTPHeloError(501, b"bad helo")),
        ("starttls", smtplib.SMTPNotSupportedError("STARTTLS extension not supported")),
    ],
    ids=lambda value: value if isinstance(value, str) else type(value).__name__,
)
def test_permanent_error_is_not_retried(smtp, sleeps, step, error):
    smtp.errors = [(step, error)]

    with pytest.raises(ValueError) as err:
        send()

    assert str(err.value) == f"Email rejected: {error}"
    assert err.value.__cause__ is error
    assert len(smtp.connections) == 1
    assert sleeps == []


@pytest.mark.parametrize(
    "step, error",
    [
        ("connect", ssl.SSLError("certificate verify failed")),
        ("connect", OSError(113, "No route to host")),
        ("sendmail", smtplib.SMTPResponseException(451, b"try again later")),
        ("quit", RuntimeError("unexpected")),
    ],
    ids=lambda value: value if isinstance(value, str) else type(value).__name__,
)
def test_other_errors_are_not_retried(smtp, sleeps, step, error):
    smtp.errors = [(step, error)]

    with pytest.raises(ValueError) as err:
        send()

    assert str(err.value) == f"Unexpected error while sending email: {error}"
    assert sleeps == []


def test_message_is_sent_as_string(smtp):
    message = email.message.EmailMessage()
    message["Subject"] = "subject"
    message.set_content("body")

    datacollector.mail_sending(
        message, MAIL, "sender@example.com", "test-password", 587, "smtp.example.com"
    )

    (connection,) = smtp.connections
    assert connection["calls"][2][3] == message.as_string()
