"""
commands of the package: gruenbeck-collect (data collector) and gruenbeck-analyse

Only this module catches the errors of the package (gruenbeck.errors.GruenbeckError and
its subclasses), sends the error mail and sets the exit code; only this module configures
the logging handlers. The run of the data collector is in gruenbeck.collector.
"""

import argparse
import logging.handlers
import os
import sys
import traceback
from collections.abc import Sequence

from gruenbeck import analysis, collector, errors, mail, version
from gruenbeck import config as configuration

# the handlers of setup_logging() sit on the logger of the package, so they also get the
# messages of the other modules (gruenbeck.collector, gruenbeck.config, gruenbeck.device, ...)
package_logger = logging.getLogger("gruenbeck")
logger = logging.getLogger(__name__)

# create logging formatter
formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S"
)

ERROR_MAIL_SUBJECT = "gruenbeck data collector failure"


def setup_logging(
    log_console: bool = False, log_file: str | os.PathLike[str] = "./log/gruenbeck_error.log"
) -> list[logging.Handler]:
    """
    attach the handlers to the logger of the package and let it pass INFO and above

    The rotating file takes warnings as well as errors: scheduled runs (systemd timer,
    cron) have no console, so a warning would be lost otherwise.
    :param log_console: also log INFO and above to the console (stderr)
    :param log_file: path of the rotating log file
    :return: list of the added handlers
    :raises OSError: the log file cannot be opened (e.g. its folder is missing)
    """
    handlers: list[logging.Handler] = []
    log_rotate_file = logging.handlers.RotatingFileHandler(
        f"{log_file}", maxBytes=8000000, backupCount=5
    )
    log_rotate_file.setLevel(logging.WARNING)
    handlers.append(log_rotate_file)
    if log_console:
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        handlers.insert(0, console)
    package_logger.setLevel(logging.INFO)
    for handler in handlers:
        handler.setFormatter(formatter)
        package_logger.addHandler(handler)
    return handlers


def main(config_file: str | os.PathLike[str]) -> int:
    """
    run the data collector once
    :return: exit code, 0 if the data was collected, stored and sent by mail, else 1
    """
    logger.info("run script: %s, version %s", sys.argv[0], version.get_version())

    try:
        config = configuration.load_configuration(config_file)
    except FileNotFoundError as err:
        # TRY400 here and below: an expected error that its message describes completely; the
        # traceback is logged only for an unexpected exception (see report_error)
        logger.error("no configuration: %s", err)  # noqa: TRY400
        return 1
    except configuration.ConfigurationError as err:
        # an error mail is only possible if the mail section is valid
        report_error(err.mail, str(err))
        return 1

    try:
        result = collector.collect_and_store(config)
    except errors.GruenbeckError as err:
        report_error(config.mail, str(err))
        return 1
    except Exception as err:
        # a failure nobody expected: with traceback in the log and in the error mail
        report_error(
            config.mail,
            f"unexpected error: {type(err).__name__}: {err}\n\n{traceback.format_exc()}",
            exception=err,
        )
        return 1

    # the data is stored at this point; a failed mail still has to be visible
    # as a failed run (exit code 1) for cron and systemd; the statistics are for the day the
    # values were stored under, even if the run went past midnight
    try:
        collector.send_data_mail(config, result.data_path, result.today)
    except errors.GruenbeckError as err:
        # an expected error is described completely by its message (no traceback, TRY400);
        # an unexpected one gets the traceback of its cause in the log (there is no error mail)
        cause = err.__cause__ if isinstance(err, mail.MailError) and err.unexpected else None
        logger.error("mail sending failed: %s", err, exc_info=cause)  # noqa: TRY400
        logger.error("data was collected and stored, but email sending failed")  # noqa: TRY400
        return 1

    logger.info("Data collection completed")
    return 0


def report_error(
    mail_settings: configuration.Mail | None,
    error_text: str,
    exception: BaseException | None = None,
) -> None:
    """
    log the error and send it as error mail
    :param mail_settings: mail section of the configuration, None if it is invalid
    :param exception: an unexpected exception: its traceback goes into the log
    """
    if exception is not None:
        logger.error("%s", error_text.split("\n", 1)[0], exc_info=exception)
    else:
        logger.error("%s", error_text)

    # Try to send an email notification about the error
    if mail_settings is None:
        logger.error("Failed to send error notification email: no valid mail configuration")
        return
    try:
        mail.send_mail(mail_settings, ERROR_MAIL_SUBJECT, error_text)
        logger.info("Error notification email sent")
    except Exception as mail_error:
        logger.error("Failed to send error notification email: %s", mail_error)  # noqa: TRY400


def collect(argv: Sequence[str] | None = None) -> int:
    """
    command gruenbeck-collect: collect, store and mail the data of the soft water system
    :return: exit code (the console script passes it to sys.exit)
    """
    parser = argparse.ArgumentParser(
        prog="gruenbeck-collect",
        description="collect the water consumption of the soft water system, store it and mail it",
    )
    configuration.add_config_file_option(parser)
    version.add_version_option(parser)
    parser.add_argument("--log-console", "-l", help="activate console logging", action="store_true")
    parser.add_argument(
        "--log-error",
        "-e",
        help="log warnings and errors to file",
        required=False,
        default="./log/gruenbeck_error.log",
    )
    args = parser.parse_args(argv)

    try:
        setup_logging(args.log_console, args.log_error)
    except OSError as err:
        # before the configuration is read: no log file and no error mail
        print(f"{parser.prog}: cannot open the log file: {err}", file=sys.stderr)
        return 1

    return main(args.config_file)


def analyse(argv: Sequence[str] | None = None) -> int:
    """
    command gruenbeck-analyse: monthly statistics of the stored data
    :return: exit code (the console script passes it to sys.exit)
    """
    parser = argparse.ArgumentParser(
        prog="gruenbeck-analyse",
        description="monthly statistics of the collected water consumption",
    )
    configuration.add_config_file_option(parser)
    version.add_version_option(parser)
    args = parser.parse_args(argv)

    try:
        analysis.main(args.config_file)
    except FileNotFoundError as err:
        print(f"{parser.prog}: no configuration: {err}", file=sys.stderr)
        return 1
    except errors.GruenbeckError as err:
        print(f"{parser.prog}: {err}", file=sys.stderr)
        return 1
    return 0
