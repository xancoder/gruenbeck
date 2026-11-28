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

# Steps 1 and 2 of a release (CONTRIBUTING.md, "release"): the version in pyproject.toml and
# uv.lock, and CHANGELOG.md for it. The version is given without "v" (the tag gets it). It stops
# if a tracked file has uncommitted changes, because the changelog lists commits only. It does
# not commit, push or tag; it prints the steps that are left instead.

# set the version and generate CHANGELOG.md for it, e.g. `just release 0.3.0` (no commit, no tag)
release version:
    @git diff --quiet HEAD -- || { echo "commit all changes first: the changelog lists commits only" >&2; exit 1; }
    uv version {{ version }}
    uv run git-cliff --tag v{{ version }} --output CHANGELOG.md
    @echo ""
    @echo "Left to do by hand (CONTRIBUTING.md, release):"
    @echo "  1. review pyproject.toml, uv.lock and CHANGELOG.md and commit them as"
    @echo "     'chore(release): v{{ version }}'"
    @echo "  2. merge development into master with a pull request"
    @echo "  3. set the tag v{{ version }} on master and push the tag to origin"
