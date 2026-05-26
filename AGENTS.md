# Scripts Repository

Personal automation scripts and utilities for cross-platform development
(Windows 11, Termux, WSL2).

## Required Reference

All AI coding assistants must read and follow [`MODULE_STANDARDS.md`](MODULE_STANDARDS.md)
before changing modules in this repository. It is the single source of truth for:

- module versioning semantics and setup reinstall behavior
- CLI flag and subcommand conventions
- pytest naming and coverage expectations
- module-local pytest/temp directory expectations
- Python style and cross-platform requirements
- ytaedl partial/temp directory conventions
- durable plan taxonomy under `plans/modules/<module>/INDEX.md`, `user/`, and `ai/`

If this file and `MODULE_STANDARDS.md` appear to conflict, `MODULE_STANDARDS.md`
wins.

## Versioning — read before editing any file

**Modules (`modules/`)** use `pyproject.toml` + optional `__init__.py`:
- MAJOR bump → `[project.scripts]` entry points changed (requires full reinstall + `.cmd` regeneration)
- MINOR bump → other `pyproject.toml` changes (deps, metadata)
- PATCH bump → source-only changes

**pyscripts (`pyscripts/`)** embed `__version__` directly in the file, after the docstring:
```python
"""My script."""

__version__ = "0.1.0"

import sys
```
- MAJOR → breaking change (renamed/removed flag, incompatible output)
- MINOR → new feature, new flag, new subcommand
- PATCH → bug fix, refactor, minor improvement

**Always bump** the relevant version when modifying any script or module.  Full
rules in [`MODULE_STANDARDS.md §1`](MODULE_STANDARDS.md) (modules) and
[`§10`](MODULE_STANDARDS.md) (pyscripts).

**Help registry:** after adding a new pyscript or module-with-CLI, add an entry
to `modules/scripts_help/scripts_help/registry/registry.py`.

## Quick Commands

```bash
python setup.py -v
python setup.py -f -v
python setup.py -p
pytest tests/ -v
pytest tests/<module>_test.py -v
black --line-length 120 <file>
ruff check <file>
```

## Repository Shape

```text
scripts/
├── modules/
├── pscripts/
├── bin/
├── setup.py
├── MODULE_STANDARDS.md
└── AGENTS.md
```
