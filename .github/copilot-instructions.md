# GitHub Copilot Instructions — scripts repository

See [`MODULE_STANDARDS.md`](../MODULE_STANDARDS.md) at the repository root for
the full coding guidelines.  The summary below covers the most common decision
points.

## Versioning

`MAJOR.MINOR.PATCH` — bump MAJOR when `[project.scripts]` entry points change
(`.cmd` recreation required), bump MINOR for other `pyproject.toml` changes,
bump PATCH for source-only changes.

## CLI flags

**All flags must have both `--full-long-name` and `-X` short forms.**  No exceptions.

## Subcommands

Use argparse subcommands when a module has > 7 flags or multiple distinct
operating modes.  See `ytaedl` for the canonical example.

## Tests

Name test files `module_name_test.py` (suffix `_test.py`, not prefix `test_`).
Use `tmp_path` — never write to relative paths in tests.

## Full guidelines

→ [`MODULE_STANDARDS.md`](../MODULE_STANDARDS.md)

## Plans

Durable implementation plans belong under `plans/`. Retain older plans there
with dated or `superseded_` naming instead of deleting them.
