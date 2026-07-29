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
5. Read `docs/agent/HYBRID_REMOTE_LOCAL_DEVELOPMENT_WORKFLOW.md` for substantial work.
6. For Python work, read `docs/agent/PYTHON_REPO_STANDARDS.md`.
7. For scripts-repo-specific behavior, read `docs/agent/SCRIPTS_REPO_STANDARDS.md`.
8. If working in a nested module with its own `docs/`, read that module's handoff docs.
9. Read `validation-targets.json` when the task includes local validation.
10. Run `git status`.

## Repository Shape

```text
scripts/
├── modules/
├── pyscripts/
├── pscripts/
├── bin/
├── docs/
├── Invoke-Tests.ps1
├── validation-targets.json
├── setup.py
├── AGENTS.md
├── CLAUDE.md
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

## Hybrid Browser/Local Development Workflow

Use the browser/app agent for as much repository work as connected tools permit. This includes repository inspection, planning, implementation, test creation, documentation, static review, commits, pushes, and diagnosis.

Reserve the local machine or local LLM for authoritative execution that genuinely depends on:

- the checked-out working tree,
- the operating system,
- installed tools and package state,
- credentials and private services,
- hardware,
- schedulers and background services,
- GUI/TUI behavior,
- networking and remote storage,
- performance or long-running tests.

Do not delegate broad implementation work to a local agent merely because the repository is local. The remote agent should leave the smallest possible environment-dependent validation remainder.

For each substantial stage:

1. Update the active plan, status, checklist, and handoff files.
2. Implement source, tests, scripts, and documentation on the feature branch.
3. Review the complete diff and correct obvious defects.
4. Commit and push the coherent stage.
5. Have the user pull the branch and run the repository-root validation dispatcher.
6. Have the user commit and push the generated tracked validation report changes.
7. Read each target's `LATEST.txt` remotely, diagnose failures, and implement the next pass.
8. Repeat until automated, environment-specific, and acceptance validation pass.

Do not have local and remote agents independently edit the same branch concurrently. Use a separate patch branch if a local agent must author code.

Local agents should apply the one-time substantial-task reminder defined in `AGENTS.md`. The reminder is advisory, appears at most once per conversation, and must not interrupt small or inherently local work.

## Repository Validation Dispatcher

The canonical local validation entry point is:

```powershell
./Invoke-Tests.ps1
```

Its target manifest is:

```text
validation-targets.json
```

The dispatcher must support one or more named targets, bootstrap declared dependencies by default, run language-native tests and platform-specific validation scripts, capture complete stdout and stderr, preserve exit codes, and write tracked reports under:

```text
docs/test-results/<target>/
├── LATEST.txt
└── history/
    └── YYYYMMDD-HHMMSS_<target>.txt
```

`LATEST.txt` is always authoritative. History is comparison-only and is bounded by default to three prior reports and 14 days.

The active remote agent should update `validation-targets.json` whenever the current stage requires different modules, commands, scripts, setup steps, or read-only environment checks. The user should normally only need to pull and run the same root command.

Default validation must use isolated temporary resources and must not mutate production systems. Production read-only checks require an explicit switch. Destructive acceptance checks require explicit approval and isolated targets.

## UI / TUI Reuse

When building reusable terminal UI components, prefer placing reusable widgets/components in `modules/termdash` rather than one-off downstream UI code.

## Planning System

The old `plans/modules/<module>/INDEX.md`, `user/`, and `ai/` taxonomy is legacy for new work.

For new substantial work, use the standard system under:

```text
project_root/docs/plans/YYYYMMDD-HHMM_descriptive-plan-name/
```

Do not delete old plans automatically. Treat them as historical evidence and migrate only active/current state into the new docs when needed.
