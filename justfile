# The checks of the project: the same ones the CI runs (.github/workflows/ci.yml calls the
# recipes), so "green here" means "green there". just is a dev dependency: `uv run just <recipe>`.
# If a check changes, change its recipe here; the CI and CONTRIBUTING.md follow.

# list the recipes
[private]
default:
    @{{ just_executable() }} --list

# format the code with ruff (double quotes, line length 100); `just format --check` only checks
format *args:
    uv run ruff format {{ args }}

# lint with ruff
lint *args:
    uv run ruff check {{ args }}

# check the types of src, tests and deploy with mypy (strict)
types:
    uv run mypy

# tests with line and branch coverage (random order, fails below the limit of pyproject.toml)
test *args:
    uv run pytest -rs --cov {{ args }}

# pre-commit hooks on all files: ruff, file checks, spelling, workflows, secrets (staged changes)
hooks:
    uv run pre-commit run --all-files --show-diff-on-failure

# gitleaks scan of the whole git history
secrets:
    uv run pre-commit run --hook-stage manual --all-files gitleaks-history

# `uv audit` asks the OSV database (network access needed) about every package in uv.lock,
# including the extra "analysis" and the dev group; a known vulnerability fails the recipe.
# The flag --preview-features only switches off the warning that the command is experimental.
# An exception is one more argument `--ignore <ID>` (the ID uv prints, e.g. GHSA-…), with a
# comment line above the command: package, why it does not affect this project, and when the
# exception goes away. Prefer updating the package (uv lock --upgrade-package <name>).

# known vulnerabilities of the locked dependencies (uv audit)
audit:
    uv audit --locked --preview-features audit-command

# all checks in the order of the CI: hooks, secrets, audit, types, test
check: hooks secrets audit types test
