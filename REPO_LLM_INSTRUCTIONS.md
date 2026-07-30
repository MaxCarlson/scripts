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
6. Read `docs/agent/BRANCH_INTEGRATION_WORKFLOW.md` before branch creation or integration.
7. For Python work, read `docs/agent/PYTHON_REPO_STANDARDS.md`.
8. For scripts-repository-specific behavior, read `docs/agent/SCRIPTS_REPO_STANDARDS.md`.
9. If working in a nested module with its own `docs/`, read that module's handoff documents.
10. Read `validation-targets.json` when the task includes local validation.
11. For a ledger-enabled active plan, read `00_implementation-plan.md` and `ledger/PROGRESS.md`.
12. Run `git status`.

## Repository Shape

```text
scripts/
├── modules/
├── pyscripts/
├── pscripts/
├── bin/
├── validation/
├── docs/
├── Invoke-Tests.ps1
├── validation-targets.json
├── setup.py
├── AGENTS.md
├── REPO_LLM_INSTRUCTIONS.md
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
- Module tests must keep temporary roots inside the owning module directory, normally `modules/<module>/.pytest_tmp_root/`.
- Preserve unrelated user state. Do not stage or commit unless explicitly approved.

## Branch Topology

Use this branch hierarchy for substantial work:

```text
main
  ↑ accepted integration
agent/unified
  ↑ feature integration
agent/<coherent-work>
```

- `main` is the stable accepted baseline.
- `agent/unified` is the shared integration branch for completed feature branches and combined validation.
- Create substantial work branches from current `agent/unified` unless the user explicitly chooses another base.
- Do not perform ordinary feature development directly on `main` or use `agent/unified` as a long-lived personal feature branch.
- Do not let browser/app and local agents independently edit the same branch.
- A local source-editing assignment uses a separate patch branch.
- Retire merged feature branches; do not continue publishing to an obsolete branch after integration.
- Follow `docs/agent/BRANCH_INTEGRATION_WORKFLOW.md` for merge gates and recovery rules.

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

1. Update the active plan's structured development-ledger state block.
2. Implement source, tests, scripts, documentation, and validation configuration on the feature branch.
3. Review the complete diff and correct obvious defects.
4. Commit and push the coherent stage.
5. Have the user pull the branch and run the repository-root validation dispatcher.
6. Have the user commit and push generated validation and ledger evidence.
7. Read `ledger/PROGRESS.md`, routing output, manual checks, and the current raw transcript before editing again.
8. Continue, replan, request a manual check, or create a narrow local handoff.
9. Merge accepted feature work into `agent/unified` for combined validation before `main`.

Local agents should apply the one-time substantial-task reminder defined in `AGENTS.md`. The reminder is advisory, appears at most once per conversation, and must not interrupt small or inherently local work.

## Development Ledger

The reusable implementation is located at:

```text
modules/development_ledger/
```

A ledger-enabled plan writes generated state under:

```text
<active-plan>/ledger/
├── RUNS.jsonl
├── LATEST.json
├── PROGRESS.md
├── TRACEABILITY.md
├── MANUAL_CHECKS.md
└── LOCAL_HANDOFF.md
```

Rules:

- The structured state block in `00_implementation-plan.md` is the only recurring LLM-maintained progress input.
- Before publishing a source-editing pass, update the session objective, hypothesis, target IDs, implementation states, test mappings, manual checks, environment dependencies, and relevant files.
- `PROGRESS.md` is the first generated project-state view to read after normal handoff documents.
- `RUNS.jsonl` is append-only. Never manually edit it or any generated ledger projection.
- Validation evidence must be pushed before the next remote modification pass.
- The remote agent must review generated progress, traceability, routing, and pending manual checks before continuing.
- A generated `LOCAL_HANDOFF.md` authorizes only the narrow assignment it contains; source changes use a separate patch branch.
- During migration, `LATEST.txt` remains the authoritative raw validation transcript. Ledger projections are the authoritative normalized progress and routing views when present.
- `LATEST_CONTEXT.md`, `LATEST_PROGRESS.diff`, `STATUS.md`, and `checklist.md` may remain temporarily but must not become parallel manually maintained sources of the same facts.

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

`LATEST.txt` remains the current raw diagnostic transcript during ledger migration. History is comparison-only and bounded by default to three prior reports and 14 days.

Validation commands may use declarative `file_command` plus `file_targets` rules. Each rule specifies a target-relative path, maximum depth, and extension set. Do not enumerate every source filename when folder/depth/extension discovery expresses the intent safely.

For ledger-enabled targets, the dispatcher should eventually:

1. resolve the active plan and ledger output;
2. emit JUnit and generic script-result evidence;
3. run all normal validation phases;
4. invoke development-ledger recording last;
5. preserve the original validation failure status;
6. fail successful validation when required evidence cannot be recorded;
7. display generated progress, routing, and pending manual checks.

The active remote agent updates `validation-targets.json` whenever the current stage requires different modules, commands, scripts, setup steps, evidence paths, or read-only environment checks. The user should normally only need to pull and run the same root command.

Default validation must use isolated temporary resources and must not mutate production systems. Production read-only checks require an explicit switch. Destructive acceptance checks require explicit approval and isolated targets.

## UI / TUI Reuse

When building reusable terminal UI components, prefer placing reusable widgets/components in `modules/termdash` rather than one-off downstream UI code.

## Planning System

The old `plans/modules/<module>/INDEX.md`, `user/`, and `ai/` taxonomy is legacy for new work.

For new substantial work, use the standard system under:

```text
project_root/docs/plans/YYYYMMDD-HHMM_descriptive-plan-name/
```

Do not delete old plans automatically. Treat them as historical evidence and migrate only active/current state into the new documents when needed.
