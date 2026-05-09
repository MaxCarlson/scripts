# Scripts Repository

Personal automation scripts and utilities for cross-platform development
(Windows 11, Termux, WSL2).

## Required Reference

All AI coding assistants must read and follow [`MODULE_STANDARDS.md`](MODULE_STANDARDS.md)
before changing modules in this repository. It is the single source of truth for:

- module versioning semantics and setup reinstall behavior
- CLI flag and subcommand conventions
- pytest naming and coverage expectations
- Python style and cross-platform requirements
- ytaedl partial/temp directory conventions

If this file and `MODULE_STANDARDS.md` appear to conflict, `MODULE_STANDARDS.md`
wins.

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
