"""
Preview the data mail without asking the device.

Read-only tool: it builds the data mail (text, HTML with the charts, CSV files) from the
yearly files in the data folder, exactly as the data collector does after a run, but does
not request the device and does not change a file in the data folder. By default it only
reports what was built. Warnings of the statistics and the charts go to stderr.

Options:

    --config-file FILE   configuration file (default ./src/config.json)
    --today YYYY-MM-DD   the day of the run (default: today); a Monday and a Thursday
                         report the same week, the day before a month ends does not
    --output-dir DIR     write data-mail.txt and data-mail.html into DIR (created if
                         missing), to open the HTML in a browser
    --send-to ADDRESS    send the mail, with the CSV files, to this address only (not to
                         the recipients of the configuration) and with the prefix
                         "[preview] " in the subject; without it nothing is sent

Usage from the repository root (same place as the data collector):

    uv run gruenbeck-preview-mail --output-dir ./log/preview
    uv run gruenbeck-preview-mail --send-to me@example.com

Exit code 0 if the mail was built (and written or sent as asked), 1 on an error in the
configuration, the data folder, the output folder or the sending.
"""

import argparse
import dataclasses
import datetime
import pathlib
import sys

import gruenbeck.collector
import gruenbeck.config
import gruenbeck.errors
import gruenbeck.mail

TEXT_FILE = "data-mail.txt"
HTML_FILE = "data-mail.html"
SUBJECT_PREFIX = "[preview] "


def local_today() -> datetime.date:
    """the current local day"""
    return datetime.date.today()


def day_of(text: str) -> datetime.date:
    """argparse type: a day as YYYY-MM-DD"""
    try:
        return datetime.date.fromisoformat(text)
    except ValueError as err:
        raise argparse.ArgumentTypeError(f"not a day (YYYY-MM-DD): {text}") from err


def address_of(text: str) -> str:
    """argparse type: a mail address (the mail program checks the rest)"""
    address = text.strip()
    if not address:
        raise argparse.ArgumentTypeError("must not be empty")
    return address


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="build the data mail from the stored data without asking the device"
    )
    parser.add_argument("--config-file", "-c", default="./src/config.json", help="set config file")
    parser.add_argument(
        "--today",
        type=day_of,
        default=None,
        help="day of the run as YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--output-dir",
        type=pathlib.Path,
        default=None,
        help=f"write {TEXT_FILE} and {HTML_FILE} into this folder (default: write nothing)",
    )
    parser.add_argument(
        "--send-to",
        type=address_of,
        default=None,
        metavar="ADDRESS",
        help="send the mail to this address only, with the subject prefix"
        f" {SUBJECT_PREFIX.strip()!r} (default: send nothing)",
    )
    return parser.parse_args(argv)


def describe(
    data_mail: gruenbeck.collector.DataMail, today: datetime.date, data_path: pathlib.Path
) -> list[str]:
    """the lines that tell what was built"""
    html = (
        f"{len(data_mail.html)} characters"
        if data_mail.html is not None
        else "none (the data mail would have the text only)"
    )
    files = ", ".join(path.name for path in data_mail.files) or "none"
    return [
        f"[*] data mail for the run on {today} from {data_path}",
        f"[*] text: {len(data_mail.text.splitlines())} lines",
        f"[*] html: {html}",
        f"[*] attachments: {files}",
    ]


def write_output(
    output_dir: pathlib.Path, data_mail: gruenbeck.collector.DataMail
) -> list[pathlib.Path]:
    """
    write the text and, if it was made, the HTML of the mail
    :return: the files written
    :raises OSError: the folder or a file cannot be written
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    text_file = output_dir / TEXT_FILE
    # a mail program ends the text with a line break as well
    text_file.write_text(data_mail.text.rstrip("\n") + "\n", encoding="utf-8")
    written.append(text_file)
    if data_mail.html is not None:
        html_file = output_dir / HTML_FILE
        html_file.write_text(data_mail.html, encoding="utf-8")
        written.append(html_file)
    return written


def send_preview(
    settings: gruenbeck.config.Mail, data_mail: gruenbeck.collector.DataMail, address: str
) -> str:
    """
    send the mail to the address only
    :return: the subject of the mail
    :raises gruenbeck.mail.MailError: the mail cannot be built or sent
    """
    # the sender and the server stay the ones of the configuration
    preview = dataclasses.replace(
        settings, recipients=(address,), subject=SUBJECT_PREFIX + settings.subject
    )
    gruenbeck.mail.send_mail(
        preview, preview.subject, data_mail.text, data_mail.files, html=data_mail.html
    )
    return preview.subject


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    today = args.today or local_today()

    try:
        config = gruenbeck.config.load_configuration(args.config_file)
    except FileNotFoundError as err:
        print(f"[-] no configuration: {err}", file=sys.stderr)
        return 1
    except gruenbeck.config.ConfigurationError as err:
        print(f"[-] invalid configuration: {err}", file=sys.stderr)
        return 1

    try:
        data_mail = gruenbeck.collector.compose_data_mail(config, config.data_path, today)
    except gruenbeck.errors.GruenbeckError as err:
        print(f"[-] {err}", file=sys.stderr)
        return 1
    for line in describe(data_mail, today, config.data_path):
        print(line, flush=True)

    if args.output_dir is not None:
        if data_mail.html is None:
            print(f"[!] no HTML part was made: {HTML_FILE} is not written", file=sys.stderr)
        try:
            for path in write_output(args.output_dir, data_mail):
                print(f"[*] wrote {path}", flush=True)
        except OSError as err:
            print(f"[-] cannot write the mail into {args.output_dir}: {err}", file=sys.stderr)
            return 1

    if args.send_to is not None:
        try:
            subject = send_preview(config.mail, data_mail, args.send_to)
        except gruenbeck.errors.GruenbeckError as err:
            print(f"[-] sending the mail failed: {err}", file=sys.stderr)
            return 1
        print(f"[*] sent to {args.send_to}: {subject}", flush=True)
    return 0
