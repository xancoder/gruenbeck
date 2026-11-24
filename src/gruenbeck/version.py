"""version of the installed package, for --version and the log of a run"""

import argparse
import importlib.metadata

PACKAGE = "gruenbeck"


def get_version() -> str:
    """version of the installed package (pyproject.toml), "unknown" if it is not installed"""
    try:
        return importlib.metadata.version(PACKAGE)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def add_version_option(parser: argparse.ArgumentParser) -> None:
    """add --version to a command: it prints "<command> <version>" and exits with 0"""
    parser.add_argument("--version", action="version", version=f"%(prog)s {get_version()}")
