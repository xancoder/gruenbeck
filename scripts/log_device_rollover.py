#!/usr/bin/env python3
"""
Log the daily rollover of the 14 day consumption values of the soft water system.

Read-only diagnostic tool: it polls the device clock (D_C_4_2) and the consumption values
D_Y_2_1 ... D_Y_2_3 and appends one CSV row per poll. A row gets the status "rollover"
when the values moved on compared to the last complete response. Errors and incomplete
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

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import datacollector  # noqa: E402
import gruenbeck  # noqa: E402

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
    return [
        name
        for name in VALUE_PARAMETERS
        if not str(values.get(name) or "").strip().isdigit()
    ]


def poll(host: str, timeout: float, previous: tuple | None, fetch: Fetch):
    """
    request the device once and classify the response
    :param previous: rollover values of the last complete response, None at the start
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
        row.update(
            status=STATUS_ERROR, message=f"incomplete response: {', '.join(missing)}"
        )
        return row, previous

    current = tuple(values[name].strip() for name in ROLLOVER_PARAMETERS)
    if previous is not None and current != previous:
        message = ", ".join(
            f"{name} {old} -> {new}"
            for name, old, new in zip(ROLLOVER_PARAMETERS, previous, current)
        )
        row.update(status=STATUS_ROLLOVER, message=message)
    else:
        row.update(status=STATUS_OK, message="")
    return row, current


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
    fetch: Fetch = gruenbeck.get_data_from_mux_http,
    now: typing.Callable[[], datetime.datetime] = local_now,
    sleep: typing.Callable[[float], None] = time.sleep,
) -> int:
    """
    poll the device every interval seconds until hours have passed
    :return: number of written rows
    """
    start = now()
    deadline = start + datetime.timedelta(hours=hours)
    next_poll = start
    previous = None
    rows = 0

    while True:
        row, previous = poll(host, timeout, previous, fetch)
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
    parser.add_argument(
        "--config-file", "-c", default="./src/config.json", help="set config file"
    )
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
    config = datacollector.check_configuration(config_file)
    device = config["softWaterSystem"]
    timeout = float(device.get("timeout", gruenbeck.DEFAULT_TIMEOUT))
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

    print(
        f"[*] logging {host} every {args.interval:g} s for {args.hours:g} h"
        f" into {args.output}",
        flush=True,
    )
    try:
        rows = run(host, timeout, args.output, args.interval, args.hours)
    except KeyboardInterrupt:
        print("[*] stopped", flush=True)
        return 0
    print(f"[*] finished after {rows} requests", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
