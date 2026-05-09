# Scripts Repository - Claude Context

Claude agents should read [`MODULE_STANDARDS.md`](MODULE_STANDARDS.md) before
changing any module in this repository. It is the single source of truth for
versioning, CLI design, testing, style, and cross-platform requirements.

If this file and `MODULE_STANDARDS.md` conflict, follow `MODULE_STANDARDS.md`.

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
source-only changes.
