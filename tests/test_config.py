"""configuration file: loading, checking and the paths (P006-S3)"""

import copy
import datetime
import json
import logging
import pathlib

import pytest

from gruenbeck import config as configuration

# --- valid configurations -----------------------------------------------------------


def test_example_configuration_is_valid(config_example_file, repo_root, caplog):
    loaded = configuration.load_configuration(config_example_file)

    assert loaded.file == config_example_file
    # relative paths start at src/, the folder of the configuration file
    assert loaded.data_path == repo_root / "data"
    assert loaded.parameter_file == repo_root / "assets" / "Gruenbeck_Webserver_Dokumentation.csv"
    assert loaded.parameter_file.exists()
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


def test_values_are_typed(config_data, write_config, tmp_path, parameter_file):
    config_data["mail"].update(
        smtpPort=" 465 ", smtpSecurity=" SSL ", subject="", retries=2, retryDelay=1.5
    )
    config_data["softWaterSystem"].update(timeout="2.5", retries=0, retryDelay=0.5)
    config_data["dataFile"]["firstDate"] = "2026-11-20"

    loaded = configuration.load_configuration(write_config(config_data))

    assert loaded == configuration.Configuration(
        file=tmp_path / "config.json",
        data_path=tmp_path / "data",
        parameter_file=parameter_file,
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


def test_optional_keys_have_defaults(loaded_config):
    assert loaded_config.data_file.first_date is None
    assert loaded_config.mail.smtp_security is None
    assert loaded_config.soft_water_system.timeout == 30.0
    assert type(loaded_config.soft_water_system.timeout) is float


def test_retry_defaults(loaded_config):
    # the device is asked again for about 2.5 minutes, the mail for about 15 seconds
    water, mail = loaded_config.soft_water_system, loaded_config.mail
    assert (water.retries, water.retry_delay) == (5, 5.0)
    assert (mail.retries, mail.retry_delay) == (3, 5.0)
    assert type(water.retry_delay) is float
    assert type(mail.retry_delay) is float


@pytest.mark.parametrize("section", ["softWaterSystem", "mail"])
@pytest.mark.parametrize(
    "key, value, expected",
    [
        ("retries", 0, 0),
        ("retries", 1, 1),
        ("retries", 10, 10),
        ("retryDelay", 0, 0.0),
        ("retryDelay", 0.5, 0.5),
        ("retryDelay", 30, 30.0),
    ],
)
def test_retries_and_retry_delay(config_data, write_config, caplog, section, key, value, expected):
    config_data[section][key] = value

    loaded = configuration.load_configuration(write_config(config_data))

    part = loaded.soft_water_system if section == "softWaterSystem" else loaded.mail
    result = part.retries if key == "retries" else part.retry_delay
    assert result == expected
    assert type(result) is type(expected)
    # known keys: no warning about an unknown parameter
    assert caplog.records == []


def test_retries_of_the_sections_are_independent(config_data, write_config):
    config_data["softWaterSystem"].update(retries=1, retryDelay=2)

    loaded = configuration.load_configuration(write_config(config_data))

    assert (loaded.soft_water_system.retries, loaded.soft_water_system.retry_delay) == (1, 2.0)
    assert (loaded.mail.retries, loaded.mail.retry_delay) == (3, 5.0)


@pytest.mark.parametrize(
    "key, value, expected",
    [
        ("timeout", 5, 5.0),
        ("timeout", 0.1, 0.1),
        ("timeout", "2.5", 2.5),
    ],
)
def test_device_timeout(config_data, write_config, key, value, expected):
    config_data["softWaterSystem"][key] = value

    loaded = configuration.load_configuration(write_config(config_data))

    assert loaded.soft_water_system.timeout == expected


@pytest.mark.parametrize("pattern", ["%Y-%m-%d", "%d.%m.%Y", "%Y%m%d", "%d/%m/%Y", "%Y-%j"])
def test_date_patterns_with_year_month_and_day(config_data, write_config, pattern):
    config_data["dataFile"]["datePattern"] = pattern

    loaded = configuration.load_configuration(write_config(config_data))

    assert loaded.data_file.date_pattern == pattern


def test_smtp_security_null_is_derived_from_the_port(config_data, write_config):
    config_data["mail"]["smtpSecurity"] = None

    loaded = configuration.load_configuration(write_config(config_data))

    assert loaded.mail.smtp_security is None


def test_mail_port_and_security_are_normalized(config_data, write_config):
    config_data["mail"].update(smtpPort="465", smtpSecurity=" SSL ")

    loaded = configuration.load_configuration(write_config(config_data))

    assert (loaded.mail.smtp_port, loaded.mail.smtp_security) == (465, "ssl")


def test_password_is_not_in_the_repr(loaded_config):
    assert "test-password" not in repr(loaded_config)


def test_unknown_keys_are_ignored_with_a_warning(config_data, write_config, caplog):
    config_data["comment"] = "my soft water system"
    config_data["mail"]["smtpSecurty"] = "ssl"

    loaded = configuration.load_configuration(write_config(config_data))

    assert loaded.mail.smtp_security is None
    assert [(r.levelno, r.getMessage()) for r in caplog.records] == [
        (logging.WARNING, "unknown config parameter 'mail.smtpSecurty' is ignored"),
        (logging.WARNING, "unknown config parameter 'comment' is ignored"),
    ]


# --- invalid configurations ---------------------------------------------------------


def problems(config_data, write_config):
    """problems of config_data; the configuration must be invalid"""
    with pytest.raises(configuration.ConfigurationError) as err:
        configuration.load_configuration(write_config(config_data))
    assert str(err.value) == "; ".join(err.value.problems)
    return err.value.problems


def test_missing_file_raises_file_not_found_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        configuration.load_configuration(tmp_path / "missing.json")


@pytest.mark.parametrize(
    "text, problem",
    [
        ("{not json", "is not valid JSON: Expecting property name enclosed in double quotes"),
        ("", "is not valid JSON: Expecting value: line 1 column 1 (char 0)"),
        ("[]", "must contain a JSON object"),
        ('"config"', "must contain a JSON object"),
    ],
)
def test_file_has_to_be_a_json_object(tmp_path, text, problem):
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
        "parameterFile",
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
        "mail.senderPassword",
        "mail.recipients",
        "mail.subject",
        "softWaterSystem",
        "softWaterSystem.host",
    ],
)
def test_missing_required_key_is_a_problem(config_data, write_config, key):
    *sections, name = key.split(".")
    part = config_data
    for section in sections:
        part = part[section]
    del part[name]

    assert problems(config_data, write_config) == [f"no config parameter: {key!r}"]


@pytest.mark.parametrize(
    "key, value, reason",
    [
        ("dataPath", "", "expected a non-empty text"),
        ("dataPath", 5, "expected a non-empty text"),
        ("parameterFile", None, "expected a non-empty text"),
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
def test_invalid_value_is_a_problem(config_data, write_config, key, value, reason):
    *sections, name = key.split(".")
    part = config_data
    for section in sections:
        part = part[section]
    part[name] = value

    found = problems(config_data, write_config)

    assert len(found) == 1
    assert found[0].startswith(f"invalid config parameter {key} {value!r}: {reason}")


@pytest.mark.parametrize(
    "value, reason",
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
def test_invalid_first_date_is_a_problem(config_data, write_config, value, reason):
    # the values of the former tests of get_first_date() (P004-S3, P006-S1)
    config_data["dataFile"]["firstDate"] = value

    (found,) = problems(config_data, write_config)
    assert found.startswith(f"invalid config parameter dataFile.firstDate {value!r}: {reason}")


def test_every_problem_is_reported(config_data, write_config):
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


def test_error_has_the_mail_section_if_it_is_valid(config_data, write_config, loaded_config):
    invalid = copy.deepcopy(config_data)
    del invalid["parameterFile"]

    with pytest.raises(configuration.ConfigurationError) as err:
        configuration.load_configuration(write_config(invalid))

    assert err.value.mail == loaded_config.mail


def test_error_has_no_mail_section_if_it_is_invalid(config_data, write_config):
    del config_data["parameterFile"]
    del config_data["mail"]["subject"]

    with pytest.raises(configuration.ConfigurationError) as err:
        configuration.load_configuration(write_config(config_data))

    assert err.value.mail is None
    assert err.value.problems == [
        "no config parameter: 'mail.subject'",
        "no config parameter: 'parameterFile'",
    ]


# --- paths --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "data_path, expected",
    [("data", "repo/src/data"), ("./data", "repo/src/data"), ("../data", "repo/data")],
)
def test_relative_paths_start_at_the_folder_of_the_configuration(
    config_data, write_config, tmp_path, monkeypatch, data_path, expected
):
    (tmp_path / "repo" / "assets").mkdir(parents=True)
    (tmp_path / "repo" / "assets" / "parameters.csv").write_text("")
    config_data.update(dataPath=data_path, parameterFile="../assets/parameters.csv")
    path = write_config(config_data, tmp_path / "repo" / "src" / "config.json")
    monkeypatch.chdir(tmp_path)

    # also with a relative path of the configuration file
    loaded = configuration.load_configuration("repo/src/config.json")

    assert loaded.file == path
    assert loaded.data_path == tmp_path / expected
    assert loaded.parameter_file == tmp_path / "repo" / "assets" / "parameters.csv"


def test_absolute_paths_stay(config_data, write_config, tmp_path):
    config_data.update(dataPath="/srv/gruenbeck/data", parameterFile="/srv/gruenbeck/p.csv")

    loaded = configuration.load_configuration(write_config(config_data, tmp_path / "c.json"))

    assert loaded.data_path == pathlib.Path("/srv/gruenbeck/data")
    assert loaded.parameter_file == pathlib.Path("/srv/gruenbeck/p.csv")


def test_path_written_for_the_working_directory_is_an_error(
    config_data, write_config, tmp_path, monkeypatch
):
    # the configuration of P006-S2 and earlier: src/config.json, run from the repository
    (tmp_path / "repo" / "data").mkdir(parents=True)
    config_data["dataPath"] = "./data"
    write_config(config_data, tmp_path / "repo" / "src" / "config.json")
    monkeypatch.chdir(tmp_path / "repo")

    found = problems_of("src/config.json")

    src = tmp_path / "repo" / "src"
    assert found == [
        f"invalid config parameter dataPath './data': relative paths start at the folder of"
        f" the configuration file ({src}), not at the working directory: {src / 'data'} does"
        f" not exist, but {tmp_path / 'repo' / 'data'} does; use '../data'"
    ]


def test_path_that_exists_from_both_folders_is_taken_from_the_configuration(
    config_data, write_config, tmp_path, monkeypatch
):
    (tmp_path / "repo" / "data").mkdir(parents=True)
    (tmp_path / "repo" / "src" / "data").mkdir(parents=True)
    config_data["dataPath"] = "./data"
    write_config(config_data, tmp_path / "repo" / "src" / "config.json")
    monkeypatch.chdir(tmp_path / "repo")

    loaded = configuration.load_configuration("src/config.json")

    assert loaded.data_path == tmp_path / "repo" / "src" / "data"


def test_path_that_exists_nowhere_is_taken_from_the_configuration(
    config_data, write_config, tmp_path, monkeypatch
):
    # the first run: the data folder is created later
    config_data["dataPath"] = "data"
    write_config(config_data, tmp_path / "repo" / "src" / "config.json")
    monkeypatch.chdir(tmp_path / "repo")

    loaded = configuration.load_configuration("src/config.json")

    assert loaded.data_path == tmp_path / "repo" / "src" / "data"


def problems_of(path):
    with pytest.raises(configuration.ConfigurationError) as err:
        configuration.load_configuration(path)
    return err.value.problems


# --- the file without checks --------------------------------------------------------


def test_read_configuration_file_returns_the_json_object(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"softWaterSystem": {"host": "device.lan"}}))

    assert configuration.read_configuration_file(path) == {
        "softWaterSystem": {"host": "device.lan"}
    }
