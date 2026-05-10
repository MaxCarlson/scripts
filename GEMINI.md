# Scripts Repository - Gemini Context

This repository uses [`MODULE_STANDARDS.md`](MODULE_STANDARDS.md) as the
single source of truth for module versioning, CLI design, testing, Python style,
and cross-platform behavior.

Gemini CLI agents should read `MODULE_STANDARDS.md` before changing any module.
If older instructions conflict with that file, follow `MODULE_STANDARDS.md`.
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

## Key Reminder

All CLI arguments need both short and long forms. Module version bumps follow
the repository policy in `MODULE_STANDARDS.md`: MAJOR for entry point wrapper
changes, MINOR for package metadata/dependency reinstall changes, PATCH for
source-only changes.
