# data collector - soft water system - Grünbeck

[![CI](https://github.com/xancoder/gruenbeck/actions/workflows/ci.yml/badge.svg)](https://github.com/xancoder/gruenbeck/actions/workflows/ci.yml)

> This python package collects water consumption data from a "Grünbeck" soft water system and stores into csv file

## Getting Started

### clone git repository

```shell script
git clone https://github.com/xancoder/gruenbeck.git
```

### install dependencies into a virtual environment

The project uses [uv](https://docs.astral.sh/uv/) and needs Python 3.12 or newer (uv installs it if missing). `uv sync` creates the virtual environment `./.venv` from `pyproject.toml` and `uv.lock` and installs the package `gruenbeck` (from `src/gruenbeck/`) with the commands `gruenbeck-collect` and `gruenbeck-analyse` into `./.venv/bin`:

```shell script
cd gruenbeck
uv sync --no-dev           # data collector only (production)
uv sync                    # plus the dev tools (pytest, pytest-cov, ruff, mypy, pre-commit)
uv sync --extra analysis   # plus pandas and matplotlib for gruenbeck-analyse
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
| `firstDate` | optional, date `YYYY-MM-DD`, e.g. `"2026-11-20"`. Values of earlier days are not written (the log names their number), values already stored stay unchanged. Without the key every value is written. Use it while the device memory still holds values that would be stored under a wrong date, e.g. after setting the device clock. The key may stay afterwards. If all values of a run are before `firstDate`, the run fails |

#### exit codes

| exit code | meaning |
|-----------|---------|
| `0` | data collected, stored and sent by mail |
| `1` | any failure: configuration or data folder invalid, device not reachable or without values, new values that differ from the stored ones, e.g. a run before the daily rollover of the device (see the note under [Scheduling](#scheduling)), error while processing or writing data, or the data mail could not be sent (the collected data is stored anyway) |

Cron and systemd can therefore detect a failed run by its exit code.

### manually running

```shell script
uv run gruenbeck-collect -l
```

Scheduled runs call the command of the virtual environment directly (`./.venv/bin/gruenbeck-collect`), so uv is not needed at run time. The command replaces the former script `src/data-collector.py` with the same options and defaults; an installation that still runs the script needs the steps in [deploy/systemd/README.md](deploy/systemd/README.md#updating-from-srcdata-collectorpy).

Warnings and errors are written to the rotating file `./log/gruenbeck_error.log` (option `--log-error` / `-e`). With `-l` the data collector also logs everything from INFO on to the console; scheduled runs do without it, so the log file is the place to look for warnings.

### analysis

`gruenbeck-analyse` (formerly `src/data-analyse.py`) prints monthly statistics per year and plots the mean consumption. It needs the extra `analysis` (pandas, matplotlib) and reads the yearly files `<prefix>_<year>.csv` from the `dataPath` of the configuration; other files in the data folder are ignored. Like the data collector it takes `--config-file` / `-c` (default `./src/config.json`) and resolves relative paths from the current directory, so run it from the repository root:

```shell script
uv run --extra analysis gruenbeck-analyse
```

### project layout

| path | content |
|------|---------|
| `src/gruenbeck/cli.py` | the commands `gruenbeck-collect` and `gruenbeck-analyse` and the run of the data collector |
| `src/gruenbeck/config.py` | reading the configuration file |
| `src/gruenbeck/device.py` | web server of the soft water system: parameter file, request, meaning of the values |
| `src/gruenbeck/storage.py` | data folder and yearly data files |
| `src/gruenbeck/mail.py` | data mail and error mail |
| `src/gruenbeck/analysis.py` | monthly statistics (extra `analysis`) |
| `scripts/log_device_rollover.py` | read-only diagnostic tool for the daily rollover of the device |
| `deploy/systemd/` | systemd units and their setup |

### tests

```shell script
uv run pytest
```

The tests run from any directory and write nothing into the repository.

### code quality

The dev tools (`uv sync`) include ruff, mypy and pre-commit; their settings are in `pyproject.toml` and `.pre-commit-config.yaml`:

```shell script
uv run ruff format   # format the code (double quotes, line length 100)
uv run ruff check    # lint
uv run mypy          # check the types of src and tests
```

#### pre-commit

[pre-commit](https://pre-commit.com/) checks every commit before it is created: ruff (lint and format), basic file checks (trailing whitespace, end of file, YAML and TOML syntax, large files) and [gitleaks](https://github.com/gitleaks/gitleaks), which looks for hard-coded secrets such as the SMTP password. Install the git hooks once per clone:

```shell script
uv sync
uv run pre-commit install
```

Hooks that already exist in `.git/hooks` are kept as `<hook>.legacy` and still run first. To check all files at any time:

```shell script
uv run pre-commit run --all-files
```

The first run needs network access to set up the hook environments (gitleaks is built with a Go toolchain that pre-commit fetches). The gitleaks hook looks at the staged changes only, so `--all-files` does not scan files that are not staged. The separate hook `gitleaks-history` (manual stage) scans the whole git history instead:

```shell script
uv run pre-commit run --hook-stage manual --all-files gitleaks-history
```

#### continuous integration

`.github/workflows/ci.yml` runs on every push and pull request: `uv sync --locked`, pre-commit (ruff and the file checks), the gitleaks scan of the git history, mypy and pytest with coverage. Run the same checks locally before pushing:

```shell script
uv sync --locked
uv run pre-commit run --all-files
uv run pre-commit run --hook-stage manual --all-files gitleaks-history
uv run mypy
uv run pytest --cov
```

Dependabot (`.github/dependabot.yml`) checks the Python dependencies (uv) and the GitHub Actions once a week and opens one pull request per ecosystem. The hook versions in `.pre-commit-config.yaml` are not covered by it; update them with `uv run pre-commit autoupdate`, and keep the ruff version there in line with `uv.lock`.

## Scheduling

The script should run once a week. Three ways are described in [deploy/systemd/README.md](deploy/systemd/README.md):

- **systemd service with timer** (recommended): generated by `./deploy/systemd/setup_systemd.py`, runs without a login and waits for the network
- **systemd user service**: the alternative without root access
- **cron**: for machines without systemd; when switching to systemd, remove the cron entry, otherwise the data is collected twice

NOTE: The data collector stores the value of `D_Y_2_n` under today minus n days, so the run has to take place after the daily rollover of the soft water system, when `D_Y_2_1` is the consumption of the day before. The rollover does not follow the device clock: this device moves its values on every day at about 10:05, before and after its clock was set on 2026-11-19 (measured with `scripts/log_device_rollover.py`). A value therefore covers the 24 hours from one rollover to the next and is stored under the day it starts. The weekly run (Monday 16:00) is well after the rollover and is based on the 14-day memory of the soft water system.

Before it writes anything, the data collector compares the new values with the days that are stored already (7 days for weekly runs); values of past days do not change on the device. If they differ, it writes nothing and fails with an error mail and exit code 1. If every new value equals the stored value of the day before, the run was probably before the rollover, for example a missed run that the systemd timer makes up (`Persistent=true`) in the morning; run it again later. A run before the rollover is not detected when there is no stored day to compare with (the first run, or after a pause of more than 14 days). The data collector also reads the device clock (`D_C_4_2`) and logs a warning in `log/gruenbeck_error.log` if it is missing, invalid or more than 15 minutes off; it is unknown whether the device switches to daylight saving time by itself.
