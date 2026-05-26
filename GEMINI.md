# Scripts Repository - Gemini Context

This repository uses [`MODULE_STANDARDS.md`](MODULE_STANDARDS.md) as the
single source of truth for module versioning, CLI design, testing, Python style,
and cross-platform behavior.

Gemini CLI agents should read `MODULE_STANDARDS.md` before changing any module.
If older instructions conflict with that file, follow `MODULE_STANDARDS.md`.
Durable plans use the taxonomy described there: `plans/modules/<module>/INDEX.md`
plus `user/` and `ai/` folders with indexed status filenames.

## Versioning — read before editing any file

**Modules (`modules/`)** — bump version in `pyproject.toml` (and `__init__.py` if present):
- MAJOR → `[project.scripts]` entry points changed
- MINOR → other `pyproject.toml` changes (deps, metadata)
- PATCH → source-only changes

**pyscripts (`pyscripts/`)** — bump `__version__` embedded at the top of the file:
```python
"""Docstring."""

__version__ = "0.1.0"   # place after docstring, before imports

import sys
```
- MAJOR → breaking interface change (renamed/removed flag, incompatible output)
- MINOR → new feature, flag, or subcommand
- PATCH → bug fix, refactor, minor improvement

Full rules: [`MODULE_STANDARDS.md §1`](MODULE_STANDARDS.md) (modules) and `§10` (pyscripts).

**Help registry:** add new scripts/modules to
`modules/scripts_help/scripts_help/registry/registry.py`.

## Common Commands

```bash
python setup.py -v
python setup.py -f -v
python setup.py -p
pytest tests/ -v
pytest tests/<module>_test.py -v
black --line-length 120 <file>
ruff check <file>
```

## Key Reminder

All CLI arguments need both short and long forms. Module version bumps follow
the repository policy in `MODULE_STANDARDS.md`: MAJOR for entry point wrapper
changes, MINOR for package metadata/dependency reinstall changes, PATCH for
source-only changes. Module tests must keep temp roots inside the owning module
directory, normally `modules/<module>/.pytest_tmp_root/`.
