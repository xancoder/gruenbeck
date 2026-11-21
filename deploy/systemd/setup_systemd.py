#!/usr/bin/env python3
"""
Generate the systemd units of the Gruenbeck data collector from the templates
next to this script and print the commands to install them as system service.

The generated files are never written into the repository.
"""

import argparse
import getpass
import pathlib
import re
import shlex
import sys
import tempfile

TEMPLATE_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = TEMPLATE_DIR.parents[1]
SERVICE_TEMPLATE = "gruenbeck-collector.service.template"
SERVICE_NAME = "gruenbeck-collector.service"
TIMER_NAME = "gruenbeck-collector.timer"
SYSTEMD_DIR = "/etc/systemd/system/"

# whitespace splits ExecStart, '%' starts a systemd specifier
INVALID_VALUE = re.compile(r"[\s%]")


def generate_units(user, install_path, output_dir=None):
    """
    Create service and timer unit in output_dir (a new temporary directory if None)
    :param user: user the service runs as
    :param install_path: path of the repository on the target machine
    :param output_dir: directory for the generated files, must be outside of the repository
    :return: pathlib.Path of the directory with the generated files
    :raises ValueError: invalid user, install path or output directory
    """
    for name, value in (("user", user), ("install path", str(install_path))):
        if not value or INVALID_VALUE.search(value):
            raise ValueError(
                f"Invalid {name} {value!r}: must not be empty or contain whitespace or '%'"
            )
    install_path = pathlib.Path(install_path).absolute()

    if output_dir is None:
        output_dir = pathlib.Path(tempfile.mkdtemp(prefix="gruenbeck-systemd-"))
    else:
        output_dir = pathlib.Path(output_dir).expanduser().absolute()
        if output_dir == REPO_ROOT or REPO_ROOT in output_dir.parents:
            raise ValueError(f"Output directory {output_dir} is inside the repository {REPO_ROOT}")
        output_dir.mkdir(parents=True, exist_ok=True)

    template = (TEMPLATE_DIR / SERVICE_TEMPLATE).read_text(encoding="utf-8")
    service = template.replace("{{USER}}", user).replace("{{INSTALL_PATH}}", str(install_path))
    if "{{" in service:
        raise ValueError(f"Unreplaced placeholder in {SERVICE_TEMPLATE}")

    (output_dir / SERVICE_NAME).write_text(service, encoding="utf-8")
    timer = (TEMPLATE_DIR / TIMER_NAME).read_text(encoding="utf-8")
    (output_dir / TIMER_NAME).write_text(timer, encoding="utf-8")
    return output_dir


def install_commands(output_dir):
    """
    :return: list of shell commands to install the units as system service
    """
    files = " ".join(shlex.quote(str(output_dir / name)) for name in (SERVICE_NAME, TIMER_NAME))
    return [
        f"sudo install -m 644 -t {SYSTEMD_DIR} {files}",
        "sudo systemctl daemon-reload",
        f"sudo systemctl enable --now {TIMER_NAME}",
    ]


def main(argv=None):
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
        "--output-dir",
        help="directory for the generated units, outside of the repository "
        "(default: a new temporary directory)",
        default=None,
    )
    args = parser.parse_args(argv)

    try:
        output_dir = generate_units(args.user, args.install_path, args.output_dir)
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
