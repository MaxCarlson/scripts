# GitHub Copilot Instructions — scripts repository

See [`MODULE_STANDARDS.md`](../MODULE_STANDARDS.md) at the repository root for
the full coding guidelines.  The summary below covers the most common decision
points.

## Versioning

### Modules (`modules/`)
`MAJOR.MINOR.PATCH` in `pyproject.toml` (and `__init__.py` if present):
- **MAJOR** — `[project.scripts]` entry points changed (`.cmd` recreation required)
- **MINOR** — other `pyproject.toml` changes (deps, metadata)
- **PATCH** — source-only changes

### pyscripts (`pyscripts/`)
Embed `__version__` directly in the file, **after the module docstring**, before imports:
```python
"""My script — one-line description."""

__version__ = "0.1.0"

import argparse
```
- **MAJOR** — breaking: renamed/removed flag, incompatible output format
- **MINOR** — new feature, new flag or subcommand, significant behavior addition
- **PATCH** — bug fix, refactor, doc update, minor improvement

Always bump `__version__` when modifying a pyscript.  Full rules in
[`MODULE_STANDARDS.md §10`](../MODULE_STANDARDS.md).

### Help registry
After adding a new pyscript or module-with-CLI, register it in
`modules/scripts_help/scripts_help/registry/registry.py`.

## CLI flags

**All flags must have both `--full-long-name` and `-X` short forms.**  No exceptions.

## Subcommands

Use argparse subcommands when a module has > 7 flags or multiple distinct
operating modes.  See `ytaedl` for the canonical example.

## Tests

Name test files `module_name_test.py` (suffix `_test.py`, not prefix `test_`).
Use `tmp_path` — never write to relative paths in tests.
Keep module test temp roots under `modules/<module>/.pytest_tmp_root/`, not in
the repository root.

## Full guidelines

→ [`MODULE_STANDARDS.md`](../MODULE_STANDARDS.md)

## Plans

Durable implementation plans belong under `plans/`. Retain older plans there
instead of deleting them. For module plans, use
`plans/modules/<module>/INDEX.md` plus `user/` and `ai/` folders with indexed
filenames in the format documented in `MODULE_STANDARDS.md`.
