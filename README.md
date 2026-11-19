# data collector - soft water system - Grünbeck

> This python script collects water consumption data from a "Grünbeck" soft water system and stores into csv file

## Getting Started

### clone git repository

```shell script
git clone https://github.com/xancoder/gruenbeck.git
```

### install dependencies into a virtual environment

The project uses [uv](https://docs.astral.sh/uv/) and needs Python 3.12 or newer (uv installs it if missing). `uv sync` creates the virtual environment `./.venv` from `pyproject.toml` and `uv.lock`:

```shell script
cd gruenbeck
uv sync --no-dev           # data collector only (production)
uv sync                    # plus the test tools (pytest, pytest-cov)
uv sync --extra analysis   # plus pandas and matplotlib for src/data-analyse.py
```

### create the config.json

The configuration file `./src/config.json` is not versioned because it contains the SMTP password. Create it from the example and modify it to your own needs and settings:

```shell script
cp src/config.example.json src/config.json
chmod 600 src/config.json
```

The file is read only by the service user, so restrict its permissions (`600`) and let that user own it.

#### existing installation with a versioned config.json

Older versions of the repository contained `src/config.json`. It is no longer versioned, so a `git pull` that brings this change removes the file (or aborts if the file was modified locally). Save the file before the next pull and put it back afterwards:

```shell script
cp src/config.json ~/gruenbeck-config.json.bak
git checkout -- src/config.json
git pull
cp ~/gruenbeck-config.json.bak src/config.json
chmod 600 src/config.json
```

#### mail settings

The section `mail` configures the SMTP server used for the data mail and the error notifications:

| key | meaning |
|-----|---------|
| `smtpServer` | host name of the SMTP server |
| `smtpPort` | port of the SMTP server (number; a string like `"587"` is still accepted) |
| `smtpSecurity` | optional, `"ssl"` (implicit TLS, usually port 465) or `"starttls"` (usually port 587). If omitted, port 465 uses `ssl` and every other port uses `starttls` |
| `senderEmail`, `senderPassword` | login and sender address |
| `recipients` | list of recipient addresses |
| `subject` | subject of the data mail |

Temporary errors (connection lost, timeout, connection failed) are retried up to 3 times with a 5 seconds delay; permanent errors (wrong login, rejected sender or recipient) fail immediately.

#### device settings

The section `softWaterSystem` configures the connection to the soft water system:

| key | meaning |
|-----|---------|
| `host` | host name (or IP address) of the soft water system |
| `timeout` | optional, seconds to wait for the connection and for the response of the device (number greater than 0, default `30`) |

If the device does not answer in time, answers with an HTTP error or returns no consumption values, the request is repeated up to 3 times with a 5 seconds delay. If it still fails, the error is logged, an error mail is sent and the script ends with exit code 1.

#### data file settings

The section `dataFile` sets the name and format of the yearly files `<prefix>_<year>.csv` in `dataPath`. Each run stores the 14-day memory of the device: the value of `D_Y_2_n` (consumption of n days ago) goes under the date of today minus n days, independent of the order of the device response.

| key | meaning |
|-----|---------|
| `firstDate` | optional, date `YYYY-MM-DD`, e.g. `"2026-11-20"`. Values of earlier days are not written (the log names their number), values already stored stay unchanged. Without the key every value is written. Use it while the device memory still holds values that would be stored under a wrong date, e.g. after setting the device clock (see the one-time migration below). The key may stay afterwards. If all values of a run are before `firstDate`, the run fails |

#### exit codes

| exit code | meaning |
|-----------|---------|
| `0` | data collected, stored and sent by mail |
| `1` | any failure: configuration or data folder invalid, device not reachable or without values, device clock missing or not past its daily rollover (see the note under [Scheduling](#scheduling)), error while processing or writing data, or the data mail could not be sent (the collected data is stored anyway) |

Cron and systemd can therefore detect a failed run by its exit code.

### manually running

```shell script
uv run python src/data-collector.py -l
```

Scheduled runs call the interpreter of the virtual environment directly (`./.venv/bin/python3 ./src/data-collector.py`), so uv is not needed at run time.

### analysis

`src/data-analyse.py` prints monthly statistics per year and plots the mean consumption. It needs the extra `analysis` (pandas, matplotlib) and reads the yearly files `<prefix>_<year>.csv` from the `dataPath` of the configuration; other files in the data folder are ignored. Like the data collector it takes `--config-file` / `-c` (default `./src/config.json`) and resolves relative paths from the current directory, so run it from the repository root:

```shell script
uv run --extra analysis python src/data-analyse.py
```

### tests

```shell script
uv run pytest
```

The tests run from any directory and write nothing into the repository.

## Scheduling

The script should run once a week. Three ways are described in [deploy/systemd/README.md](deploy/systemd/README.md):

- **systemd service with timer** (recommended): generated by `./deploy/systemd/setup_systemd.py`, runs without a login and waits for the network
- **systemd user service**: the alternative without root access
- **cron**: for machines without systemd; when switching to systemd, remove the cron entry, otherwise the data is collected twice

NOTE: The data collector stores the value of `D_Y_2_n` under today minus n days, so the soft water system must have written the consumption of the day before when the run starts. It does so shortly after midnight of its own clock (measured about 15 to 20 minutes after midnight). Before it stores anything, the data collector therefore reads the device clock (`D_C_4_2`) along with the values: if the device is not on the local day yet (or already on the next one) or its clock is before 00:30, the run stores nothing and fails with an error mail and exit code 1, for example a missed run that the systemd timer makes up (`Persistent=true`) after a restart in that time. A device clock that is more than 15 minutes off is logged as a warning, and the run goes on. It is unknown whether the device switches to daylight saving time by itself, so check the clock after each change. The weekly run (Monday 06:00) is based on the 14-day memory of the soft water system.

## One-time migration: values stored one day late (2026)

Up to this version the data collector stored every consumption value one day late: the value of `D_Y_2_1` ("yesterday") ended up under today's date. `scripts/fix_date_offset.py` corrects the existing yearly files `<prefix>_<year>.csv` once. Every value moves one day back (the value of 1 January moves into the file of the previous year, which is created if needed), and `--set DATE=VALUE` (litres, repeatable) fills in the days the old data collector did not store. Values are copied unchanged.

- Without `--apply` the script only does a dry run: it lists every change per file and writes nothing.
- It aborts without changes if the youngest stored date is 2026-11-19 or later. The device clock was set on that day, so no data collector (neither the old one nor the corrected one) may have stored values since then. If one did, copy the data files from before that run again (e.g. from the old checkout) and start over.
- `--set` on a date that already has a different value after the move is an error. The same value is accepted, so the values still in the device memory can double-check the move. Days without a value up to 2026-11-19 are reported. `--set` after 2026-11-19 is an error, because from 2026-11-20 on the data collector stores the values.
- `--apply` first copies every changed file to `<file>.<timestamp>.bak` in the data folder, then writes the files atomically and creates the marker file `fix_date_offset.done.json` there. While the marker exists, the script refuses to run again.

The script needs only the Python standard library (Python 3.11 or newer, no uv). It reads the data folder, prefix, column names and date pattern from `--config-file` / `-c` (default `./src/config.json`), so run it from the repository root.

Order on the machine running the data collector:

1. Pause the old scheduled data collector (cron entry or timer). It must not run after the device clock was set on 2026-11-19; otherwise the migration aborts.
2. Note the values of the missing days from the 14-day memory of the device (`D_Y_2_n` is the value of n days ago). Setting the clock caused an extra rollover, so 2026-11-19 takes two places in the memory. The first part is `D_Y_2_1` right after the clock change; the second part is `D_Y_2_1` after the next rollover, shortly after midnight (`scripts/log_device_rollover.py` logs it). Pass the sum of both parts as the value for 2026-11-19.
3. Prepare a fresh clone in a new directory (`uv sync --no-dev`, copy `src/config.json` from the old checkout). Do not schedule the data collector there yet.
4. Update the clone to a version that contains this script and the corrected data collector. Copy `data/` from the old checkout into the clone, run the dry run, check its output, and run the script again with `--apply`. Do this before the data collector runs in the clone for the first time. Then set `dataFile.firstDate` to `2026-11-20` in `src/config.json` (see [data file settings](#data-file-settings)). Until about 2026-12-04 the double place of 2026-11-19 shifts the older places of the memory by one day; with `firstDate` they are not written, and the values from the migration stay.
5. Run the data collector once by hand, on 2026-11-21 or later: on 2026-11-20 every value of the device memory is before `firstDate`, so the run ends with an error mail and writes nothing. Then set up the schedule (systemd timer, see [deploy/systemd/README.md](deploy/systemd/README.md), or cron with the new path) and delete the old cron entry. The first run has to take place by 2026-12-04 at the latest; after that, 2026-11-20 is no longer in the 14-day memory.

Dry run and migration, from the root of the new clone (replace `VALUE` with the litres of each day):

```shell script
python3 scripts/fix_date_offset.py --set 2026-11-16=VALUE --set 2026-11-17=VALUE --set 2026-11-18=VALUE --set 2026-11-19=VALUE
python3 scripts/fix_date_offset.py --set 2026-11-16=VALUE --set 2026-11-17=VALUE --set 2026-11-18=VALUE --set 2026-11-19=VALUE --apply
```

The backups and the marker stay in the data folder. They are not attached to the data mail, and the analysis ignores them.
