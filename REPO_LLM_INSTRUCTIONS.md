# Scripts Repository-Specific LLM Instructions

This file contains instructions specific to the `scripts/` repository.

Generic agent behavior belongs in global `AGENTS.md`. Reusable Python standards belong in `docs/agent/PYTHON_REPO_STANDARDS.md`. Scripts-only standards belong in `docs/agent/SCRIPTS_REPO_STANDARDS.md`.

## Repository Purpose

`~/src/scripts/` is a personal automation toolkit for cross-platform development on Windows 11, WSL2/Ubuntu, and Termux.

## Required Reading

Before modifying this repository:

1. Read `AGENTS.md`.
2. Read this file.
3. Read `MODULE_STANDARDS.md` for compatibility routing.
4. Read `docs/agent/README.md`.
5. For Python work, read `docs/agent/PYTHON_REPO_STANDARDS.md`.
6. For scripts-repo-specific behavior, read `docs/agent/SCRIPTS_REPO_STANDARDS.md`.
7. If working in a nested module with its own `docs/`, read that module's handoff docs.
8. Run `git status`.

## Repository Shape

```text
scripts/
├── modules/
├── pyscripts/
├── pscripts/
├── bin/
├── setup.py
├── AGENTS.md
├── MODULE_STANDARDS.md
└── docs/agent/
```

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

## Core Repository Rules

- All CLI arguments need both short and long forms.
- For modules, bump `pyproject.toml` version and `__init__.__version__` when present.
- For standalone `pyscripts/`, embed and bump `__version__` in the file.
- After adding a new pyscript or module with a CLI, update `modules/scripts_help/scripts_help/registry/registry.py`.
- Module tests must keep temp roots inside the owning module directory, normally `modules/<module>/.pytest_tmp_root/`.
- Preserve unrelated user state. Do not stage or commit unless explicitly approved.

## Token Conservation / Browser LLM Offloading

The user has hard token limits on local/CLI agents. Flag token-heavy work that does not require local file access for browser-LLM offloading.

Good offload candidates:

- implementation plans,
- design docs,
- summaries/reports,
- spec gap reviews,
- brainstorming approaches.

Must stay local:

- editing files,
- running tests,
- executing commands,
- anything needing live repo access.

When offloading:

1. Write a self-contained Markdown handoff document.
2. Tell the user exactly which files/folders to attach.
3. Keep the handoff concise and task-focused.

## UI / TUI Reuse

When building reusable terminal UI components, prefer placing reusable widgets/components in `modules/termdash` rather than one-off downstream UI code.

## Planning System

The old `plans/modules/<module>/INDEX.md`, `user/`, and `ai/` taxonomy is legacy for new work.

For new substantial work, use the standard system under:

```text
project_root/docs/plans/YYYYMMDD-HHMM_descriptive-plan-name/
```

Do not delete old plans automatically. Treat them as historical evidence and migrate only active/current state into the new docs when needed.
