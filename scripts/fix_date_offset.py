#!/usr/bin/env python3
"""
One-time migration: move every stored consumption value one day back.

Up to now the data collector stored the value of D_Y_2_n ("n days ago") under
today - (n - 1) days, so every value in the data files is one day late. This script moves
each value of the yearly files <prefix>_<year>.csv from date d to d - 1 (the value of
1 January moves into the file of the previous year, which is created if needed) and fills
the days the old data collector did not store with --set DATE=VALUE. Values are copied
unchanged, also values that are not a number.

Safeguards:
- By default it is a dry run that prints every change per file. Only --apply writes.
- It aborts without changes if the youngest stored date is on or after CLOCK_CHANGE_DATE:
  then the old data collector ran after the device clock was set, and the values of that
  run do not have the offset of one day.
- --set on a date that already has a different value after the move is an error, and so
  is --set after CLOCK_CHANGE_DATE (from the next day on the data collector stores the
  values). Days without a value from the youngest moved date up to CLOCK_CHANGE_DATE are
  reported.
- --apply first copies every file it changes to <file>.<timestamp>.bak in the data folder,
  then writes each file atomically (temporary file and rename, like the data collector).
  The marker file fix_date_offset.done.json in the data folder records date and
  parameters of the run; while it exists, the script refuses to run again.

Data folder, file prefix, column names and date pattern come from the configuration
(--config-file, default ./src/config.json). Relative paths start at the current directory,
so run it from the repository root. Only the standard library and src/datacollector are
needed, so any Python 3.11 or newer works, with or without the virtual environment.

Usage on the Raspberry Pi, from the repository root (DATE=VALUE in litres):

    python3 scripts/fix_date_offset.py --set 2026-11-18=120 --set 2026-11-19=80
    python3 scripts/fix_date_offset.py --set 2026-11-18=120 --set 2026-11-19=80 --apply

The first call is the dry run; check its output before adding --apply.
"""

import argparse
import csv
import dataclasses
import datetime
import json
import os
import pathlib
import re
import shutil
import sys
import typing

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import datacollector  # noqa: E402

# the device clock was set on this day; the old data collector stored values up to the
# day before at the latest, and from the next day on the data collector stores them
CLOCK_CHANGE_DATE = datetime.date(2026, 11, 19)
ONE_DAY = datetime.timedelta(days=1)

MARKER_NAME = "fix_date_offset.done.json"
STATUS_IN_PROGRESS = "in progress"
STATUS_DONE = "done"

SET_ARGUMENT = re.compile(r"(\d{4}-\d{2}-\d{2})=(\d+)", re.ASCII)


class MigrationError(Exception):
    """the migration cannot run as requested"""


@dataclasses.dataclass(frozen=True)
class DataFiles:
    """location and format of the yearly data files, from the configuration"""

    folder: pathlib.Path
    prefix: str
    date_column: str
    value_column: str
    date_pattern: str

    def path(self, year: int) -> pathlib.Path:
        return self.folder / f"{self.prefix}_{year}.csv"

    @property
    def marker(self) -> pathlib.Path:
        return self.folder / MARKER_NAME


@dataclasses.dataclass(frozen=True)
class Entry:
    """value of one day after the migration and where it comes from"""

    value: str
    source: str


@dataclasses.dataclass(frozen=True)
class FileChange:
    """content of one yearly file before and after the migration"""

    path: pathlib.Path
    exists: bool
    old: dict  # datetime.date -> str
    new: dict  # datetime.date -> Entry

    def new_values(self) -> dict:
        return {day: entry.value for day, entry in self.new.items()}

    @property
    def changed(self) -> bool:
        return not self.exists or self.old != self.new_values()


@dataclasses.dataclass(frozen=True)
class Migration:
    files: list  # FileChange, sorted by year
    youngest: datetime.date  # youngest stored date before the move
    set_values: dict  # datetime.date -> str
    gaps: list  # (first, last) of the days without value up to CLOCK_CHANGE_DATE


def local_now() -> datetime.datetime:
    """current local time with its UTC offset"""
    return datetime.datetime.now().astimezone()


def read_config(config_file: str) -> DataFiles:
    config = datacollector.check_configuration(config_file)
    data_file = config["dataFile"]
    return DataFiles(
        folder=pathlib.Path(config["dataPath"]),
        prefix=data_file["prefix"],
        date_column=data_file["fieldnames"]["date"],
        value_column=data_file["fieldnames"]["value"],
        date_pattern=data_file["datePattern"],
    )


def find_data_files(files: DataFiles) -> dict:
    """yearly data files in the data folder: year -> path"""
    if not files.folder.is_dir():
        raise MigrationError(f"data folder {files.folder} does not exist")
    year_file = re.compile(rf"{re.escape(files.prefix)}_(\d{{4}})\.csv")
    found = {}
    for path in files.folder.iterdir():
        match = year_file.fullmatch(path.name)
        if match and path.is_file():
            found[int(match.group(1))] = path
    if not found:
        raise MigrationError(
            f"no data files {files.prefix}_<year>.csv in {files.folder}"
        )
    return dict(sorted(found.items()))


def parse_stored_date(text: str, pattern: str) -> datetime.date:
    """date of a data file row; it has to be written exactly in the date pattern"""
    try:
        day = datetime.datetime.strptime(text, pattern).date()
    except ValueError:
        day = None
    if day is None or day.strftime(pattern) != text:
        raise ValueError(f"date {text!r} does not match the date pattern {pattern!r}")
    return day


def read_data_file(path: pathlib.Path, year: int, files: DataFiles) -> dict:
    """values of one yearly file: date -> value as stored"""
    columns = [files.date_column, files.value_column]
    values = {}
    with path.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.reader(csv_file)
        header = next(reader, None)
        if header != columns:
            found = ",".join(header) if header else "(none)"
            raise MigrationError(
                f"{path.name}: header {found} instead of {','.join(columns)}"
            )
        for row in reader:
            if not row:
                continue
            where = f"{path.name} line {reader.line_num}"
            if len(row) != len(columns):
                raise MigrationError(f"{where}: {len(row)} columns instead of 2")
            text, value = row
            try:
                day = parse_stored_date(text, files.date_pattern)
            except ValueError as err:
                raise MigrationError(f"{where}: {err}") from None
            if day.year != year:
                raise MigrationError(f"{where}: {text} does not belong to {year}")
            if day in values:
                raise MigrationError(f"{where}: {text} appears twice")
            values[day] = value
    return values


def load_data(files: DataFiles) -> dict:
    """values of all yearly files: year -> (date -> value)"""
    return {
        year: read_data_file(path, year, files)
        for year, path in find_data_files(files).items()
    }


def missing_days(entries: dict, first: datetime.date, last: datetime.date) -> list:
    """days from first to last without entry, as (first, last) of each gap"""
    gaps = []
    day = first
    while day <= last:
        if day not in entries:
            if gaps and gaps[-1][1] == day - ONE_DAY:
                gaps[-1] = (gaps[-1][0], day)
            else:
                gaps.append((day, day))
        day += ONE_DAY
    return gaps


def plan_migration(files: DataFiles, old_files: dict, set_values: list) -> Migration:
    """
    move every value one day back and add the --set values; nothing is written here
    :param old_files: year -> (date -> value), see load_data
    :param set_values: list of (date, value) from --set
    :raises MigrationError: the migration must not run
    """
    stored = {day: value for values in old_files.values() for day, value in values.items()}
    if not stored:
        raise MigrationError("the data files contain no values")
    youngest = max(stored)
    if youngest >= CLOCK_CHANGE_DATE:
        raise MigrationError(
            f"the youngest stored date is {youngest}, on or after {CLOCK_CHANGE_DATE}"
            " (device clock set): the old data collector ran after the clock change,"
            " so the values of that run do not have the offset of one day"
        )
    new = {day - ONE_DAY: Entry(value, f"from {day}") for day, value in stored.items()}

    requested = {}
    for day, value in set_values:
        if day in requested:
            raise MigrationError(f"--set {day} is given twice")
        if day > CLOCK_CHANGE_DATE:
            raise MigrationError(
                f"--set {day} is after {CLOCK_CHANGE_DATE}: from"
                f" {CLOCK_CHANGE_DATE + ONE_DAY} on the data collector stores the values"
            )
        requested[day] = value
    conflicts = [
        f"--set {day}={value}, but {day} has {new[day].value} ({new[day].source})"
        for day, value in sorted(requested.items())
        if day in new and new[day].value != value
    ]
    if conflicts:
        raise MigrationError("conflict with a moved value: " + "; ".join(conflicts))
    for day, value in requested.items():
        source = f"{new[day].source} (= --set)" if day in new else "--set"
        new[day] = Entry(value, source)

    changes = []
    for year in sorted(set(old_files) | {day.year for day in new}):
        changes.append(
            FileChange(
                path=files.path(year),
                exists=year in old_files,
                old=old_files.get(year, {}),
                new={day: new[day] for day in sorted(new) if day.year == year},
            )
        )
    return Migration(
        files=changes,
        youngest=youngest,
        set_values=requested,
        gaps=missing_days(new, youngest, CLOCK_CHANGE_DATE),
    )


def shown(value: str | None) -> str:
    if value is None:
        return "-"
    return value if value else '""'


def count(values: dict) -> str:
    return f"{len(values)} value" if len(values) == 1 else f"{len(values)} values"


def print_report(migration: Migration, files: DataFiles) -> None:
    """every change per file, then the days without value"""
    print(f"[*] data folder: {files.folder}")
    print(
        f"[*] every value moves one day back; youngest stored date"
        f" {migration.youngest} -> {migration.youngest - ONE_DAY}"
    )
    for change in migration.files:
        name = change.path.name
        if not change.exists:
            print(f"[*] {name}: new file, {count(change.new)}")
        elif not change.changed:
            print(f"[*] {name}: unchanged, {count(change.old)}")
            continue
        else:
            print(f"[*] {name}: {count(change.old)} -> {count(change.new)}")
        for day in sorted(set(change.old) | set(change.new)):
            entry = change.new.get(day)
            new, source = (entry.value, entry.source) if entry else (None, "removed")
            old = change.old.get(day)
            print(f"    {day}  {shown(old):>6} -> {shown(new):<6}  {source}")
    for first, last in migration.gaps:
        if first == last:
            print(f"[!] no value for {first}")
        else:
            days = (last - first).days + 1
            print(f"[!] no value for {first} ... {last} ({days} days)")


def write_atomically(path: pathlib.Path, write: typing.Callable) -> None:
    """write into a temporary file next to path, then replace path (like write_data())"""
    tmp_file = path.with_name(f".{path.name}.tmp")
    try:
        with tmp_file.open(mode="w", newline="", encoding="utf-8") as out_file:
            write(out_file)
            out_file.flush()
            os.fsync(out_file.fileno())
        if path.exists():
            shutil.copymode(path, tmp_file)
        os.replace(tmp_file, path)
    except BaseException:
        tmp_file.unlink(missing_ok=True)
        raise


def write_data_file(path: pathlib.Path, files: DataFiles, values: dict) -> None:
    """write one yearly file in the format of the data collector"""

    def write(out_file):
        writer = csv.writer(out_file)
        writer.writerow([files.date_column, files.value_column])
        for day in sorted(values):
            writer.writerow([day.strftime(files.date_pattern), values[day]])

    write_atomically(path, write)


def write_marker(path: pathlib.Path, info: dict) -> None:
    write_atomically(
        path, lambda out_file: out_file.write(json.dumps(info, indent=2) + "\n")
    )


def check_marker(files: DataFiles) -> None:
    """:raises MigrationError: the marker of an earlier --apply exists"""
    marker = files.marker
    if not marker.exists():
        return
    try:
        info = json.loads(marker.read_text(encoding="utf-8"))
        status, started = info.get("status"), info.get("started")
    except (OSError, ValueError, AttributeError):
        status, started = "unreadable", "unknown"
    if status == STATUS_IN_PROGRESS:
        hint = (
            "an earlier --apply did not finish; restore the backups listed in the"
            " marker, then delete it"
        )
    else:
        hint = "the migration was already applied and must run only once"
    raise MigrationError(f"{marker} exists (status {status}, started {started}): {hint}")


def apply_migration(
    migration: Migration,
    files: DataFiles,
    config_file: str,
    now: typing.Callable[[], datetime.datetime],
) -> None:
    """back up, write the marker (in progress), write the files, mark the marker done"""
    started = now()
    stamp = started.strftime("%Y%m%dT%H%M%S")
    changed = [change for change in migration.files if change.changed]
    backups = {
        change.path: change.path.with_name(f"{change.path.name}.{stamp}.bak")
        for change in changed
        if change.exists
    }
    for backup in backups.values():
        if backup.exists():
            raise MigrationError(f"backup {backup} already exists")
    for path, backup in backups.items():
        shutil.copy2(path, backup)
        print(f"[*] backup {backup.name}")

    marker = {
        "script": pathlib.Path(__file__).name,
        "status": STATUS_IN_PROGRESS,
        "started": started.isoformat(timespec="seconds"),
        "finished": None,
        "clockChangeDate": CLOCK_CHANGE_DATE.isoformat(),
        "shiftDays": -1,
        "configFile": config_file,
        "dataPath": str(files.folder),
        "set": {
            day.isoformat(): value for day, value in sorted(migration.set_values.items())
        },
        "files": [change.path.name for change in changed],
        "backups": [backup.name for backup in backups.values()],
    }
    write_marker(files.marker, marker)
    for change in changed:
        write_data_file(change.path, files, change.new_values())
        print(f"[*] written {change.path.name}")
    marker.update(status=STATUS_DONE, finished=now().isoformat(timespec="seconds"))
    write_marker(files.marker, marker)


def parse_set(text: str) -> tuple:
    """DATE=VALUE of --set as (datetime.date, value)"""
    match = SET_ARGUMENT.fullmatch(text.strip())
    if not match:
        raise argparse.ArgumentTypeError(
            f"expected DATE=VALUE with DATE as YYYY-MM-DD and VALUE in whole litres,"
            f" e.g. 2026-11-18=120: {text!r}"
        )
    try:
        day = datetime.date.fromisoformat(match.group(1))
    except ValueError as err:
        raise argparse.ArgumentTypeError(f"invalid date in {text!r}: {err}") from None
    return day, str(int(match.group(2)))


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "one-time migration: move every stored consumption value one day back"
            " (dry run unless --apply)"
        )
    )
    parser.add_argument(
        "--config-file", "-c", default="./src/config.json", help="set config file"
    )
    parser.add_argument(
        "--set",
        type=parse_set,
        action="append",
        metavar="DATE=VALUE",
        help="store VALUE (litres) under DATE (YYYY-MM-DD) after the move; repeatable",
    )
    parser.add_argument(
        "--apply", action="store_true", help="write the changes (default: dry run)"
    )
    return parser.parse_args(argv)


def main(argv=None, now: typing.Callable[[], datetime.datetime] = local_now) -> int:
    args = parse_args(argv)
    try:
        files = read_config(args.config_file)
    except FileNotFoundError as err:
        print(f"[-] no configuration: {err}", file=sys.stderr)
        return 1
    except KeyError as err:
        print(f"[-] no config parameter: {err}", file=sys.stderr)
        return 1
    except (TypeError, ValueError) as err:
        print(f"[-] invalid configuration: {err}", file=sys.stderr)
        return 1

    try:
        check_marker(files)
        migration = plan_migration(files, load_data(files), args.set or [])
    except (MigrationError, OSError, ValueError, csv.Error) as err:
        print(f"[-] {err}", file=sys.stderr)
        print("[-] nothing changed", file=sys.stderr)
        return 1

    print_report(migration, files)
    if not args.apply:
        print("[*] dry run: nothing written; add --apply to write the changes")
        return 0

    try:
        apply_migration(migration, files, args.config_file, now)
    except (MigrationError, OSError) as err:
        print(f"[-] {err}", file=sys.stderr)
        if files.marker.exists():
            print(
                f"[-] the migration is incomplete: restore the backups listed in"
                f" {files.marker}, then delete it",
                file=sys.stderr,
            )
        else:
            print("[-] no data file changed", file=sys.stderr)
        return 1
    print(f"[*] migration done; marker {files.marker}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
