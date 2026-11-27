"""
the mails: building with EmailMessage and sending with smtplib (P006-S5)

smtplib.SMTP and smtplib.SMTP_SSL are replaced by the fake server of the fixture smtp
(conftest.py); no connection leaves the test.
"""

import collections.abc
import dataclasses
import email.message
import logging
import pathlib
import smtplib
import socket
import ssl
import typing

import pytest

from gruenbeck import config, errors, mail

if typing.TYPE_CHECKING:
    from conftest import FakeSMTP

SETTINGS = config.Mail(
    smtp_server="smtp.example.com",
    smtp_port=587,
    smtp_security=None,
    sender_email="sender@example.com",
    sender_password="test-password",
    recipients=("one@example.com", "two@example.com"),
    subject="[data collector] - gruenbeck",
    retries=3,
    retry_delay=5,
)

SEND_STEPS = ["starttls", "login", "send_message", "sendmail", "quit", "close", "exit"]


def settings_with(**changes: typing.Any) -> config.Mail:
    return dataclasses.replace(SETTINGS, **changes)


def send(
    settings: config.Mail = SETTINGS,
    subject: str = "subject",
    text: str = "text",
    attachments: collections.abc.Iterable[pathlib.Path] = (),
    html: str | None = None,
) -> None:
    mail.send_mail(settings, subject, text, attachments, html)


def parts(message: email.message.EmailMessage) -> list[tuple[str, str | None, typing.Any]]:
    """(content type, filename, content) of every part of a multipart mail"""
    return [
        (part.get_content_type(), part.get_filename(), part.get_content())
        for part in message.iter_parts()
    ]


# --- building: one mail with or without attachments ---------------------------------


def test_mail_without_attachments_is_a_plain_text_mail(
    smtp: "FakeSMTP", sleeps: list[float]
) -> None:
    send(subject="gruenbeck data collector failure", text="an error")

    (message,) = smtp.messages()
    assert message["Subject"] == "gruenbeck data collector failure"
    assert message["From"] == "sender@example.com"
    assert message["To"] == "one@example.com, two@example.com"
    assert message.get_content_type() == "text/plain"
    assert message.get_content() == "an error\n"
    assert sleeps == []


def test_mail_goes_to_every_recipient_after_login(smtp: "FakeSMTP") -> None:
    send()

    (connection,) = smtp.connections
    assert connection["kind"] == "SMTP"
    assert (connection["host"], connection["port"]) == ("smtp.example.com", 587)
    assert [call[0] for call in connection["calls"]] == SEND_STEPS
    assert connection["calls"][1] == ("login", "sender@example.com", "test-password")
    # the envelope comes from the headers of the mail
    sendmail = connection["calls"][3]
    assert sendmail[1:3] == ("sender@example.com", ["one@example.com", "two@example.com"])


def test_mail_is_given_to_send_message_as_email_message(smtp: "FakeSMTP") -> None:
    send(subject="the subject", text="the text")

    (connection,) = smtp.connections
    (_, message) = connection["calls"][2]
    assert isinstance(message, email.message.EmailMessage)
    assert message["Subject"] == "the subject"


def test_mail_with_attachments_is_a_multipart_mail(
    smtp: "FakeSMTP", tmp_path: pathlib.Path
) -> None:
    first = tmp_path / "gruenbeck_2025.csv"
    first.write_bytes(b"date,value\r\n2025-12-31,3\r\n")
    second = tmp_path / "gruenbeck_2026.csv"
    second.write_text("date,value\n2026-11-22,101\n")

    send(text="your stored data", attachments=[first, second])

    (message,) = smtp.messages()
    assert message["Subject"] == "subject"
    assert message.get_content_type() == "multipart/mixed"
    # in the given order
    assert parts(message) == [
        ("text/plain", None, "your stored data\n"),
        ("application/octet-stream", "gruenbeck_2025.csv", b"date,value\r\n2025-12-31,3\r\n"),
        ("application/octet-stream", "gruenbeck_2026.csv", b"date,value\n2026-11-22,101\n"),
    ]
    attachment = list(message.iter_parts())[1]
    assert attachment["Content-Disposition"] == 'attachment; filename="gruenbeck_2025.csv"'


def test_attachments_can_be_any_iterable(smtp: "FakeSMTP", tmp_path: pathlib.Path) -> None:
    (tmp_path / "a.csv").write_text("a")
    (tmp_path / "b.csv").write_text("b")

    send(attachments=(file for file in sorted(tmp_path.glob("*.csv"))))

    (message,) = smtp.messages()
    assert [name for _, name, _ in parts(message)] == [None, "a.csv", "b.csv"]


def test_unreadable_attachment_is_named_in_the_text_and_logged(
    smtp: "FakeSMTP", tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "a.csv").write_text("date,value\n")
    (tmp_path / "b.csv").mkdir()  # cannot be read as a file
    (tmp_path / "c.csv").write_text("date,value\n")
    caplog.set_level(logging.WARNING, logger="gruenbeck")

    send(text="your stored data", attachments=sorted(tmp_path.glob("*.csv")))

    (message,) = smtp.messages()
    found = parts(message)
    assert [(kind, name) for kind, name, _ in found] == [
        ("text/plain", None),
        ("application/octet-stream", "a.csv"),
        ("application/octet-stream", "c.csv"),
    ]
    assert found[0][2].startswith("your stored data\n\nError attaching file b.csv: [Errno 21]")
    assert [(r.name, r.getMessage()[:28]) for r in caplog.records] == [
        ("gruenbeck.mail", "cannot attach b.csv: [Errno ")
    ]


def test_missing_attachment_is_named_in_the_text(smtp: "FakeSMTP", tmp_path: pathlib.Path) -> None:
    send(text="body", attachments=[tmp_path / "missing.csv"])

    (message,) = smtp.messages()
    # no attachment is left: a plain text mail
    assert message.get_content_type() == "text/plain"
    assert message.get_content().startswith("body\n\nError attaching file missing.csv: [Errno 2]")


def test_text_and_subject_may_have_non_ascii_characters(smtp: "FakeSMTP") -> None:
    send(subject="Wasserverbrauch für Köln", text="Stand: 5 m³")

    (message,) = smtp.messages()
    assert message["Subject"] == "Wasserverbrauch für Köln"
    assert message.get_content() == "Stand: 5 m³\n"


def test_empty_subject_is_allowed(smtp: "FakeSMTP") -> None:
    send(subject="")

    (message,) = smtp.messages()
    assert message["Subject"] == ""


def test_line_break_in_the_subject_is_an_error_before_connecting(smtp: "FakeSMTP") -> None:
    with pytest.raises(mail.MailError) as err:
        send(subject="one\ntwo")

    assert str(err.value) == (
        "Cannot build the email: Header values may not contain linefeed or carriage return"
        " characters"
    )
    assert isinstance(err.value.__cause__, ValueError)
    assert not err.value.unexpected
    assert smtp.connections == []


# --- errors --------------------------------------------------------------------------


def test_mail_errors_have_the_common_base_class() -> None:
    assert issubclass(mail.MailError, errors.GruenbeckError)
    assert not issubclass(mail.MailError, ValueError)


def test_logger_of_the_module_has_its_own_name() -> None:
    assert mail.logger.name == "gruenbeck.mail"


# --- connection security -------------------------------------------------------------


@pytest.mark.parametrize(
    ("port", "security", "expected"),
    [
        (465, None, "ssl"),
        (587, None, "starttls"),
        (25, None, "starttls"),
        (587, "ssl", "ssl"),
        (465, "starttls", "starttls"),
        (2525, "ssl", "ssl"),
        (2525, "starttls", "starttls"),
    ],
)
def test_connection_security(port: int, security: str | None, expected: str) -> None:
    settings = settings_with(smtp_port=port, smtp_security=security)

    assert mail.get_smtp_security(settings) == expected


def test_ssl_connects_with_smtp_ssl_and_without_starttls(smtp: "FakeSMTP") -> None:
    send(settings_with(smtp_port=465))

    (connection,) = smtp.connections
    assert connection["kind"] == "SMTP_SSL"
    assert (connection["host"], connection["port"]) == ("smtp.example.com", 465)
    assert connection["kwargs"]["timeout"] == 30
    assert isinstance(connection["kwargs"]["context"], ssl.SSLContext)
    assert [call[0] for call in connection["calls"]] == SEND_STEPS[1:]


def test_starttls_connects_with_smtp_and_starts_tls_first(smtp: "FakeSMTP") -> None:
    send()

    (connection,) = smtp.connections
    assert connection["kind"] == "SMTP"
    assert connection["port"] == 587
    assert connection["kwargs"] == {"timeout": 30}
    assert connection["calls"][0][0] == "starttls"
    assert isinstance(connection["calls"][0][1], ssl.SSLContext)


def test_smtp_security_overrides_the_port(smtp: "FakeSMTP") -> None:
    send(settings_with(smtp_security="ssl"))

    assert [connection["kind"] for connection in smtp.connections] == ["SMTP_SSL"]


def test_both_connection_kinds_send_the_attachments(
    smtp: "FakeSMTP", tmp_path: pathlib.Path
) -> None:
    (tmp_path / "a.csv").write_text("date,value\n")

    send(settings_with(smtp_port=465), attachments=[tmp_path / "a.csv"])
    send(attachments=[tmp_path / "a.csv"])

    assert [connection["kind"] for connection in smtp.connections] == ["SMTP_SSL", "SMTP"]
    for message in smtp.messages():
        assert parts(message)[1][:2] == ("application/octet-stream", "a.csv")


# --- retries -------------------------------------------------------------------------


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
def test_transient_error_is_retried_three_times(
    smtp: "FakeSMTP", sleeps: list[float], error: typing.Any
) -> None:
    smtp.errors = [("connect", error)] * 3

    send()

    assert len(smtp.connections) == 1  # the fourth attempt connects
    assert sleeps == [5, 5, 5]


def test_transient_error_while_sending_is_retried(smtp: "FakeSMTP", sleeps: list[float]) -> None:
    smtp.errors = [("sendmail", smtplib.SMTPServerDisconnected("closed"))]

    send()

    assert len(smtp.connections) == 2
    assert len(smtp.messages()) == 1
    assert sleeps == [5]


def test_retry_sends_the_same_mail_with_its_attachments(
    smtp: "FakeSMTP", sleeps: list[float], tmp_path: pathlib.Path
) -> None:
    (tmp_path / "a.csv").write_text("date,value\n")
    smtp.errors = [("connect", TimeoutError("timed out"))]

    send(attachments=[tmp_path / "a.csv"])

    (message,) = smtp.messages()
    assert [name for _, name, _ in parts(message)] == [None, "a.csv"]


def test_transient_error_fails_after_four_attempts(smtp: "FakeSMTP", sleeps: list[float]) -> None:
    smtp.errors = [("connect", TimeoutError("timed out"))] * 5

    with pytest.raises(mail.MailError) as err:
        send()

    assert str(err.value) == "Failed to send email after 4 attempts: timed out"
    assert isinstance(err.value.__cause__, TimeoutError)
    assert not err.value.unexpected
    assert sleeps == [5, 5, 5]
    assert len(smtp.errors) == 1


def test_number_of_retries_and_delay_come_from_the_configuration(
    smtp: "FakeSMTP", sleeps: list[float]
) -> None:
    smtp.errors = [("connect", TimeoutError("timed out"))] * 2

    send(settings_with(retries=2, retry_delay=0.5))

    assert sleeps == [0.5, 0.5]
    assert len(smtp.connections) == 1


def test_no_retry_with_retries_zero(smtp: "FakeSMTP", sleeps: list[float]) -> None:
    smtp.errors = [("connect", TimeoutError("timed out"))]

    with pytest.raises(mail.MailError, match=r"^Failed to send email after 1 attempts: timed out$"):
        send(settings_with(retries=0))

    assert sleeps == []


def test_authentication_error_is_not_retried_and_not_wrapped_twice(
    smtp: "FakeSMTP", sleeps: list[float]
) -> None:
    smtp.errors = [("login", smtplib.SMTPAuthenticationError(535, b"bad credentials"))]

    with pytest.raises(mail.MailError) as err:
        send()

    assert str(err.value) == "Authentication failed: (535, b'bad credentials')"
    assert isinstance(err.value.__cause__, smtplib.SMTPAuthenticationError)
    assert not err.value.unexpected
    assert len(smtp.connections) == 1
    assert sleeps == []


@pytest.mark.parametrize(
    ("step", "error"),
    [
        ("sendmail", smtplib.SMTPSenderRefused(550, b"sender refused", "sender@example.com")),
        ("sendmail", smtplib.SMTPRecipientsRefused({"one@example.com": (550, b"unknown")})),
        ("sendmail", smtplib.SMTPDataError(554, b"rejected")),
        ("login", smtplib.SMTPHeloError(501, b"bad helo")),
        ("starttls", smtplib.SMTPNotSupportedError("STARTTLS extension not supported")),
    ],
    ids=lambda value: value if isinstance(value, str) else type(value).__name__,
)
def test_permanent_error_is_not_retried(
    smtp: "FakeSMTP", sleeps: list[float], step: str, error: typing.Any
) -> None:
    smtp.errors = [(step, error)]

    with pytest.raises(mail.MailError) as err:
        send()

    assert str(err.value) == f"Email rejected: {error}"
    assert err.value.__cause__ is error
    assert not err.value.unexpected
    assert len(smtp.connections) == 1
    assert sleeps == []


@pytest.mark.parametrize(
    ("step", "error"),
    [
        ("connect", ssl.SSLError("certificate verify failed")),
        ("connect", OSError(113, "No route to host")),
        ("sendmail", smtplib.SMTPResponseException(451, b"try again later")),
        ("login", RuntimeError("boom")),
    ],
    ids=lambda value: value if isinstance(value, str) else type(value).__name__,
)
def test_other_errors_are_not_retried(
    smtp: "FakeSMTP", sleeps: list[float], step: str, error: Exception
) -> None:
    smtp.errors = [(step, error)]

    with pytest.raises(mail.MailError) as err:
        send()

    # the type of the error is part of the message, as in collector.send_data_mail (P011-S2)
    assert str(err.value) == (
        f"Unexpected error while sending email: {type(error).__name__}: {error}"
    )
    assert err.value.unexpected
    assert err.value.__cause__ is error
    assert sleeps == []


# --- ending the session after the mail was accepted (P009-S2) ------------------------


@pytest.mark.parametrize(
    "error",
    [
        # the connection breaks or times out before the answer to QUIT
        smtplib.SMTPServerDisconnected("Connection unexpectedly closed"),
        TimeoutError("timed out"),
        # an answer other than 221 to QUIT
        smtplib.SMTPResponseException(421, b"closing"),
        RuntimeError("unexpected"),
    ],
    ids=lambda error: type(error).__name__,
)
def test_error_while_ending_the_session_neither_sends_again_nor_fails(
    smtp: "FakeSMTP", sleeps: list[float], caplog: pytest.LogCaptureFixture, error: Exception
) -> None:
    smtp.errors = [("quit", error)]
    caplog.set_level(logging.WARNING, logger="gruenbeck")

    send()

    (connection,) = smtp.connections
    assert [call[0] for call in connection["calls"]] == [
        "starttls",
        "login",
        "send_message",
        "sendmail",
        "close",
        "exit",
    ]
    assert len(smtp.raw_messages()) == 1
    assert sleeps == []
    assert [(r.name, r.levelno, r.getMessage()) for r in caplog.records] == [
        (
            "gruenbeck.mail",
            logging.WARNING,
            f"mail sent, but ending the SMTP session failed: {error}",
        )
    ]


def test_ending_a_real_session_closes_it_so_the_with_block_does_not_quit_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # smtplib.SMTP itself (not the fake): never connected, so QUIT cannot be sent
    server = smtplib.SMTP()
    caplog.set_level(logging.WARNING, logger="gruenbeck")

    with server:
        mail._end_session(server)

    assert server.sock is None
    assert [r.getMessage() for r in caplog.records] == [
        "mail sent, but ending the SMTP session failed: please run connect() first"
    ]


# --- HTML part (P007-S4) ------------------------------------------------------------

HTML = "<!DOCTYPE html><html><body><p>the <b>stored</b> data</p></body></html>"


def test_mail_with_html_is_multipart_alternative_with_the_html_last(smtp: "FakeSMTP") -> None:
    send(text="the text", html=HTML)

    (message,) = smtp.messages()
    assert message.get_content_type() == "multipart/alternative"
    assert parts(message) == [("text/plain", None, "the text\n"), ("text/html", None, HTML + "\n")]
    # the mail program shows the last part it can, so the HTML is the preferred one
    body = message.get_body(preferencelist=("html", "plain"))
    assert body is not None
    assert body.get_content_type() == "text/html"


def test_mail_with_html_and_attachments_keeps_both_in_one_multipart_mixed_mail(
    smtp: "FakeSMTP", tmp_path: pathlib.Path
) -> None:
    (tmp_path / "a.csv").write_text("date,value\n")
    (tmp_path / "b.csv").write_text("date,value\n")

    send(text="the text", html=HTML, attachments=sorted(tmp_path.glob("*.csv")))

    (message,) = smtp.messages()
    assert message.get_content_type() == "multipart/mixed"
    alternative, *attachments = message.iter_parts()
    assert alternative.get_content_type() == "multipart/alternative"
    assert [(part.get_content_type(), part.get_content()) for part in alternative.iter_parts()] == [
        ("text/plain", "the text\n"),
        ("text/html", HTML + "\n"),
    ]
    assert [(part.get_content_type(), part.get_filename()) for part in attachments] == [
        ("application/octet-stream", "a.csv"),
        ("application/octet-stream", "b.csv"),
    ]


def test_html_with_non_ascii_text_is_sent_as_utf8(smtp: "FakeSMTP") -> None:
    html = "<html><body><p>11-16 \N{EN DASH} 11-22 \N{NO-BREAK SPACE}</p></body></html>"

    send(text="11-16 - 11-22", html=html)

    (message,) = smtp.messages()
    _, html_part = message.iter_parts()
    assert html_part.get_content_charset() == "utf-8"
    assert html_part.get_content() == html + "\n"


def test_long_lines_of_the_html_survive_the_transmission(smtp: "FakeSMTP") -> None:
    html = "<html><body>" + '<p><span class="x">1</span></p>' * 2000 + "</body></html>"

    send(text="the text", html=html)

    (raw,) = smtp.raw_messages()
    assert max(len(line) for line in raw.split(b"\r\n")) <= 998
    (message,) = smtp.messages()
    assert parts(message)[1][2] == html + "\n"


def test_unreadable_attachment_is_named_in_the_text_and_in_the_html(
    smtp: "FakeSMTP", tmp_path: pathlib.Path
) -> None:
    (tmp_path / "a<b>&.csv").mkdir()  # cannot be read as a file

    send(text="body", html=HTML, attachments=[tmp_path / "a<b>&.csv"])

    (message,) = smtp.messages()
    # no attachment is left, so the mail is the text and the HTML
    assert message.get_content_type() == "multipart/alternative"
    text, html = (part.get_content() for part in message.iter_parts())
    assert text.startswith("body\n\nError attaching file a<b>&.csv: [Errno 21]")
    # the note is escaped and inside the body of the document
    assert (
        '<p style="margin:12px 16px;font-size:13px;">Error attaching file a&lt;b&gt;&amp;.csv:'
        in html
    )
    assert html.index("Error attaching file") < html.index("</body>")
    assert html.rstrip().endswith("</body></html>")


def test_notes_go_to_the_end_of_a_html_without_body() -> None:
    assert mail.add_notes_to_html("<p>x</p>", ["a & b"]) == (
        '<p>x</p><p style="margin:12px 16px;font-size:13px;">a &amp; b</p>'
    )
    assert mail.add_notes_to_html("<p>x</p>", []) == "<p>x</p>"


def test_mail_without_html_stays_as_before(smtp: "FakeSMTP", tmp_path: pathlib.Path) -> None:
    (tmp_path / "a.csv").write_text("a")

    send(text="the text", attachments=[tmp_path / "a.csv"], html=None)

    (message,) = smtp.messages()
    assert message.get_content_type() == "multipart/mixed"
    assert [kind for kind, _, _ in parts(message)] == ["text/plain", "application/octet-stream"]
