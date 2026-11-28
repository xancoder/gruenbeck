# Contributing

This file is about working on the project: layout, tests, checks, continuous integration and release. Installation, configuration and operation are described in the [README](README.md).

- The working branch is `development`; changes reach `master` only through a pull request from `development`.
- Install the dev tools and the extra `analysis` with `uv sync --locked --all-extras` (see [install dependencies](README.md#install-dependencies-into-a-virtual-environment)), and the git hooks once per clone (see [pre-commit](#pre-commit)).
- Run `uv run just check` before every push: it runs the checks of the CI (see [code quality](#code-quality)).

## project layout

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

## tests

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

## code quality

The dev tools (`uv sync`) include ruff, mypy, pre-commit and [just](https://just.systems), a command runner; the settings of the tools are in `pyproject.toml` and `.pre-commit-config.yaml`, the commands in the `justfile`. `uv run just check` runs all checks in the order of the CI, the other recipes run one check each (`uv run just --list` describes them):

```shell script
uv run just check          # all of the following, in the order of the CI
uv run just format         # format the code (double quotes, line length 100); `just format --check` only checks
uv run just lint           # ruff check
uv run just types          # mypy: the types of src, tests and deploy (strict, plus unreachable code and @typing.override)
uv run just test           # pytest with line and branch coverage of the code (src, deploy)
uv run just hooks          # all pre-commit hooks on all files (ruff, file checks, spelling, zizmor)
uv run just secrets        # gitleaks scan of the whole git history
uv run just audit          # uv audit: known vulnerabilities of the locked dependencies (network access needed)
```

Further arguments go to the tool: `uv run just test -k mail`, `uv run just format --check`.

The coverage settings are in `pyproject.toml` (`[tool.coverage.*]`): branches are measured, the tests themselves are not counted, the missing lines are listed, and the run fails below 97 % (`fail_under`). The value has to hold without the extra `analysis` (where `analysis.py` is not covered) as well as with it; CI runs both. Every warning during the tests is an error (`filterwarnings` in `[tool.pytest]`); a test that expects a warning checks it with `pytest.warns`.

### pre-commit

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

### continuous integration

`.github/workflows/ci.yml` runs on every pull request and on every push to `master` and `development` (a branch with an open pull request does not run twice; a newer run for the same branch or pull request cancels the older one). Every job starts with `uv sync --locked`; except for one test job it adds `--all-extras`, so that the extra `analysis` (pandas, matplotlib) is installed and tested:

- job `checks` (Python 3.12, all extras): the recipes `hooks` (ruff, the file checks, spelling and zizmor; as separate steps the log of every check stays apart), `secrets` (the gitleaks scan of the git history), `audit` (known vulnerabilities of the dependencies) and `types` (mypy);
- job `tests`: the recipe `test` (pytest with coverage) in four runs: `tests (3.12)` (lowest supported version), `tests (3.14)` and `tests (3.15)` (the version on the Raspberry Pi) with the extra, and `tests (3.15, without analysis)`, exactly the state of the Pi: the tests of `analysis` are skipped there, and the coverage limit has to hold all the same.

The steps call the recipes of the `justfile` (`uv run just hooks`, …), so no check is spelled out in `ci.yml`. Run the same checks locally before pushing:

```shell script
uv sync --locked --all-extras
uv run just check
```

Another Python version, or the run without the extra, can be tried without touching `.venv`, e.g. `uv run --isolated --locked --all-extras --python 3.12 pytest` or `uv run --isolated --locked --python 3.15 pytest -rs --cov` (not `just test` there: the recipe calls `uv run` again, which uses `.venv`).

The actions in `ci.yml` are pinned to the full commit SHA (with the version as a comment), not to a tag, because a tag can be moved. Dependabot (`.github/dependabot.yml`) checks the Python dependencies (uv, including ruff), the GitHub Actions (it updates SHA and comment) and the hook versions in `.pre-commit-config.yaml` (ecosystem `pre-commit`; the local ruff hooks have no version there) once a week and opens one pull request per ecosystem against `development` (`target-branch`; Dependabot reads the file from `master`, and security updates always go to `master`). Version updates wait 7 days after a release (`cooldown`); security updates are not delayed. `uv run pre-commit autoupdate` updates the hook versions by hand.

`uv run just audit` (`uv audit --locked`) looks up every package in `uv.lock`, including the extra `analysis` and the dev tools, in the [OSV](https://osv.dev) database; a known vulnerability fails the recipe and so `just check` and CI. The fix is an update of the package (`uv lock --upgrade-package <name>`). Only if the vulnerability does not affect this project and no update is possible yet, the recipe gets `--ignore <ID>`, with a comment in the `justfile` that names the package, the reason and when the exception goes away.

## release

The version is in `pyproject.toml` (`version`); every command prints it with `--version` (for example `gruenbeck-collect 0.2.0`), and the data collector writes it into the first line of every run in `log/gruenbeck_error.log` (`run script: …, version 0.2.0`). `CHANGELOG.md` is generated from the commit messages (Conventional Commits: `feat`, `fix`, `refactor`, `test`, `docs`, `style`, `chore`, `build`, `ci`, `perf`) with [git-cliff](https://git-cliff.org); its settings are in `pyproject.toml` (`[tool.git-cliff.*]`). Do not edit the file by hand. To release a version:

1. Commit all changes (the changelog lists commits only) and raise the version, e.g. `uv version --bump minor` (or `uv version 0.3.0`); it changes `pyproject.toml` and `uv.lock`.
2. Generate the changelog for the new version, which has no tag yet:

   ```shell script
   uv run git-cliff --tag v0.3.0 --output CHANGELOG.md
   ```

3. Commit `pyproject.toml`, `uv.lock` and `CHANGELOG.md` as `chore(release): v0.3.0` (git-cliff leaves such commits out), merge into `master`, and set the tag there (`git tag v0.3.0`, then push the tag to `origin`).

How to update the Raspberry Pi to the new version is in the README ([install dependencies](README.md#install-dependencies-into-a-virtual-environment)).
