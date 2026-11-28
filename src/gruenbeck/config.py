"""
configuration file of the data collector: loading and checking

load_configuration() reads the JSON file into a Configuration and checks required keys,
types and values. A relative path (dataPath) starts at the folder of the
configuration file, not at the working directory. load_soft_water_system() reads and checks
only the section softWaterSystem, for a command that needs nothing else (gruenbeck.rollover).

The file of the commands is --config-file; its default is the environment variable
GRUENBECK_CONFIG if it is set, else ./src/config.json (add_config_file_option()). The SMTP
password can come from the systemd credential "smtp-password" instead of the key
mail.senderPassword.
"""

import argparse
import dataclasses
import datetime
import json
import logging
import math
import os
import pathlib
import re
import typing
import warnings

from gruenbeck import device, errors

logger = logging.getLogger(__name__)

FIRST_DATE_FORMAT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
# dates to check dataFile.datePattern with: written and read back, they must stay the same
PATTERN_CHECK_DATES = (datetime.date(2026, 1, 2), datetime.date(2027, 12, 31))
SMTP_SECURITY = ("ssl", "starttls")
# the default of --config-file: this environment variable if set and not empty, else the file
CONFIG_FILE_ENV = "GRUENBECK_CONFIG"
DEFAULT_CONFIG_FILE = "./src/config.json"
# systemd puts the credentials of LoadCredential= into the folder this variable names
CREDENTIALS_DIRECTORY_ENV = "CREDENTIALS_DIRECTORY"
PASSWORD_CREDENTIAL = "smtp-password"
# defaults of the optional keys retries and retryDelay of softWaterSystem and mail:
# repeated attempts after a temporary error and the seconds to wait (see gruenbeck.device
# and gruenbeck.mail for what the delay means)
DEVICE_RETRIES = 5
DEVICE_RETRY_DELAY = 5
MAIL_RETRIES = 3
MAIL_RETRY_DELAY = 5
_MISSING = object()


class ConfigurationError(errors.GruenbeckError, ValueError):
    """
    the configuration file is invalid; str() lists every problem

    `mail` is the mail section if that part is valid (to send the error mail), else None.
    Also a ValueError: the file has an invalid value.
    """

    def __init__(self, problems: list[str], mail: "Mail | None" = None):
        super().__init__("; ".join(problems))
        self.problems = problems
        self.mail = mail


@dataclasses.dataclass(frozen=True)
class FieldNames:
    """column names of the yearly data files (dataFile.fieldnames)"""

    date: str
    value: str


@dataclasses.dataclass(frozen=True)
class DataFile:
    """name and format of the yearly data files (dataFile)"""

    date_pattern: str
    fieldnames: FieldNames
    prefix: str
    first_date: datetime.date | None


@dataclasses.dataclass(frozen=True)
class Mail:
    """SMTP server, sender and recipients (mail)"""

    smtp_server: str
    smtp_port: int
    smtp_security: str | None
    sender_email: str
    # the password stays in the configuration file only; repr() leaves it out of logs
    sender_password: str = dataclasses.field(repr=False)
    recipients: tuple[str, ...]
    subject: str
    retries: int
    retry_delay: float


@dataclasses.dataclass(frozen=True)
class SoftWaterSystem:
    """web server of the soft water system (softWaterSystem)"""

    host: str
    timeout: float
    retries: int
    retry_delay: float


@dataclasses.dataclass(frozen=True)
class Configuration:
    """the checked configuration file"""

    file: pathlib.Path
    data_path: pathlib.Path
    data_file: DataFile
    mail: Mail
    soft_water_system: SoftWaterSystem


class _Section:
    """reads the keys of one object of the JSON file and records the problems"""

    def __init__(self, data: dict[str, typing.Any], prefix: str, problems: list[str]):
        self.data = data
        self.prefix = prefix
        self.problems = problems
        self.read: set[str] = set()

    def name(self, key: str) -> str:
        return f"{self.prefix}.{key}" if self.prefix else key

    def problem(self, key: str, value: object, reason: str) -> None:
        self.problems.append(f"invalid config parameter {self.name(key)} {value!r}: {reason}")

    def value(self, key: str, required: bool = True) -> typing.Any:
        self.read.add(key)
        if key not in self.data:
            if required:
                self.problems.append(f"no config parameter: {self.name(key)!r}")
            return _MISSING
        return self.data[key]

    def text(self, key: str, allow_empty: bool = False) -> str | None:
        value = self.value(key)
        if value is _MISSING:
            return None
        if not isinstance(value, str) or not (allow_empty or value.strip()):
            self.problem(
                key, value, "expected a text" if allow_empty else "expected a non-empty text"
            )
            return None
        return value

    def section(self, key: str) -> "_Section | None":
        value = self.value(key)
        if value is _MISSING:
            return None
        if not isinstance(value, dict):
            self.problem(key, value, "expected an object")
            return None
        return _Section(value, self.name(key), self.problems)

    def warn_unknown(self) -> None:
        for key in self.data:
            if key not in self.read:
                logger.warning("unknown config parameter %r is ignored", self.name(key))


def default_config_file() -> str:
    """the default of --config-file: $GRUENBECK_CONFIG if it is set and not empty, else the file"""
    return os.environ.get(CONFIG_FILE_ENV) or DEFAULT_CONFIG_FILE


def add_config_file_option(parser: argparse.ArgumentParser) -> None:
    """add --config-file / -c with the default of default_config_file() to a command"""
    parser.add_argument(
        "--config-file",
        "-c",
        default=default_config_file(),
        help=(
            "set config file (default: the environment variable"
            f" {CONFIG_FILE_ENV} if it is set, else {DEFAULT_CONFIG_FILE})"
        ),
    )


def read_configuration_file(configuration_file: str | os.PathLike[str]) -> dict[str, typing.Any]:
    """
    the JSON object of the configuration file, not checked
    :raises FileNotFoundError: the file does not exist
    :raises ConfigurationError: the file is not valid JSON or not a JSON object
    """
    path = pathlib.Path(configuration_file)
    with path.open(encoding="utf-8") as json_data_file:
        try:
            data = json.load(json_data_file)
        except json.JSONDecodeError as err:
            raise ConfigurationError(
                [f"configuration file {path} is not valid JSON: {err}"]
            ) from err
    if not isinstance(data, dict):
        raise ConfigurationError([f"configuration file {path} must contain a JSON object"])
    return data


def load_configuration(
    configuration_file: str | os.PathLike[str], *, password_required: bool = True
) -> Configuration:
    """
    read and check the configuration file
    :param configuration_file: path of the JSON file
    :param password_required: False for a command that never logs in to the SMTP server
        (gruenbeck-analyse, the preview without --send-to): a missing SMTP password is then no
        problem and `mail.sender_password` is empty. A password that is there is checked.
    :return: Configuration with absolute paths
    :raises FileNotFoundError: the file does not exist
    :raises ConfigurationError: a key is missing or has an invalid value
    """
    path = pathlib.Path(configuration_file)
    data = read_configuration_file(path)
    base = path.resolve().parent
    problems: list[str] = []
    top = _Section(data, "", problems)

    # first, so the error mail can report the problems of the other parts
    mail = _read_mail(top.section("mail"), password_required)
    soft_water_system = _read_soft_water_system(top.section("softWaterSystem"))
    data_file = _read_data_file(top.section("dataFile"))
    data_path = _read_path(top, "dataPath", base)
    top.warn_unknown()

    if problems:
        raise ConfigurationError(problems, mail)
    # without problems every part is set
    return Configuration(
        file=path.resolve(),
        data_path=typing.cast(pathlib.Path, data_path),
        data_file=typing.cast(DataFile, data_file),
        mail=typing.cast(Mail, mail),
        soft_water_system=typing.cast(SoftWaterSystem, soft_water_system),
    )


def load_soft_water_system(configuration_file: str | os.PathLike[str]) -> SoftWaterSystem:
    """
    read and check only the section softWaterSystem, with the rules of load_configuration()
    Unknown keys of the section are ignored with a warning; the other sections of the file are
    neither checked nor reported as unknown.
    :param configuration_file: path of the JSON file
    :raises FileNotFoundError: the file does not exist
    :raises ConfigurationError: every problem of the section (also: it is missing or no object)
    """
    data = read_configuration_file(configuration_file)
    problems: list[str] = []
    soft_water_system = _read_soft_water_system(
        _Section(data, "", problems).section("softWaterSystem")
    )
    if problems:
        raise ConfigurationError(problems)
    # without problems the section is set
    return typing.cast(SoftWaterSystem, soft_water_system)


def _read_path(section: _Section, key: str, base: pathlib.Path) -> pathlib.Path | None:
    """absolute path of a path parameter; a relative path starts at `base`, the config folder"""
    text = section.text(key)
    if text is None:
        return None
    path = pathlib.Path(text)
    return path if path.is_absolute() else (base / path).resolve()


def _read_mail(section: _Section | None, password_required: bool) -> Mail | None:
    if section is None:
        return None
    count = len(section.problems)
    smtp_server = section.text("smtpServer")
    smtp_port = _read_port(section, "smtpPort")
    smtp_security = _read_security(section, "smtpSecurity")
    sender_email = section.text("senderEmail")
    sender_password = _read_sender_password(section, password_required)
    recipients = _read_recipients(section, "recipients")
    subject = section.text("subject", allow_empty=True)
    retries = _read_retries(section, MAIL_RETRIES)
    retry_delay = _read_retry_delay(section, MAIL_RETRY_DELAY)
    section.warn_unknown()
    if len(section.problems) > count:
        return None
    return Mail(
        smtp_server=typing.cast(str, smtp_server),
        smtp_port=typing.cast(int, smtp_port),
        smtp_security=smtp_security,
        sender_email=typing.cast(str, sender_email),
        sender_password=typing.cast(str, sender_password),
        recipients=typing.cast(tuple[str, ...], recipients),
        subject=typing.cast(str, subject),
        retries=typing.cast(int, retries),
        retry_delay=typing.cast(float, retry_delay),
    )


class _CredentialError(Exception):
    """the credential is there, but cannot be used; the text names the file, never the content"""


def _read_password_credential() -> str | None:
    """
    the SMTP password of the credential "smtp-password" of systemd, without the final line break
    :return: the password, or None if there is no credential
    :raises _CredentialError: the credential cannot be read or is empty
    """
    folder = os.environ.get(CREDENTIALS_DIRECTORY_ENV)
    if not folder:
        return None
    path = pathlib.Path(folder) / PASSWORD_CREDENTIAL
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except UnicodeDecodeError:
        # no chained error: its text names bytes of the file
        raise _CredentialError(f"the credential {path} is not valid UTF-8") from None
    except OSError as err:
        raise _CredentialError(f"cannot read the credential {path}: {err}") from err
    password = text.removesuffix("\n").removesuffix("\r") if text.endswith("\n") else text
    if not password.strip():
        raise _CredentialError(f"the credential {path} is empty")
    return password


def _read_sender_password(section: _Section, required: bool) -> str | None:
    """
    the SMTP password: the credential if there is one, else mail.senderPassword
    Both together are no problem, but the credential wins and the log gets a warning.
    Neither is a problem only if the password is required (see load_configuration()).
    """
    key = "senderPassword"
    try:
        credential = _read_password_credential()
    except _CredentialError as err:
        section.read.add(key)
        section.problems.append(str(err))
        return None
    if credential is not None:
        if section.value(key, required=False) is not _MISSING:
            logger.warning(
                "the credential %r is used as SMTP password; remove %r from the configuration file",
                PASSWORD_CREDENTIAL,
                section.name(key),
            )
        return credential
    if key in section.data:
        return section.text(key)
    section.read.add(key)
    if not required:
        return ""
    section.problems.append(
        f"no SMTP password: set {section.name(key)!r} in the configuration file or provide the"
        f" credential {PASSWORD_CREDENTIAL!r} (systemd LoadCredential=, found through"
        f" ${CREDENTIALS_DIRECTORY_ENV})"
    )
    return None


def _read_port(section: _Section, key: str) -> int | None:
    value = section.value(key)
    if value is _MISSING:
        return None
    port = None
    if isinstance(value, int) and not isinstance(value, bool):
        port = value
    elif isinstance(value, str) and value.strip().isdigit():
        port = int(value.strip())
    if port is None or not 1 <= port <= 65535:
        section.problem(key, value, "expected a port number 1 ... 65535")
        return None
    return port


def _read_security(section: _Section, key: str) -> str | None:
    value = section.value(key, required=False)
    if value is _MISSING or value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in SMTP_SECURITY:
        return value.strip().lower()
    section.problem(key, value, "expected 'ssl' or 'starttls'")
    return None


def _read_recipients(section: _Section, key: str) -> tuple[str, ...] | None:
    value = section.value(key)
    if value is _MISSING:
        return None
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        section.problem(key, value, "expected a non-empty list of mail addresses")
        return None
    return tuple(value)


def _read_soft_water_system(section: _Section | None) -> SoftWaterSystem | None:
    if section is None:
        return None
    count = len(section.problems)
    host = section.text("host")
    timeout = _read_timeout(section, "timeout")
    retries = _read_retries(section, DEVICE_RETRIES)
    retry_delay = _read_retry_delay(section, DEVICE_RETRY_DELAY)
    section.warn_unknown()
    if len(section.problems) > count:
        return None
    return SoftWaterSystem(
        host=typing.cast(str, host),
        timeout=typing.cast(float, timeout),
        retries=typing.cast(int, retries),
        retry_delay=typing.cast(float, retry_delay),
    )


def _read_timeout(section: _Section, key: str) -> float | None:
    value = section.value(key, required=False)
    if value is _MISSING:
        return float(device.DEFAULT_TIMEOUT)
    if isinstance(value, bool):
        section.problem(key, value, "expected a number")
        return None
    try:
        timeout = float(value)
    except (TypeError, ValueError) as err:
        section.problem(key, value, f"{err}")
        return None
    if not 0 < timeout < math.inf:
        section.problem(key, value, "must be a number greater than 0")
        return None
    return timeout


def _read_retries(section: _Section, default: int) -> int | None:
    """optional key retries: whole number of repeated attempts, 0 for none"""
    value = section.value("retries", required=False)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        section.problem("retries", value, "must be a whole number, 0 or greater")
        return None
    return value


def _read_retry_delay(section: _Section, default: float) -> float | None:
    """optional key retryDelay: seconds, 0 for no waiting"""
    value = section.value("retryDelay", required=False)
    if value is _MISSING:
        return float(default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value < math.inf:
        section.problem("retryDelay", value, "must be a number, 0 or greater")
        return None
    return float(value)


def _read_data_file(section: _Section | None) -> DataFile | None:
    if section is None:
        return None
    count = len(section.problems)
    date_pattern = _read_date_pattern(section, "datePattern")
    fieldnames = _read_fieldnames(section.section("fieldnames"))
    prefix = section.text("prefix")
    if prefix is not None and ("/" in prefix or os.sep in prefix):
        section.problem("prefix", prefix, "must not contain a path separator")
    first_date = _read_first_date(section, "firstDate")
    section.warn_unknown()
    if len(section.problems) > count:
        return None
    return DataFile(
        date_pattern=typing.cast(str, date_pattern),
        fieldnames=typing.cast(FieldNames, fieldnames),
        prefix=typing.cast(str, prefix),
        first_date=first_date,
    )


def _read_date_pattern(section: _Section, key: str) -> str | None:
    pattern = section.text(key)
    if pattern is None:
        return None
    try:
        # Python 3.14 warns about a day without a year (from 3.15 on it may fail)
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            unchanged = all(
                datetime.datetime.strptime(day.strftime(pattern), pattern).date() == day
                for day in PATTERN_CHECK_DATES
            )
    except (ValueError, DeprecationWarning):
        unchanged = False
    if not unchanged:
        section.problem(
            key, pattern, "expected a date format with year, month and day, e.g. '%Y-%m-%d'"
        )
        return None
    return pattern


def _read_fieldnames(section: _Section | None) -> FieldNames | None:
    if section is None:
        return None
    count = len(section.problems)
    date = section.text("date")
    value = section.text("value")
    if date is not None and date == value:
        section.problem("value", value, "must differ from the date column")
    section.warn_unknown()
    if len(section.problems) > count:
        return None
    return FieldNames(date=typing.cast(str, date), value=typing.cast(str, value))


def _read_first_date(section: _Section, key: str) -> datetime.date | None:
    """optional dataFile.firstDate (YYYY-MM-DD): values of earlier days are not written"""
    value = section.value(key, required=False)
    if value is _MISSING:
        return None
    try:
        if not isinstance(value, str) or not FIRST_DATE_FORMAT.fullmatch(value):
            raise ValueError("expected a date YYYY-MM-DD")
        return datetime.date.fromisoformat(value)
    except ValueError as err:
        section.problem(key, value, f"{err}")
        return None
