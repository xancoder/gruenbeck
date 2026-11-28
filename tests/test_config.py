"""configuration file: loading, checking and the paths (P006-S3)"""

import argparse
import collections.abc
import copy
import datetime
import json
import logging
import math
import pathlib
import typing

import pytest

import gruenbeck.config
from gruenbeck import config as configuration

# --- valid configurations -----------------------------------------------------------


def test_example_configuration_is_valid(
    config_example_file: pathlib.Path, repo_root: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    loaded = configuration.load_configuration(config_example_file)

    assert loaded.file == config_example_file
    # relative paths start at src/, the folder of the configuration file
    assert loaded.data_path == repo_root / "data"
    assert loaded.data_file == configuration.DataFile(
        date_pattern="%Y-%m-%d",
        fieldnames=configuration.FieldNames(date="date", value="value"),
        prefix="gruenbeck_water_consumption",
        first_date=datetime.date(2026, 11, 20),
    )
    assert loaded.mail.smtp_port == 587
    assert loaded.mail.smtp_security == "starttls"
    assert loaded.mail.recipients == ("receiver@example.com",)
    assert loaded.soft_water_system == configuration.SoftWaterSystem(
        host="softliq-sc.example.lan", timeout=30.0, retries=5, retry_delay=5.0
    )
    # every key of the example is known
    assert caplog.records == []


def test_values_are_typed(
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
    tmp_path: pathlib.Path,
) -> None:
    config_data["mail"].update(
        smtpPort=" 465 ", smtpSecurity=" SSL ", subject="", retries=2, retryDelay=1.5
    )
    config_data["softWaterSystem"].update(timeout="2.5", retries=0, retryDelay=0.5)
    config_data["dataFile"]["firstDate"] = "2026-11-20"

    loaded = configuration.load_configuration(write_config(config_data))

    assert loaded == configuration.Configuration(
        file=tmp_path / "config.json",
        data_path=tmp_path / "data",
        data_file=configuration.DataFile(
            date_pattern="%Y-%m-%d",
            fieldnames=configuration.FieldNames(date="date", value="value"),
            prefix="gruenbeck_water_consumption",
            first_date=datetime.date(2026, 11, 20),
        ),
        mail=configuration.Mail(
            smtp_server="smtp.example.com",
            smtp_port=465,
            smtp_security="ssl",
            sender_email="sender@example.com",
            sender_password="test-password",
            recipients=("receiver@example.com",),
            subject="",
            retries=2,
            retry_delay=1.5,
        ),
        soft_water_system=configuration.SoftWaterSystem(
            host="device.lan", timeout=2.5, retries=0, retry_delay=0.5
        ),
    )


def test_optional_keys_have_defaults(loaded_config: gruenbeck.config.Configuration) -> None:
    assert loaded_config.data_file.first_date is None
    assert loaded_config.mail.smtp_security is None
    assert loaded_config.soft_water_system.timeout == 30.0
    assert type(loaded_config.soft_water_system.timeout) is float


def test_retry_defaults(loaded_config: gruenbeck.config.Configuration) -> None:
    # the device is asked again for about 2.5 minutes, the mail for about 15 seconds
    water, mail = loaded_config.soft_water_system, loaded_config.mail
    assert (water.retries, water.retry_delay) == (5, 5.0)
    assert (mail.retries, mail.retry_delay) == (3, 5.0)
    assert type(water.retry_delay) is float
    assert type(mail.retry_delay) is float


@pytest.mark.parametrize("section", ["softWaterSystem", "mail"])
@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("retries", 0, 0),
        ("retries", 1, 1),
        ("retries", 10, 10),
        ("retryDelay", 0, 0.0),
        ("retryDelay", 0.5, 0.5),
        ("retryDelay", 30, 30.0),
    ],
)
def test_retries_and_retry_delay(
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
    caplog: pytest.LogCaptureFixture,
    section: str,
    key: str,
    value: float,
    expected: float,
) -> None:
    config_data[section][key] = value

    loaded = configuration.load_configuration(write_config(config_data))

    part = loaded.soft_water_system if section == "softWaterSystem" else loaded.mail
    result = part.retries if key == "retries" else part.retry_delay
    assert result == expected
    assert type(result) is type(expected)
    # known keys: no warning about an unknown parameter
    assert caplog.records == []


@pytest.mark.parametrize("port", [1, 25, 65535])
def test_port_numbers_from_1_to_65535_are_valid(
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
    port: int,
) -> None:
    config_data["mail"]["smtpPort"] = port

    assert configuration.load_configuration(write_config(config_data)).mail.smtp_port == port


def test_retries_of_the_sections_are_independent(
    config_data: dict[str, typing.Any], write_config: collections.abc.Callable[..., pathlib.Path]
) -> None:
    config_data["softWaterSystem"].update(retries=1, retryDelay=2)

    loaded = configuration.load_configuration(write_config(config_data))

    assert (loaded.soft_water_system.retries, loaded.soft_water_system.retry_delay) == (1, 2.0)
    assert (loaded.mail.retries, loaded.mail.retry_delay) == (3, 5.0)


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("timeout", 5, 5.0),
        ("timeout", 0.1, 0.1),
        ("timeout", "2.5", 2.5),
    ],
)
def test_device_timeout(
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
    key: str,
    value: float | str,
    expected: float,
) -> None:
    config_data["softWaterSystem"][key] = value

    loaded = configuration.load_configuration(write_config(config_data))

    assert loaded.soft_water_system.timeout == expected


@pytest.mark.parametrize("pattern", ["%Y-%m-%d", "%d.%m.%Y", "%Y%m%d", "%d/%m/%Y", "%Y-%j"])
def test_date_patterns_with_year_month_and_day(
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
    pattern: str,
) -> None:
    config_data["dataFile"]["datePattern"] = pattern

    loaded = configuration.load_configuration(write_config(config_data))

    assert loaded.data_file.date_pattern == pattern


def test_smtp_security_null_is_derived_from_the_port(
    config_data: dict[str, typing.Any], write_config: collections.abc.Callable[..., pathlib.Path]
) -> None:
    config_data["mail"]["smtpSecurity"] = None

    loaded = configuration.load_configuration(write_config(config_data))

    assert loaded.mail.smtp_security is None


def test_mail_port_and_security_are_normalized(
    config_data: dict[str, typing.Any], write_config: collections.abc.Callable[..., pathlib.Path]
) -> None:
    config_data["mail"].update(smtpPort="465", smtpSecurity=" SSL ")

    loaded = configuration.load_configuration(write_config(config_data))

    assert (loaded.mail.smtp_port, loaded.mail.smtp_security) == (465, "ssl")


# --- the SMTP password: mail.senderPassword or the credential "smtp-password" ----------

SECRET = "s3cret-from-the-credential"


@pytest.fixture
def credentials(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """the folder of $CREDENTIALS_DIRECTORY, still empty"""
    folder = tmp_path / "credentials"
    folder.mkdir()
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(folder))
    return folder


@pytest.mark.parametrize(
    ("content", "password"),
    [
        (SECRET, SECRET),
        (SECRET + "\n", SECRET),
        (SECRET + "\r\n", SECRET),
        # only one final line break belongs to the file, not to the password
        (SECRET + "\n\n", SECRET + "\n"),
        (" a b ", " a b "),
    ],
)
def test_credential_is_the_password(
    credentials: pathlib.Path,
    content: str,
    password: str,
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
    caplog: pytest.LogCaptureFixture,
) -> None:
    del config_data["mail"]["senderPassword"]
    (credentials / "smtp-password").write_bytes(content.encode())

    loaded = configuration.load_configuration(write_config(config_data))

    assert loaded.mail.sender_password == password
    assert caplog.records == []


def test_credential_wins_over_the_key_and_the_log_asks_to_remove_it(
    credentials: pathlib.Path,
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
    caplog: pytest.LogCaptureFixture,
) -> None:
    (credentials / "smtp-password").write_text(SECRET + "\n")

    loaded = configuration.load_configuration(write_config(config_data))

    assert loaded.mail.sender_password == SECRET
    assert [(r.levelno, r.getMessage()) for r in caplog.records] == [
        (
            logging.WARNING,
            "the credential 'smtp-password' is used as SMTP password;"
            " remove 'mail.senderPassword' from the configuration file",
        )
    ]
    assert SECRET not in caplog.text
    assert "test-password" not in caplog.text


def test_credential_folder_without_the_credential_falls_back_to_the_key(
    credentials: pathlib.Path,
    loaded_config: configuration.Configuration,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # systemd lists every credential of the unit in the folder, not only this one
    (credentials / "other").write_text("x")

    assert loaded_config.mail.sender_password == "test-password"
    assert caplog.records == []


@pytest.mark.parametrize("folder", [None, ""])
def test_no_credential_folder_uses_the_key(
    monkeypatch: pytest.MonkeyPatch,
    folder: str | None,
    loaded_config: configuration.Configuration,
) -> None:
    if folder is not None:
        monkeypatch.setenv("CREDENTIALS_DIRECTORY", folder)

    assert loaded_config.mail.sender_password == "test-password"


@pytest.mark.parametrize("with_folder", [True, False])
def test_missing_password_names_both_ways(
    with_folder: bool,
    request: pytest.FixtureRequest,
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
) -> None:
    if with_folder:
        request.getfixturevalue("credentials")
    del config_data["mail"]["senderPassword"]

    assert problems(config_data, write_config) == [
        "no SMTP password: set 'mail.senderPassword' in the configuration file or provide the"
        " credential 'smtp-password' (systemd LoadCredential=, found through"
        " $CREDENTIALS_DIRECTORY)"
    ]


def test_password_is_optional_where_it_is_not_needed(
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
    credentials: pathlib.Path,
) -> None:
    del config_data["mail"]["senderPassword"]
    path = write_config(config_data)

    loaded = configuration.load_configuration(path, password_required=False)

    assert loaded.mail.sender_password == ""
    assert loaded.mail.sender_email == "sender@example.com"
    # the default stays strict
    with pytest.raises(configuration.ConfigurationError, match="no SMTP password"):
        configuration.load_configuration(path)


def test_password_that_is_there_is_used_and_checked_even_if_not_required(
    credentials: pathlib.Path,
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
) -> None:
    kept = configuration.load_configuration(write_config(config_data), password_required=False)
    assert kept.mail.sender_password == "test-password"

    (credentials / "smtp-password").write_text(SECRET)
    from_credential = configuration.load_configuration(
        write_config(config_data), password_required=False
    )
    assert from_credential.mail.sender_password == SECRET

    (credentials / "smtp-password").write_text("")
    with pytest.raises(configuration.ConfigurationError, match="is empty"):
        configuration.load_configuration(write_config(config_data), password_required=False)

    (credentials / "smtp-password").unlink()
    config_data["mail"]["senderPassword"] = ""
    with pytest.raises(configuration.ConfigurationError, match="expected a non-empty text"):
        configuration.load_configuration(write_config(config_data), password_required=False)


def test_other_problems_are_reported_if_the_password_is_not_required(
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
) -> None:
    del config_data["mail"]["senderPassword"]
    del config_data["mail"]["smtpServer"]

    with pytest.raises(configuration.ConfigurationError) as err:
        configuration.load_configuration(write_config(config_data), password_required=False)

    assert err.value.problems == ["no config parameter: 'mail.smtpServer'"]


@pytest.mark.parametrize("content", [b"", b"\n", b"\r\n", b"  \n"])
@pytest.mark.parametrize("with_key", [True, False])
def test_empty_credential_is_a_problem(
    credentials: pathlib.Path,
    content: bytes,
    with_key: bool,
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
    caplog: pytest.LogCaptureFixture,
) -> None:
    if not with_key:
        del config_data["mail"]["senderPassword"]
    (credentials / "smtp-password").write_bytes(content)

    # not a silent fallback to the key: the credential is there, so it is meant
    assert problems(config_data, write_config) == [
        f"the credential {credentials / 'smtp-password'} is empty"
    ]
    # the key is known: it is not reported as an unknown parameter as well
    assert caplog.records == []


def test_unreadable_credential_is_a_problem(
    credentials: pathlib.Path,
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
) -> None:
    (credentials / "smtp-password").mkdir()

    [problem] = problems(config_data, write_config)

    assert problem.startswith(f"cannot read the credential {credentials / 'smtp-password'}: ")


def test_credential_that_is_no_text_is_a_problem_without_its_content(
    credentials: pathlib.Path,
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
) -> None:
    (credentials / "smtp-password").write_bytes(b"\xff\xfe secret")

    assert problems(config_data, write_config) == [
        f"the credential {credentials / 'smtp-password'} is not valid UTF-8"
    ]


def test_problem_with_the_credential_leaves_no_mail_section_for_the_error_mail(
    credentials: pathlib.Path,
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
) -> None:
    (credentials / "smtp-password").write_text("")
    config_data["softWaterSystem"] = {}

    with pytest.raises(configuration.ConfigurationError) as err:
        configuration.load_configuration(write_config(config_data))

    # the password is missing, so no mail can be sent; the other problems are listed as well
    assert err.value.mail is None
    assert len(err.value.problems) == 2


def test_credential_is_not_in_the_repr_or_in_a_problem(
    credentials: pathlib.Path,
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
) -> None:
    (credentials / "smtp-password").write_text(SECRET)
    loaded = configuration.load_configuration(write_config(config_data))
    config_data["softWaterSystem"] = {}

    assert SECRET not in repr(loaded)
    assert SECRET not in "; ".join(problems(config_data, write_config))


# --- the default of --config-file ---------------------------------------------------


def test_default_config_file_without_the_variable() -> None:
    assert configuration.default_config_file() == "./src/config.json"


def test_default_config_file_is_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRUENBECK_CONFIG", "/etc/gruenbeck/config.json")

    assert configuration.default_config_file() == "/etc/gruenbeck/config.json"


def test_empty_variable_means_the_default_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRUENBECK_CONFIG", "")

    assert configuration.default_config_file() == "./src/config.json"


@pytest.mark.parametrize(
    ("variable", "argv", "expected"),
    [
        (None, [], "./src/config.json"),
        ("", [], "./src/config.json"),
        ("/etc/gruenbeck/config.json", [], "/etc/gruenbeck/config.json"),
        # the option wins over the variable
        ("/etc/gruenbeck/config.json", ["-c", "other.json"], "other.json"),
        ("/etc/gruenbeck/config.json", ["--config-file", "other.json"], "other.json"),
    ],
)
def test_option_uses_the_variable_as_its_default(
    monkeypatch: pytest.MonkeyPatch, variable: str | None, argv: list[str], expected: str
) -> None:
    if variable is not None:
        monkeypatch.setenv("GRUENBECK_CONFIG", variable)
    parser = argparse.ArgumentParser()
    configuration.add_config_file_option(parser)

    assert parser.parse_args(argv).config_file == expected


def test_password_is_not_in_the_repr(loaded_config: gruenbeck.config.Configuration) -> None:
    assert "test-password" not in repr(loaded_config)


def test_unknown_keys_are_ignored_with_a_warning(
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
    caplog: pytest.LogCaptureFixture,
) -> None:
    config_data["comment"] = "my soft water system"
    config_data["mail"]["smtpSecurty"] = "ssl"

    loaded = configuration.load_configuration(write_config(config_data))

    assert loaded.mail.smtp_security is None
    assert [(r.levelno, r.getMessage()) for r in caplog.records] == [
        (logging.WARNING, "unknown config parameter 'mail.smtpSecurty' is ignored"),
        (logging.WARNING, "unknown config parameter 'comment' is ignored"),
    ]


def test_former_parameter_file_key_is_ignored_with_a_warning(
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
    caplog: pytest.LogCaptureFixture,
) -> None:
    # configurations from before P009-S7 still have it; the file does not even have to exist
    config_data["parameterFile"] = "../assets/missing.csv"

    loaded = configuration.load_configuration(write_config(config_data))

    assert loaded.data_path == pathlib.Path(config_data["dataPath"])
    assert [(r.levelno, r.getMessage()) for r in caplog.records] == [
        (logging.WARNING, "unknown config parameter 'parameterFile' is ignored")
    ]


# --- invalid configurations ---------------------------------------------------------


def problems(
    config_data: dict[str, typing.Any], write_config: collections.abc.Callable[..., pathlib.Path]
) -> list[str]:
    """problems of config_data; the configuration must be invalid"""
    with pytest.raises(configuration.ConfigurationError) as err:
        configuration.load_configuration(write_config(config_data))
    assert str(err.value) == "; ".join(err.value.problems)
    return err.value.problems


def test_missing_file_raises_file_not_found_error(tmp_path: pathlib.Path) -> None:
    with pytest.raises(FileNotFoundError):
        configuration.load_configuration(tmp_path / "missing.json")


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("{not json", "is not valid JSON: Expecting property name enclosed in double quotes"),
        ("", "is not valid JSON: Expecting value: line 1 column 1 (char 0)"),
        ("[]", "must contain a JSON object"),
        ('"config"', "must contain a JSON object"),
    ],
)
def test_file_has_to_be_a_json_object(tmp_path: pathlib.Path, text: str, problem: str) -> None:
    path = tmp_path / "config.json"
    path.write_text(text)

    with pytest.raises(configuration.ConfigurationError) as err:
        configuration.load_configuration(path)

    assert str(err.value).startswith(f"configuration file {path} {problem}")
    assert err.value.mail is None


@pytest.mark.parametrize(
    "key",
    [
        "dataPath",
        "dataFile",
        "dataFile.datePattern",
        "dataFile.fieldnames",
        "dataFile.fieldnames.date",
        "dataFile.fieldnames.value",
        "dataFile.prefix",
        "mail",
        "mail.smtpServer",
        "mail.smtpPort",
        "mail.senderEmail",
        "mail.recipients",
        "mail.subject",
        "softWaterSystem",
        "softWaterSystem.host",
    ],
)
def test_missing_required_key_is_a_problem(
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
    key: str,
) -> None:
    *sections, name = key.split(".")
    part = config_data
    for section in sections:
        part = part[section]
    del part[name]

    assert problems(config_data, write_config) == [f"no config parameter: {key!r}"]


def test_the_example_of_the_date_pattern_problem_is_a_valid_pattern(
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
) -> None:
    config_data["dataFile"]["datePattern"] = "%m-%d"
    (problem,) = problems(config_data, write_config)
    example = problem.rsplit("e.g. ", 1)[1].strip("'")

    config_data["dataFile"]["datePattern"] = example
    loaded = configuration.load_configuration(write_config(config_data))

    assert loaded.data_file.date_pattern == example == "%Y-%m-%d"


@pytest.mark.parametrize(
    ("key", "value", "reason"),
    [
        ("dataPath", "", "expected a non-empty text"),
        ("dataPath", 5, "expected a non-empty text"),
        ("dataFile", "data", "expected an object"),
        ("dataFile.datePattern", "", "expected a non-empty text"),
        ("dataFile.datePattern", "%m-%d", "expected a date format with year, month and day"),
        ("dataFile.datePattern", "%d.%m.%y.%Q", "expected a date format with year, month and day"),
        ("dataFile.datePattern", "date", "expected a date format with year, month and day"),
        ("dataFile.fieldnames", ["date", "value"], "expected an object"),
        ("dataFile.fieldnames.date", "", "expected a non-empty text"),
        ("dataFile.fieldnames.value", "date", "must differ from the date column"),
        ("dataFile.prefix", "", "expected a non-empty text"),
        ("dataFile.prefix", "data/gruenbeck", "must not contain a path separator"),
        ("mail", [], "expected an object"),
        ("mail.smtpServer", " ", "expected a non-empty text"),
        ("mail.smtpPort", "smtp", "expected a port number 1 ... 65535"),
        ("mail.smtpPort", 0, "expected a port number 1 ... 65535"),
        ("mail.smtpPort", 65536, "expected a port number 1 ... 65535"),
        ("mail.smtpPort", 587.0, "expected a port number 1 ... 65535"),
        ("mail.smtpPort", True, "expected a port number 1 ... 65535"),
        ("mail.smtpPort", None, "expected a port number 1 ... 65535"),
        ("mail.smtpSecurity", "tls", "expected 'ssl' or 'starttls'"),
        ("mail.smtpSecurity", 465, "expected 'ssl' or 'starttls'"),
        ("mail.senderEmail", 5, "expected a non-empty text"),
        ("mail.senderPassword", "", "expected a non-empty text"),
        ("mail.recipients", [], "expected a non-empty list of mail addresses"),
        ("mail.recipients", "receiver@example.com", "expected a non-empty list of mail addresses"),
        (
            "mail.recipients",
            ["receiver@example.com", ""],
            "expected a non-empty list of mail addresses",
        ),
        ("mail.subject", None, "expected a text"),
        ("softWaterSystem", "device.lan", "expected an object"),
        ("softWaterSystem.host", "", "expected a non-empty text"),
        ("softWaterSystem.timeout", 0, "must be a number greater than 0"),
        ("softWaterSystem.timeout", -1, "must be a number greater than 0"),
        ("softWaterSystem.timeout", "nan", "must be a number greater than 0"),
        ("softWaterSystem.timeout", "inf", "must be a number greater than 0"),
        ("softWaterSystem.timeout", True, "expected a number"),
        ("softWaterSystem.retries", -1, "must be a whole number, 0 or greater"),
        ("softWaterSystem.retries", 2.5, "must be a whole number, 0 or greater"),
        ("softWaterSystem.retries", 3.0, "must be a whole number, 0 or greater"),
        ("softWaterSystem.retries", "3", "must be a whole number, 0 or greater"),
        ("softWaterSystem.retries", True, "must be a whole number, 0 or greater"),
        ("softWaterSystem.retries", None, "must be a whole number, 0 or greater"),
        ("softWaterSystem.retryDelay", -1, "must be a number, 0 or greater"),
        ("softWaterSystem.retryDelay", "5", "must be a number, 0 or greater"),
        ("softWaterSystem.retryDelay", True, "must be a number, 0 or greater"),
        ("softWaterSystem.retryDelay", None, "must be a number, 0 or greater"),
        # json writes and reads float("inf") as Infinity
        ("softWaterSystem.retryDelay", math.inf, "must be a number, 0 or greater"),
        ("mail.retries", -1, "must be a whole number, 0 or greater"),
        ("mail.retries", "3", "must be a whole number, 0 or greater"),
        ("mail.retryDelay", -0.5, "must be a number, 0 or greater"),
        ("mail.retryDelay", [5], "must be a number, 0 or greater"),
        ("softWaterSystem.timeout", "abc", "could not convert string to float: 'abc'"),
        (
            "softWaterSystem.timeout",
            None,
            "float() argument must be a string or a real number, not 'NoneType'",
        ),
        (
            "softWaterSystem.timeout",
            [5],
            "float() argument must be a string or a real number, not 'list'",
        ),
    ],
    ids=repr,
)
def test_invalid_value_is_a_problem(
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
    key: str,
    value: typing.Any,
    reason: str,
) -> None:
    *sections, name = key.split(".")
    part = config_data
    for section in sections:
        part = part[section]
    part[name] = value

    found = problems(config_data, write_config)

    assert len(found) == 1
    assert found[0].startswith(f"invalid config parameter {key} {value!r}: {reason}")


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("20.11.2026", "expected a date YYYY-MM-DD"),
        # the text of the ValueError differs between Python versions
        ("2026-11-31", "day "),
        ("2026-1-5", "expected a date YYYY-MM-DD"),
        ("20261120", "expected a date YYYY-MM-DD"),
        ("2026-11-20T00:00", "expected a date YYYY-MM-DD"),
        ("", "expected a date YYYY-MM-DD"),
        (20261120, "expected a date YYYY-MM-DD"),
        (None, "expected a date YYYY-MM-DD"),
    ],
    ids=repr,
)
def test_invalid_first_date_is_a_problem(
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
    value: int | str | None,
    reason: str,
) -> None:
    # the values of the former tests of get_first_date() (P004-S3, P006-S1)
    config_data["dataFile"]["firstDate"] = value

    (found,) = problems(config_data, write_config)
    assert found.startswith(f"invalid config parameter dataFile.firstDate {value!r}: {reason}")


def test_every_problem_is_reported(
    config_data: dict[str, typing.Any], write_config: collections.abc.Callable[..., pathlib.Path]
) -> None:
    del config_data["dataPath"]
    config_data["mail"]["recipients"] = []
    config_data["dataFile"]["fieldnames"] = {"date": "day"}
    config_data["softWaterSystem"]["timeout"] = -1

    assert problems(config_data, write_config) == [
        "invalid config parameter mail.recipients []: expected a non-empty list of mail addresses",
        "invalid config parameter softWaterSystem.timeout -1: must be a number greater than 0",
        "no config parameter: 'dataFile.fieldnames.value'",
        "no config parameter: 'dataPath'",
    ]


def test_error_has_the_mail_section_if_it_is_valid(
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
    loaded_config: gruenbeck.config.Configuration,
) -> None:
    invalid = copy.deepcopy(config_data)
    del invalid["dataPath"]

    with pytest.raises(configuration.ConfigurationError) as err:
        configuration.load_configuration(write_config(invalid))

    assert err.value.mail == loaded_config.mail


def test_error_has_no_mail_section_if_it_is_invalid(
    config_data: dict[str, typing.Any], write_config: collections.abc.Callable[..., pathlib.Path]
) -> None:
    del config_data["dataPath"]
    del config_data["mail"]["subject"]

    with pytest.raises(configuration.ConfigurationError) as err:
        configuration.load_configuration(write_config(config_data))

    assert err.value.mail is None
    assert err.value.problems == [
        "no config parameter: 'mail.subject'",
        "no config parameter: 'dataPath'",
    ]


# --- paths --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data_path", "expected"),
    [("data", "repo/src/data"), ("./data", "repo/src/data"), ("../data", "repo/data")],
)
def test_relative_paths_start_at_the_folder_of_the_configuration(
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    data_path: str,
    expected: str,
) -> None:
    config_data["dataPath"] = data_path
    path = write_config(config_data, tmp_path / "repo" / "src" / "config.json")
    monkeypatch.chdir(tmp_path)

    # also with a relative path of the configuration file
    loaded = configuration.load_configuration("repo/src/config.json")

    assert loaded.file == path
    assert loaded.data_path == tmp_path / expected


def test_absolute_paths_stay(
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
    tmp_path: pathlib.Path,
) -> None:
    config_data["dataPath"] = "/srv/gruenbeck/data"

    loaded = configuration.load_configuration(write_config(config_data, tmp_path / "c.json"))

    assert loaded.data_path == pathlib.Path("/srv/gruenbeck/data")


def test_a_folder_of_the_working_directory_is_not_used(
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # only repo/data exists, the folder of the configuration file has no data folder (yet)
    (tmp_path / "repo" / "data").mkdir(parents=True)
    config_data["dataPath"] = "./data"
    write_config(config_data, tmp_path / "repo" / "src" / "config.json")
    monkeypatch.chdir(tmp_path / "repo")

    loaded = configuration.load_configuration("src/config.json")

    assert loaded.data_path == tmp_path / "repo" / "src" / "data"


# --- the file without checks --------------------------------------------------------


def test_read_configuration_file_returns_the_json_object(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"softWaterSystem": {"host": "device.lan"}}))

    assert configuration.read_configuration_file(path) == {
        "softWaterSystem": {"host": "device.lan"}
    }


# --- only the section softWaterSystem -----------------------------------------------


def test_load_soft_water_system_ignores_the_other_sections(
    write_config: collections.abc.Callable[..., pathlib.Path], caplog: pytest.LogCaptureFixture
) -> None:
    path = write_config(
        {"softWaterSystem": {"host": "device.lan", "timeout": 7}, "mail": 5, "comment": "x"}
    )

    assert configuration.load_soft_water_system(path) == configuration.SoftWaterSystem(
        host="device.lan",
        timeout=7.0,
        retries=configuration.DEVICE_RETRIES,
        retry_delay=float(configuration.DEVICE_RETRY_DELAY),
    )
    # neither the invalid section mail nor the unknown key at the top is reported
    assert caplog.records == []


def test_load_soft_water_system_warns_about_unknown_keys_of_the_section(
    write_config: collections.abc.Callable[..., pathlib.Path], caplog: pytest.LogCaptureFixture
) -> None:
    path = write_config({"softWaterSystem": {"host": "device.lan", "hots": "x"}})

    assert configuration.load_soft_water_system(path).host == "device.lan"
    assert [(r.levelno, r.getMessage()) for r in caplog.records] == [
        (logging.WARNING, "unknown config parameter 'softWaterSystem.hots' is ignored")
    ]


@pytest.mark.parametrize(
    "section",
    [
        None,
        "device.lan",
        ["device.lan"],
        {},
        {"host": ["a"]},
        {"host": " "},
        {"host": "", "timeout": 0, "retries": -1, "retryDelay": "5"},
        {"host": "device.lan", "timeout": "x"},
    ],
    ids=repr,
)
def test_load_soft_water_system_has_the_problems_of_load_configuration(
    config_data: dict[str, typing.Any],
    write_config: collections.abc.Callable[..., pathlib.Path],
    section: typing.Any,
) -> None:
    if section is None:
        del config_data["softWaterSystem"]
    else:
        config_data["softWaterSystem"] = section
    expected = problems(config_data, write_config)

    with pytest.raises(configuration.ConfigurationError) as err:
        configuration.load_soft_water_system(write_config(config_data))

    assert err.value.problems == expected
    assert err.value.mail is None


def test_load_soft_water_system_lists_every_problem_of_the_section(
    write_config: collections.abc.Callable[..., pathlib.Path],
) -> None:
    path = write_config({"softWaterSystem": {"timeout": 0, "retries": True}})

    with pytest.raises(configuration.ConfigurationError) as err:
        configuration.load_soft_water_system(path)

    assert err.value.problems == [
        "no config parameter: 'softWaterSystem.host'",
        "invalid config parameter softWaterSystem.timeout 0: must be a number greater than 0",
        "invalid config parameter softWaterSystem.retries True: must be a whole number, 0 or"
        " greater",
    ]


def test_load_soft_water_system_without_file_raises_file_not_found_error(
    tmp_path: pathlib.Path,
) -> None:
    with pytest.raises(FileNotFoundError):
        configuration.load_soft_water_system(tmp_path / "missing.json")
