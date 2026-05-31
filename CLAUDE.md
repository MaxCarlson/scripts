# Scripts Repository - Claude Context

Claude agents should read [`MODULE_STANDARDS.md`](MODULE_STANDARDS.md) before
changing any module in this repository. It is the single source of truth for
versioning, CLI design, testing, style, and cross-platform requirements.

If this file and `MODULE_STANDARDS.md` conflict, follow `MODULE_STANDARDS.md`.
Durable plans use the taxonomy described there: `plans/modules/<module>/INDEX.md`
plus `user/` and `ai/` folders with indexed status filenames.

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

## Key Reminders

All CLI arguments need both short and long forms.

**Module versioning** (`modules/` — `pyproject.toml` + optional `__init__.py`):
- MAJOR → `[project.scripts]` entry points changed
- MINOR → backward-compatible feature addition, or other `pyproject.toml` changes (deps, metadata)
- PATCH → bug fix, refactor, docs, or tests only; no new user-facing feature

`X.Y.Z` follows semantic-version intent: `Z` is PATCH and does not introduce
new functionality.

**pyscript versioning** (`pyscripts/` — `__version__` embedded in the file):
```python
"""Docstring."""

__version__ = "0.1.0"   # after docstring, before imports

import sys
```
- MAJOR → breaking interface change
- MINOR → new feature, flag, or subcommand
- PATCH → bug fix or internal/documentation improvement with no new feature

Always bump `__version__` when modifying a pyscript. Full rules: `MODULE_STANDARDS.md §10`.

Module tests must keep temp roots inside the owning module directory,
normally `modules/<module>/.pytest_tmp_root/`.

**Help registry:** after adding a new pyscript or module-with-CLI, register it in
`modules/scripts_help/scripts_help/registry/registry.py`.
