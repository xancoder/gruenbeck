#!/usr/bin/env python3
"""
Log the daily rollover of the 14 day consumption values of the soft water system.

Read-only diagnostic tool: it polls the device clock (D_C_4_2) and the consumption values
D_Y_2_1 ... D_Y_2_3 and appends one CSV row per poll. A row gets the status "rollover"
when the values moved on compared to the last complete response. When appending to an
existing file, the comparison starts from its last complete row, so a rollover between
two runs is marked as well ("since" names the time of that row). Errors and incomplete
responses are logged and do not stop the script (the device drops requests while its
web interface is open). Every row is written immediately, so stopping the script at any
time loses nothing.

Usage on the Raspberry Pi, from the repository root (same place as the data collector):

    uv run python scripts/log_device_rollover.py --config-file ./src/config.json

Keep it running after logout (e.g. over night):

    nohup uv run python scripts/log_device_rollover.py > /dev/null 2>&1 &

or as a transient user unit (needs "loginctl enable-linger" to survive logout):

    systemd-run --user --unit=gruenbeck-rollover --working-directory="$PWD" \\
        "$(command -v uv)" run python scripts/log_device_rollover.py

Stop it with Ctrl+C, "kill <pid>" or "systemctl --user stop gruenbeck-rollover".
The result is in ./log/device_rollover.csv.
"""

import argparse
import csv
import datetime
import pathlib
import sys
import time
import typing

# the package is installed into the virtual environment (uv sync)
import gruenbeck.config
import gruenbeck.device

CLOCK_PARAMETER = "D_C_4_2"
VALUE_PARAMETERS = ("D_Y_2_1", "D_Y_2_2", "D_Y_2_3")
# the rollover is detected on these values (the first two are enough and keep
# the comparison independent of a late correction of older values)
ROLLOVER_PARAMETERS = ("D_Y_2_1", "D_Y_2_2")
FIELDNAMES = ("time", "device_clock", *VALUE_PARAMETERS, "status", "message")

STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_ROLLOVER = "rollover"

Fetch = typing.Callable[..., dict]


def local_now() -> datetime.datetime:
    """current local time with its UTC offset"""
    return datetime.datetime.now().astimezone()


def missing_values(values: dict) -> list:
    """names of the consumption values that are absent or not a number"""
    return [name for name in VALUE_PARAMETERS if not str(values.get(name) or "").strip().isdigit()]


def poll(
    host: str,
    timeout: float,
    previous: tuple | None,
    fetch: Fetch,
    since: str | None = None,
):
    """
    request the device once and classify the response
    :param previous: rollover values of the last complete response, None at the start
    :param since: time of the row previous comes from, if it is from an earlier run
    :return: (row without time, rollover values of this response or previous)
    """
    try:
        values = fetch(host, [CLOCK_PARAMETER, *VALUE_PARAMETERS], timeout=timeout)
    except Exception as err:  # never stop logging because of one failed request
        row = {"status": STATUS_ERROR, "message": f"{type(err).__name__}: {err}"}
        return row, previous

    row = {
        "device_clock": values.get(CLOCK_PARAMETER) or "",
        **{name: values.get(name) or "" for name in VALUE_PARAMETERS},
    }
    missing = missing_values(values)
    if missing:
        row.update(status=STATUS_ERROR, message=f"incomplete response: {', '.join(missing)}")
        return row, previous

    current = tuple(values[name].strip() for name in ROLLOVER_PARAMETERS)
    if previous is not None and current != previous:
        message = ", ".join(
            f"{name} {old} -> {new}"
            for name, old, new in zip(ROLLOVER_PARAMETERS, previous, current, strict=True)
        )
        if since:
            message += f" (since {since})"
        row.update(status=STATUS_ROLLOVER, message=message)
    else:
        row.update(status=STATUS_OK, message="")
    return row, current


def last_complete_row(output: pathlib.Path) -> dict | None:
    """
    last row of an earlier run with status ok or rollover and all values
    :return: the row, or None if the file is missing, empty or has no complete row
    :raises ValueError: the file has a different header, so it is not a log of this script
    """
    if not output.exists() or output.stat().st_size == 0:
        return None
    last = None
    with output.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        if tuple(reader.fieldnames or ()) != FIELDNAMES:
            raise ValueError(
                f"{output} has a different header: {','.join(reader.fieldnames or ())}"
            )
        for row in reader:
            if row["status"] in (STATUS_OK, STATUS_ROLLOVER) and not missing_values(row):
                last = row
    return last


def append_row(output: pathlib.Path, row: dict) -> None:
    """append one row; the header is written only into a new or empty file"""
    output.parent.mkdir(parents=True, exist_ok=True)
    write_header = not output.exists() or output.stat().st_size == 0
    with output.open(mode="a", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=FIELDNAMES, restval="")
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def run(
    host: str,
    timeout: float,
    output: pathlib.Path,
    interval: float,
    hours: float,
    fetch: Fetch = gruenbeck.device.get_data_from_mux_http,
    now: typing.Callable[[], datetime.datetime] = local_now,
    sleep: typing.Callable[[float], None] = time.sleep,
    previous_row: dict | None = None,
) -> int:
    """
    poll the device every interval seconds until hours have passed
    :param previous_row: last complete row of an earlier run (see last_complete_row)
    :return: number of written rows
    """
    start = now()
    deadline = start + datetime.timedelta(hours=hours)
    next_poll = start
    previous = None
    since = None
    if previous_row:
        previous = tuple(previous_row[name].strip() for name in ROLLOVER_PARAMETERS)
        since = previous_row["time"]
    rows = 0

    while True:
        row, previous = poll(host, timeout, previous, fetch, since)
        if row["status"] != STATUS_ERROR:
            # only the first complete response compares with the earlier run
            since = None
        row["time"] = now().isoformat(timespec="seconds")
        append_row(output, row)
        rows += 1
        print(
            " ".join(str(row.get(name, "")) for name in FIELDNAMES).rstrip(),
            flush=True,
        )

        # schedule from the start, so slow requests do not shift later polls
        next_poll += datetime.timedelta(seconds=interval)
        if next_poll > deadline:
            break
        sleep(max(0.0, (next_poll - now()).total_seconds()))

    return rows


def positive_float(text: str) -> float:
    value = float(text)
    if not value > 0:
        raise argparse.ArgumentTypeError(f"must be greater than 0: {text}")
    return value


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="log the daily rollover of the consumption values (read-only)"
    )
    parser.add_argument("--config-file", "-c", default="./src/config.json", help="set config file")
    parser.add_argument(
        "--interval",
        type=positive_float,
        default=300,
        help="seconds between two requests (default: 300)",
    )
    parser.add_argument(
        "--hours",
        type=positive_float,
        default=26,
        help="run time in hours (default: 26)",
    )
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=pathlib.Path("./log/device_rollover.csv"),
        help="csv file to append to (default: ./log/device_rollover.csv)",
    )
    return parser.parse_args(argv)


def read_device_config(config_file: str) -> tuple[str, float]:
    """host and timeout of the device from the configuration"""
    config = gruenbeck.config.check_configuration(config_file)
    device = config["softWaterSystem"]
    timeout = float(device.get("timeout", gruenbeck.device.DEFAULT_TIMEOUT))
    if not timeout > 0:
        raise ValueError("softWaterSystem.timeout must be greater than 0")
    return device["host"], timeout


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        host, timeout = read_device_config(args.config_file)
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
        previous_row = last_complete_row(args.output)
    except ValueError as err:
        print(f"[-] not appending: {err}", file=sys.stderr)
        return 1

    print(
        f"[*] logging {host} every {args.interval:g} s for {args.hours:g} h into {args.output}",
        flush=True,
    )
    if previous_row:
        print(
            f"[*] comparing with the last complete row of {previous_row['time']}",
            flush=True,
        )
    try:
        rows = run(
            host,
            timeout,
            args.output,
            args.interval,
            args.hours,
            previous_row=previous_row,
        )
    except KeyboardInterrupt:
        print("[*] stopped", flush=True)
        return 0
    print(f"[*] finished after {rows} requests", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
