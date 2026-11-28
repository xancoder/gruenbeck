# data collector - soft water system - Grünbeck

[![CI](https://github.com/xancoder/gruenbeck/actions/workflows/ci.yml/badge.svg)](https://github.com/xancoder/gruenbeck/actions/workflows/ci.yml)

> This python package collects water consumption data from a "Grünbeck" soft water system and stores into csv file

## Getting Started

### clone git repository

```shell script
git clone https://github.com/xancoder/gruenbeck.git
```

### install dependencies into a virtual environment

The project uses [uv](https://docs.astral.sh/uv/) and needs Python 3.12 or newer (uv installs it if missing). `.python-version` pins `3.15`, the version on the Raspberry Pi, for the virtual environment; CI tests 3.12 (the lowest supported version), 3.14 and 3.15. `uv sync` creates the virtual environment `./.venv` from `pyproject.toml` and `uv.lock` and installs the package `gruenbeck` (from `src/gruenbeck/`) with the commands `gruenbeck-collect`, `gruenbeck-analyse`, `gruenbeck-preview-mail` and `gruenbeck-log-rollover` into `./.venv/bin`:

```shell script
cd gruenbeck
uv sync --no-dev           # data collector only (production)
uv sync                    # plus the dev tools (pytest, pytest-cov, ruff, mypy, pre-commit)
uv sync --extra analysis   # plus pandas and matplotlib for gruenbeck-analyse
uv sync --all-extras       # dev tools and the extra: what CI installs
```

Without the extra, the tests that need pandas and matplotlib are skipped; `uv sync --all-extras` runs all of them.

### create the config.json

The configuration file `./src/config.json` is not versioned because it contains the SMTP password. Create it from the example and modify it to your own needs and settings:

```shell script
cp src/config.example.json src/config.json
chmod 600 src/config.json
```

The file is read only by the service user, so restrict its permissions (`600`) and let that user own it. The SMTP password is in this file (`mail.senderPassword`) unless the service gets it as a systemd credential (see [mail settings](#mail-settings)).

All commands read `./src/config.json` (relative to the current directory) unless `--config-file` / `-c` names another file. If the environment variable `GRUENBECK_CONFIG` is set and not empty, it is the default of `--config-file` instead, so a service can read a configuration outside of the repository, e.g. `/etc/gruenbeck/config.json`; the option still wins over the variable.

The data collector and the analysis check the whole file when they start: every missing key and every invalid value is listed in one message, and the run ends with exit code 1 before the device is asked. If the `mail` section itself is valid, that message also goes out as error mail. Unknown keys (e.g. a typo in an optional key) are ignored with a warning in the log.

#### paths

| key | meaning |
|-----|---------|
| `dataPath` | folder of the yearly data files; created if it does not exist (its parent folder must exist) |

A relative path starts at the folder of the configuration file, not at the current directory: in `src/config.json`, `"../data"` is the folder `data/` of the repository. Only the default of `--config-file` (`./src/config.json` unless `GRUENBECK_CONFIG` is set) and of `--log-error` (`./log/gruenbeck_error.log`) are relative to the current directory.

#### mail settings

The section `mail` configures the SMTP server used for the data mail and the error notifications:

| key | meaning |
|-----|---------|
| `smtpServer` | host name of the SMTP server |
| `smtpPort` | port of the SMTP server (number 1 ... 65535; a string like `"587"` is still accepted) |
| `smtpSecurity` | optional, `"ssl"` (implicit TLS, usually port 465) or `"starttls"` (usually port 587). If omitted, port 465 uses `ssl` and every other port uses `starttls` |
| `senderEmail`, `senderPassword` | login and sender address. `senderPassword` is optional if the SMTP password comes from a credential (see below) |
| `recipients` | list of recipient addresses |
| `subject` | subject of the data mail (may be empty) |
| `retries` | optional, how often a mail is sent again after a temporary error (whole number, 0 or greater, default `3`) |
| `retryDelay` | optional, seconds to wait before every repeated attempt (number, 0 or greater, default `5`) |

Temporary errors (connection lost, timeout, connection failed) are retried `retries` times, `retryDelay` seconds apart; permanent errors (wrong login, rejected sender or recipient) fail immediately.

##### SMTP password as a systemd credential

The password need not be in `src/config.json`. If the environment variable `CREDENTIALS_DIRECTORY` is set (systemd does that for a service with `LoadCredential=`) and the folder holds a file `smtp-password`, its content is the SMTP password, without a final line break, and `senderPassword` is optional:

- Both there: the credential wins, and the log gets the warning `the credential 'smtp-password' is used as SMTP password; remove 'mail.senderPassword' from the configuration file`. Remove the key, the file does not need the password any more.
- Neither there: the configuration error names both ways (the key and the credential).
- A credential that is empty or cannot be read is a configuration error; it is not replaced by `senderPassword`. As the `mail` section is then unusable, no error mail is sent.

The password appears in no log entry and in no mail. How to create the file and let the service load it is in [deploy/systemd/README.md](deploy/systemd/README.md#smtp-password-as-credential). Commands that never log in to the SMTP server do not need the password: `gruenbeck-analyse` and `gruenbeck-preview-mail` without `--send-to` run without `senderPassword` and without a credential (a password that is there is still used and checked). `gruenbeck-collect` and `gruenbeck-preview-mail --send-to` stop with the error above if the password is missing, so start the collector through the service (`sudo systemctl start gruenbeck-collector.service`) once the key is removed.

#### device settings

The section `softWaterSystem` configures the connection to the soft water system:

| key | meaning |
|-----|---------|
| `host` | host name (or IP address) of the soft water system |
| `timeout` | optional, seconds to wait for the connection and for the response of the device, per attempt (number greater than 0, default `30`) |
| `retries` | optional, how often a failed request is repeated (whole number, 0 or greater, default `5`) |
| `retryDelay` | optional, backoff factor in seconds (number, 0 or greater, default `5`): the first repeat follows at once, the next ones after 2, 4, 8 ... times `retryDelay` (at most 2 minutes each) |

A request is repeated after a connection error, a timeout, an aborted connection and an HTTP server error (5xx). Other HTTP errors such as 404 fail at once. With the defaults the waits are 0, 10, 20, 40 and 80 seconds, so the device gets about 2.5 minutes to come back, for example when a run that was missed is made up right after the boot and the network is not ready yet. An answer that is no valid XML, has no values or lacks one of the 14 places `D_Y_2_1` ... `D_Y_2_14` is asked again after `retryDelay` seconds each time, up to `retries` times. If it still fails, the error is logged, an error mail is sent and the script ends with exit code 1. Every repeated request is logged as a warning. A run against a device that does not answer can take several minutes before it fails, because every attempt may wait up to `timeout` seconds.

Close the web interface of the device in the browser before a run: while it was open, the device broke off 4 of 6 requests in a test. The repeated requests often get through, but not reliably.

#### data file settings

The section `dataFile` sets the name and format of the yearly files `<prefix>_<year>.csv` in `dataPath`. Each run stores the 14-day memory of the device: the value of `D_Y_2_n` (consumption of n days ago) goes under the date of today minus n days, independent of the order of the device response.

| key | meaning |
|-----|---------|
| `prefix` | start of the file names, e.g. `"gruenbeck_water_consumption"` (no path separator) |
| `datePattern` | format of the dates in the files, with year, month and day, e.g. `"%Y-%m-%d"` or `"%d.%m.%Y"` ([format codes](https://docs.python.org/3/library/datetime.html#format-codes)). The rows are sorted by date |
| `fieldnames` | names of the two columns, `{"date": "date", "value": "value"}`; both are written as header, and existing files must have them |
| `firstDate` | optional, date `YYYY-MM-DD`, e.g. `"2026-11-20"`. Values of earlier days are not written (the log names their number), values already stored stay unchanged. Without the key every value is written. Use it while the device memory still holds values that would be stored under a wrong date, e.g. after setting the device clock. The key may stay afterwards. If all values of a run are before `firstDate`, the run fails |

#### values of the device

Every value of the response is checked before anything is written:

| value | result |
|-------|--------|
| a whole number of liters, 0 or greater (e.g. `93`; blanks around it are ignored) | stored |
| `-` (the device has no value for that place) | not written, a value already stored for that day stays; one warning per place in the log (parameter and date). If every value is `-`, the run fails |
| anything else (empty, text, a negative number, a decimal number, an element without text) | the run fails; the error mail names every such place |

In every failing case nothing is written, not even one of two yearly files, and an error mail is sent. The check includes days before `firstDate`.

#### exit codes

| exit code | meaning |
|-----------|---------|
| `0` | data collected, stored and sent by mail (also if only the [statistics in the data mail](#data-mail) failed) |
| `1` | any failure: configuration or data folder invalid, device not reachable or without values, new values that differ from the stored ones, e.g. a run before the daily rollover of the device (see the note under [Scheduling](#scheduling)), error while processing or writing data, or the data mail could not be sent (the collected data is stored anyway) |

Cron and systemd can therefore detect a failed run by its exit code.

Every failure is logged and, if the `mail` section of the configuration is valid, sent as error mail, also an unexpected one (with its traceback in the log file and in the mail). Exceptions: a missing configuration file is only logged, and a failed data mail is only logged (an error mail would most likely fail as well); an unexpected error of the data mail has its traceback in the log file only, an expected one (login refused, server unreachable after all attempts, mail rejected, mail cannot be built) is logged with its message only. If the log file cannot be opened (e.g. its folder `./log` is missing), the data collector only prints the reason to stderr, which the journal of a systemd service keeps.

Before it writes anything, the data collector reads every yearly file it needs. If a file lacks a column of `fieldnames`, a stored date is not exactly what `datePattern` writes (e.g. `2026-11-20` with `"%d.%m.%Y"`, or `1.12.2026` instead of `01.12.2026`), or a row ends before the value column (e.g. `2026-11-20` without a comma; an empty value after the comma is kept as it is), the run writes nothing and fails with an error mail; the message names the file and line. So changing `datePattern` or `fieldnames` later needs the existing files converted as well.

### manually running

```shell script
uv run gruenbeck-collect -l
```

Scheduled runs call the command of the virtual environment directly (`./.venv/bin/gruenbeck-collect`), so uv is not needed at run time.

Warnings and errors are written to the rotating file `./log/gruenbeck_error.log` (option `--log-error` / `-e`). With `-l` the data collector also logs everything from INFO on to the console; scheduled runs do without it, so the log file is the place to look for warnings.

### data mail

Every run ends with the data mail to the `recipients`: the subject is `mail.subject`, every CSV file directly in the data folder is attached, and the mail holds the statistics of the stored consumption as text and as HTML. They are calculated after the yearly files have been written, so they include the values of the run. All figures are whole liters.

The mail is `multipart/alternative` (text and HTML, the mail program shows the HTML) inside `multipart/mixed` with the CSV files. The **text** is plain ASCII with tables of a fixed column width (at most 78 characters per line). The **HTML** has the same tables, a table layout of at most 640 px with inline CSS that fits a phone. There is no configuration key for it: the data mail always has both parts.

The statistics cover, for the day of the run:

| part | period |
|------|--------|
| Last week | the last complete calendar week (Monday to Sunday) before the day of the run, with the value of every day. A run on another weekday (e.g. a missed run that the systemd timer makes up) reports the same week |
| Current month so far | the 1st up to yesterday; left out on the 1st of a month |
| Last month | the last complete month |
| Year so far | 1 January up to yesterday; left out on 1 January |
| Earlier years as a whole | the earlier years, each from 1 January to 31 December (with the limits below) |

Each of the first four parts is compared with the same period of the earlier years, latest year first: the calendar week with the same number (ISO week; week 53 only in years that have one), the same days of the month, the same days of the year (29 February counts only in leap years, so an earlier year ends at 28 February if the year of the run does not have the 29th), and for the last month the complete month. The table shows total, mean per day, and the minimum and maximum with their day (`MM-DD`):

```text
Year  Period          Total    Mean          Min          Max
----  ------------  --------  -----  -----------  -----------
2026  11-16..11-22     1100     157     90 11-21    300 11-20
2025  11-17..11-23      140      20     20 11-17     20 11-17
```

The comparisons stay short with two limits (constants `MIN_COVERAGE` and `MAX_COMPARED_YEARS` in `src/gruenbeck/report.py`, not configuration keys):

- An earlier period is only shown if at least **half of its days have a value** (measured or interpolated): 4 of 7 days for a week, 183 of 365 or 366 days for a year. An earlier year with fewer values is left out, and so is an earlier year without any value in the period. The period of the run itself is always shown, however few values it has.
- Of the earlier years that remain, each table shows **at most the 5 latest**.

A note below the table says how many earlier years with values in the period are left out, e.g. `4 earlier years are not shown (older than the latest 5, or with values on less than half of the days).` If no earlier year is left to show, the note is `No earlier year has enough values for this period.`

#### missing values and interpolation

A day is **missing** if no value is stored for it (no row, or a value that is not a number such as `-` from older runs), from the first stored day up to yesterday. Days before the first stored day and the day of the run itself are **without data**: the collector was not running yet, or the day is not over.

- A gap of up to 3 missing days with a measured day on both sides is **interpolated**: a straight line between the two values, in whole liters. The value counts for the total and the mean, is marked with `*` (in the list of days and at the total of the period) and is not used for the minimum and maximum, which are measured days only. Interpolated values exist for the statistics only; they are never written to the data files.
- Longer gaps and gaps at the edge of the data (for example no value for yesterday, which has no measured day after it) stay missing: total and mean cover the days with a value, and the period is marked below its row as `incomplete: 4 days missing` and, if it starts before the first stored day, `n days without data`.

#### if a part cannot be made

The data is stored before the mail is made, so the mail goes out whatever happens to its parts; the exit code stays `0` and the log file gets a warning with the traceback:

- the statistics cannot be calculated (e.g. a yearly file of an earlier year has no column of `fieldnames`): a note takes the place of the statistics in the text and in the HTML
- the HTML cannot be made: the mail has the text only

#### preview of the data mail

`gruenbeck-preview-mail` builds the data mail from the yearly files that are in the data folder already, without asking the device and without changing a file in the data folder, so the mail can be looked at (and sent to your own address) between two runs. Like the data collector it takes the configuration relative to the current directory, so run it from the repository root or pass the configuration file:

```shell script
uv run gruenbeck-preview-mail --output-dir ./log/preview
uv run gruenbeck-preview-mail --send-to me@example.com
```

| option | meaning |
|--------|---------|
| `--config-file` / `-c` | configuration file (default: `$GRUENBECK_CONFIG` if set, else `./src/config.json`) |
| `--today YYYY-MM-DD` | the day of the run for the statistics (default: today), e.g. to see the mail of the next Monday |
| `--output-dir DIR` | write `data-mail.txt` and `data-mail.html` into `DIR` (created if missing); open the HTML in a browser. Without it nothing is written, the command only reports what it built (lines of text, size of the HTML, attachments) |
| `--send-to ADDRESS` | send the mail like the data mail, with the CSV files, but to this address only and with the prefix `[preview] ` in the subject (sender and server from the `mail` section). Without it nothing is sent |

Warnings of the statistics go to stderr. An error in the configuration, the data folder, the output folder or the sending ends with a message on stderr and exit code `1`.

### analysis

`gruenbeck-analyse` prints monthly statistics per year and plots the mean consumption. It needs the extra `analysis` (pandas, matplotlib) and reads the yearly files `<prefix>_<year>.csv` from the `dataPath` of the configuration; other files in the data folder are ignored. Like the data collector it takes `--config-file` / `-c` (default `$GRUENBECK_CONFIG` if set, else `./src/config.json`, relative to the current directory) and uses `datePattern` and `fieldnames` of `dataFile`, so run it from the repository root or pass the configuration file:

```shell script
uv run --extra analysis gruenbeck-analyse
```

Without the extra it ends with exit code `1` and the message `gruenbeck-analyse: the extra 'analysis' is not installed (needs matplotlib and pandas): uv sync --extra analysis`.

### project layout

| path | content |
|------|---------|
| `src/gruenbeck/cli.py` | the commands `gruenbeck-collect` and `gruenbeck-analyse`: options, logging, error mail and exit code |
| `src/gruenbeck/collector.py` | the run of the data collector: request the device, store the new values, compose and send the data mail |
| `src/gruenbeck/config.py` | reading the configuration file |
| `src/gruenbeck/device.py` | web server of the soft water system: request, meaning of the values |
| `src/gruenbeck/storage.py` | data folder and yearly data files |
| `src/gruenbeck/mail.py` | data mail (text, HTML, CSV attachments) and error mail |
| `src/gruenbeck/report.py` | statistics of the stored consumption for the data mail (periods, missing values, interpolation); plain data, no text |
| `src/gruenbeck/report_sections.py` | the sections, notes and legend of the data mail, shared by the text and the HTML part |
| `src/gruenbeck/report_text.py` | the statistics as plain text for the data mail |
| `src/gruenbeck/report_html.py` | the statistics as HTML document for the data mail |
| `src/gruenbeck/analysis.py` | monthly statistics (extra `analysis`) |
| `src/gruenbeck/rollover.py` | the command `gruenbeck-log-rollover`: read-only diagnostic tool for the daily rollover of the device |
| `src/gruenbeck/preview.py` | the command `gruenbeck-preview-mail`: read-only preview of the data mail without the device (files, or a mail to your own address) |
| `deploy/systemd/` | systemd units and their setup |

### tests

```shell script
uv run just test   # with coverage; plain: uv run pytest
```

The tests run from any directory and write nothing into the repository, except the folder `.hypothesis/` of the property tests in the current directory (it is ignored by git).

Two dev tools shape the run:

- **pytest-randomly** shuffles the order of the tests on every run, so a test that depends on another one fails soon instead of years later. The first lines of the pytest output name the seed (`Using --randomly-seed=3811257189`). To repeat a run in the same order, for example a failed one from CI, pass that seed or take the one of the last run; to switch the shuffling off use `-p no:randomly`:

  ```shell script
  uv run pytest --randomly-seed=3811257189
  uv run pytest --randomly-seed=last
  uv run pytest -p no:randomly
  ```

- **hypothesis** generates the inputs of the property tests in `tests/test_properties.py` (about 1.5 s): they state what holds for *every* input instead of single examples, for instance that the interpolated days of a short gap lie between the measured neighbours, that a data file is read back as it was written, or that the device clock deviation is the shortest way round the clock. A failing example is shrunk to a small one and printed; the same seed (see above) generates it again, and hypothesis remembers it in `.hypothesis/` and tries it first on the next run.

### code quality

The dev tools (`uv sync`) include ruff, mypy, pre-commit and [just](https://just.systems), a command runner; the settings of the tools are in `pyproject.toml` and `.pre-commit-config.yaml`, the commands in the `justfile`. `uv run just check` runs all checks in the order of the CI, the other recipes run one check each (`uv run just --list` describes them):

```shell script
uv run just check          # all of the following, in the order of the CI
uv run just format         # format the code (double quotes, line length 100); `just format --check` only checks
uv run just lint           # ruff check
uv run just types          # mypy: the types of src, tests and deploy (strict, plus unreachable code and @typing.override)
uv run just test           # pytest with line and branch coverage of the code (src, deploy)
uv run just hooks          # all pre-commit hooks on all files (ruff, file checks, spelling, zizmor)
uv run just secrets        # gitleaks scan of the whole git history
```

Further arguments go to the tool: `uv run just test -k mail`, `uv run just format --check`.

The coverage settings are in `pyproject.toml` (`[tool.coverage.*]`): branches are measured, the tests themselves are not counted, the missing lines are listed, and the run fails below 97 % (`fail_under`). The value has to hold without the extra `analysis` (where `analysis.py` is not covered) as well as in CI. Every warning during the tests is an error (`filterwarnings` in `[tool.pytest]`); a test that expects a warning checks it with `pytest.warns`.
#### pre-commit

[pre-commit](https://pre-commit.com/) checks every commit before it is created: ruff (lint and format), basic file checks (trailing whitespace, end of file, YAML, TOML and JSON syntax, merge conflict markers, large files), [typos](https://github.com/crate-ci/typos) (spelling of code, comments and documentation), [zizmor](https://docs.zizmor.sh/) (audits the GitHub Actions workflows and the Dependabot configuration, offline) and [gitleaks](https://github.com/gitleaks/gitleaks), which looks for hard-coded secrets such as the SMTP password. The two ruff hooks are local hooks that run `uv run --no-sync ruff` (so `uv` has to be on the `PATH` and the virtual environment has to exist: `uv sync`); this way they use the ruff version from `uv.lock`, the same one as `uv run ruff`. Install the git hooks once per clone:

```shell script
uv sync
uv run pre-commit install --hook-type pre-commit --hook-type pre-push --hook-type commit-msg
```

The hook type `commit-msg` checks the first word of the commit message ([conventional-pre-commit](https://github.com/compilerla/conventional-pre-commit)): it has to be a type of the history (`feat`, `fix`, `refactor`, `test`, `docs`, `style`, `chore`, `build`, `ci` or `perf`), optionally with a scope and `!`, then `: ` and a description, for example `fix(storage): report a row without value as storage error`. Other messages are rejected. `CHANGELOG.md` is generated from these messages (see [release](#release)). The hook runs only when this hook type is installed; leave out `--hook-type commit-msg` to go without it.

`typos` only reports what it finds (the hook of the project does not write corrections into the files, because a name of the standard library such as `smtplib.SMTPHeloError` would be "corrected" too). The settings are in `pyproject.toml` (`[tool.typos]`): `assets/`, `uv.lock` and the generated `CHANGELOG.md` are not checked, and the few false positives are listed with their reason (names of `smtplib`, the SMTP command `helo`, the misspelled key of a test).

Hooks that already exist in `.git/hooks` are kept as `<hook>.legacy` and still run first. To check all files at any time:

```shell script
uv run just hooks   # same as: uv run pre-commit run --all-files --show-diff-on-failure
```

The first run needs network access to set up the hook environments (gitleaks is built with a Go toolchain that pre-commit fetches). The gitleaks hook looks at the staged changes only, so `--all-files` does not scan files that are not staged. The separate hook `gitleaks-history` (manual stage) scans the whole git history instead:

```shell script
uv run just secrets
```

#### continuous integration

`.github/workflows/ci.yml` runs on every pull request and on every push to `master` and `development` (a branch with an open pull request does not run twice; a newer run for the same branch or pull request cancels the older one). It always uses `uv sync --locked --all-extras`, so that the extra `analysis` (pandas, matplotlib) is installed and tested:

- job `checks` (Python 3.12): the recipes `hooks` (ruff, the file checks, spelling and zizmor; as separate steps the log of every check stays apart), `secrets` (the gitleaks scan of the git history) and `types` (mypy);
- job `tests`: the recipe `test` (pytest with coverage) on Python 3.12 (lowest supported version), 3.14 and 3.15 (the version on the Raspberry Pi).

The steps call the recipes of the `justfile` (`uv run just hooks`, …), so no check is spelled out in `ci.yml`. Run the same checks locally before pushing:

```shell script
uv sync --locked --all-extras
uv run just check
```

Another Python version can be tried without touching `.venv`, e.g. `uv run --isolated --locked --all-extras --python 3.12 pytest`.

The actions in `ci.yml` are pinned to the full commit SHA (with the version as a comment), not to a tag, because a tag can be moved. Dependabot (`.github/dependabot.yml`) checks the Python dependencies (uv, including ruff), the GitHub Actions (it updates SHA and comment) and the hook versions in `.pre-commit-config.yaml` (ecosystem `pre-commit`; the local ruff hooks have no version there) once a week and opens one pull request per ecosystem. Version updates wait 7 days after a release (`cooldown`); security updates are not delayed. `uv run pre-commit autoupdate` updates the hook versions by hand.

### release

The version is in `pyproject.toml` (`version`); every command prints it with `--version` (for example `gruenbeck-collect 0.2.0`), and the data collector writes it into the first line of every run in `log/gruenbeck_error.log` (`run script: …, version 0.2.0`). `CHANGELOG.md` is generated from the commit messages (Conventional Commits: `feat`, `fix`, `refactor`, `test`, `docs`, `style`, `chore`, `build`, `ci`, `perf`) with [git-cliff](https://git-cliff.org); its settings are in `pyproject.toml` (`[tool.git-cliff.*]`). Do not edit the file by hand. To release a version:

1. Commit all changes (the changelog lists commits only) and raise the version, e.g. `uv version --bump minor` (or `uv version 0.3.0`); it changes `pyproject.toml` and `uv.lock`.
2. Generate the changelog for the new version, which has no tag yet:

   ```shell script
   uv run git-cliff --tag v0.3.0 --output CHANGELOG.md
   ```

3. Commit `pyproject.toml`, `uv.lock` and `CHANGELOG.md` as `chore(release): v0.3.0` (git-cliff leaves such commits out), merge into `master`, and set the tag there (`git tag v0.3.0`, then push the tag to `origin`).

On the Raspberry Pi, `./.venv/bin/gruenbeck-collect --version` shows the installed version. After an update (`git pull`, `uv sync --no-dev`) it is the new one; the log file shows the version of every run.

## Scheduling

The script should run once a week. Three ways are described in [deploy/systemd/README.md](deploy/systemd/README.md):

- **systemd service with timer** (recommended): generated by `./deploy/systemd/setup_systemd.py`, runs without a login and waits for the network, is hardened (it may only write to `data/` and `log/`) and ends after 30 minutes at the latest
- **systemd user service**: the alternative without root access
- **cron**: for machines without systemd; when switching to systemd, remove the cron entry, otherwise the data is collected twice

NOTE: The data collector stores the value of `D_Y_2_n` under today minus n days, so the run has to take place after the daily rollover of the soft water system, when `D_Y_2_1` is the consumption of the day before. The rollover does not follow the device clock: this device moves its values on every day at about 10:05, before and after its clock was set on 2026-11-19 (measured with `gruenbeck-log-rollover`). A value therefore covers the 24 hours from one rollover to the next and is stored under the day it starts. The weekly run (Monday 16:00) is well after the rollover and is based on the 14-day memory of the soft water system.

Before it writes anything, the data collector compares the new values with the days that are stored already (7 days for weekly runs); values of past days do not change on the device. If they differ, it writes nothing and fails with an error mail and exit code 1. If every new value equals the stored value of the day before, the run was probably before the rollover, for example a missed run that the systemd timer makes up (`Persistent=true`) in the morning; run it again later. A run before the rollover is not detected when there is no stored day to compare with (the first run, or after a pause of more than 14 days). The data collector also reads the device clock (`D_C_4_2`) and logs a warning in `log/gruenbeck_error.log` if it is missing, invalid or more than 15 minutes off; it is unknown whether the device switches to daylight saving time by itself.
