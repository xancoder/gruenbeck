#!/usr/bin/env python3
"""
Generate the systemd units of the Gruenbeck data collector from the templates
next to this script and print the commands to install them as system service.

The service is hardened: it may only write to the data folder and the log folder
(`<install path>/data` and `<install path>/log`, or the folders of --write-path).
With --smtp-password-file the unit passes that file to the collector as the systemd
credential "smtp-password", so the password need not be in the configuration file.
The generated files are never written into the repository.
"""

import argparse
import collections.abc
import getpass
import os
import pathlib
import re
import shlex
import sys
import tempfile

TEMPLATE_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = TEMPLATE_DIR.parents[1]
SERVICE_TEMPLATE = "gruenbeck-collector.service.template"
PASSWORD_CREDENTIAL = "smtp-password"
SERVICE_NAME = "gruenbeck-collector.service"
TIMER_NAME = "gruenbeck-collector.timer"
SYSTEMD_DIR = "/etc/systemd/system/"

# whitespace splits ExecStart and ReadWritePaths, '%' starts a systemd specifier
INVALID_VALUE = re.compile(r"[\s%]")


def default_write_paths(install_path: str | os.PathLike[str]) -> list[pathlib.Path]:
    """the data folder and the log folder next to the repository, where the collector writes"""
    base = pathlib.Path(install_path).absolute()
    return [base / "data", base / "log"]


def generate_units(
    user: str,
    install_path: str | os.PathLike[str],
    output_dir: str | os.PathLike[str] | None = None,
    write_paths: collections.abc.Sequence[str | os.PathLike[str]] | None = None,
    smtp_password_file: str | os.PathLike[str] | None = None,
) -> pathlib.Path:
    """
    Create service and timer unit in output_dir (a new temporary directory if None)
    :param user: user the service runs as
    :param install_path: path of the repository on the target machine
    :param output_dir: directory for the generated files, must be outside of the repository
    :param write_paths: the only folders the service may write to; they replace the default
        (`data` and `log` in install_path), so list every folder the collector writes to
    :param smtp_password_file: file on the target machine with the SMTP password; systemd
        reads it as root and gives it to the service as the credential "smtp-password"
    :return: pathlib.Path of the directory with the generated files
    :raises ValueError: invalid user, install path, write path, password file or output directory
    """
    checked = [("user", user), ("install path", str(install_path))]
    checked += [("write path", str(path)) for path in write_paths or ()]
    if smtp_password_file is not None:
        checked.append(("SMTP password file", str(smtp_password_file)))
    for name, value in checked:
        if not value or INVALID_VALUE.search(value):
            raise ValueError(
                f"Invalid {name} {value!r}: must not be empty or contain whitespace or '%'"
            )
    install_path = pathlib.Path(install_path).absolute()
    # systemd wants absolute, normalized paths
    folders = (
        [pathlib.Path(os.path.normpath(pathlib.Path(path).absolute())) for path in write_paths]
        if write_paths
        else default_write_paths(install_path)
    )

    if output_dir is None:
        output_dir = pathlib.Path(tempfile.mkdtemp(prefix="gruenbeck-systemd-"))
    else:
        output_dir = pathlib.Path(output_dir).expanduser().absolute()
        if output_dir == REPO_ROOT or REPO_ROOT in output_dir.parents:
            raise ValueError(f"Output directory {output_dir} is inside the repository {REPO_ROOT}")
        output_dir.mkdir(parents=True, exist_ok=True)

    template = (TEMPLATE_DIR / SERVICE_TEMPLATE).read_text(encoding="utf-8")
    if smtp_password_file is None:
        credential_line = ""
    else:
        credential = pathlib.Path(os.path.normpath(pathlib.Path(smtp_password_file).absolute()))
        credential_line = f"LoadCredential={PASSWORD_CREDENTIAL}:{credential}\n"
    service = (
        template.replace("{{LOAD_CREDENTIAL}}\n", credential_line)
        .replace("{{USER}}", user)
        .replace("{{INSTALL_PATH}}", str(install_path))
        .replace("{{WRITE_PATHS}}", " ".join(str(folder) for folder in folders))
    )
    if "{{" in service:
        raise ValueError(f"Unreplaced placeholder in {SERVICE_TEMPLATE}")

    (output_dir / SERVICE_NAME).write_text(service, encoding="utf-8")
    timer = (TEMPLATE_DIR / TIMER_NAME).read_text(encoding="utf-8")
    (output_dir / TIMER_NAME).write_text(timer, encoding="utf-8")
    return output_dir


def install_commands(output_dir: pathlib.Path) -> list[str]:
    """
    :return: list of shell commands to install the units as system service
    """
    files = " ".join(shlex.quote(str(output_dir / name)) for name in (SERVICE_NAME, TIMER_NAME))
    return [
        f"sudo install -m 644 -t {SYSTEMD_DIR} {files}",
        "sudo systemctl daemon-reload",
        f"sudo systemctl enable --now {TIMER_NAME}",
    ]


def main(argv: collections.abc.Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate systemd units for the Gruenbeck data collector"
    )
    parser.add_argument(
        "--user",
        help="user to run the service as (default: current user)",
        default=getpass.getuser(),
    )
    parser.add_argument(
        "--install-path",
        help="path of the repository on the target machine (default: this repository)",
        default=str(REPO_ROOT),
    )
    parser.add_argument(
        "--write-path",
        action="append",
        metavar="PATH",
        help="folder the service may write to; repeat it for several folders. They replace the"
        " default (data and log in the install path), so list the folder of dataPath and the"
        " folder of the log file (--log-error) if they are somewhere else",
        default=None,
    )
    parser.add_argument(
        "--smtp-password-file",
        metavar="PATH",
        help="file on the target machine with the SMTP password (owned by root, mode 600): the"
        " unit passes it to the collector as the credential 'smtp-password', so mail.senderPassword"
        " can be removed from the configuration file (default: no credential)",
        default=None,
    )
    parser.add_argument(
        "--output-dir",
        help="directory for the generated units, outside of the repository "
        "(default: a new temporary directory)",
        default=None,
    )
    args = parser.parse_args(argv)

    try:
        output_dir = generate_units(
            args.user,
            args.install_path,
            args.output_dir,
            args.write_path,
            args.smtp_password_file,
        )
    except ValueError as err:
        parser.error(str(err))
    except OSError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1

    print(f"Units generated in {output_dir}")
    print("\nInstall them as system service and start the timer:")
    for command in install_commands(output_dir):
        print(f"  {command}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
