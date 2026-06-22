# Scripts Repository — Module Standards

This file is a compatibility entrypoint for humans and AI agents that already know to read `MODULE_STANDARDS.md`.

The standards have been split to avoid one oversized instruction file:

- `docs/agent/PYTHON_REPO_STANDARDS.md` — reusable Python versioning, CLI, testing, style, and cross-platform standards.
- `docs/agent/SCRIPTS_REPO_STANDARDS.md` — scripts-repo-specific setup, dependency, registry, temp-root, ytaedl, and termdash rules.
- `docs/agent/LEGACY_PLANNING_MIGRATION.md` — migration from the old `plans/modules/<module>/...` taxonomy to the new project-local `docs/plans/` system.

Before changing modules in this repository, read all three files when relevant.

If this file and the split standards conflict, the split standards win.

## Essential Reminders

- Every CLI argument needs both `-X` and `--full-long-name` forms.
- Modules use `pyproject.toml` version and optional synchronized `__version__`.
- Standalone `pyscripts/` embed `__version__` after the docstring and bump it on every edit.
- PATCH is for fixes/refactors/docs/tests only; new features are MINOR.
- Entry point additions/removals/renames are MAJOR in this repo.
- Module tests keep temp roots inside `modules/<module>/.pytest_tmp_root/`.
- Add new CLIs to `modules/scripts_help/scripts_help/registry/registry.py`.
- New substantial planning belongs in `project_root/docs/plans/`, not the old `plans/modules/<module>/` taxonomy.
