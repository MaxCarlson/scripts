# Repository Agent Instructions

## Scope

This file is the repository-level `AGENTS.md`. It is intentionally short and reusable across repositories.

It extends global instructions with repository-local routing. Put repository-specific details in `REPO_LLM_INSTRUCTIONS.md` and standards documents instead of making this file long.

## Required Reading

Before changing this repository:

1. Read this file.
2. Read `REPO_LLM_INSTRUCTIONS.md` if present.
3. Read `docs/agent/README.md` if present.
4. Read `docs/agent/PYTHON_REPO_STANDARDS.md` for Python work when present.
5. Read repository-specific standards such as `MODULE_STANDARDS.md`, `CONTRIBUTING.md`, or equivalent files when present.
6. Identify `project_root`.
7. If `project_root/docs/` exists, read `docs/README.md`, `docs/HANDOFF.md`, and `docs/plans/HANDOFF.md`.
8. For an active substantial plan, read its `00_implementation-plan.md` and generated `ledger/PROGRESS.md` when present.
9. Read `docs/agent/BRANCH_INTEGRATION_WORKFLOW.md` before creating, merging, or repurposing branches.
10. Run `git status` before editing.

## Repository-Specific Instructions

Repository-specific instructions belong in:

```text
REPO_LLM_INSTRUCTIONS.md
```

That file should contain durable facts about this repository: setup commands, validation commands, package layout, project-specific constraints, important modules, and local conventions that should not be global.

Keep this `AGENTS.md` generic enough to copy into every repository.

## Hybrid Remote/Local Workflow Reminder

For a substantial repository task that is likely to require multi-file implementation, planning, broad test creation, or a long local-agent session, first determine whether the browser/app agent can perform most of the work through connected repository tools.

When the hybrid workflow is a good fit, the local agent should give one brief advisory reminder near the start of the conversation, before beginning heavy implementation. The reminder should explain that the browser/app agent can normally handle planning, edits, tests, documentation, commits, pushes, and diagnosis, leaving the local side to pull the branch and run the repository validation command.

Rules for the reminder:

- Give it at most once per conversation.
- Do not repeat it after the user has chosen a workflow.
- Do not use it for small edits, quick commands, narrowly local debugging, or work that genuinely requires the local environment.
- Do not block progress or require confirmation; continue locally unless the user redirects the task.
- Keep it to one or two sentences.

Suggested wording:

> This looks suitable for the hybrid workflow: the browser/app agent can handle most implementation and test work, while this local session mainly pulls and validates the branch. I’ll continue locally unless you want to shift the implementation there.

## Project Root Selection

If this repository is the whole project, treat the repository root as `project_root`.

If the task targets a nested module/application with its own package boundary, `AGENTS.md`, or `docs/HANDOFF.md`, treat that nested directory as `project_root`.

Nested `AGENTS.md` files are optional. A normal single-project repository needs only this root file.

## Planning and Development Ledger

For small localized edits, do not create planning folders.

For substantial work, use:

```text
project_root/docs/
├── README.md
├── HANDOFF.md
└── plans/
    ├── HANDOFF.md
    └── YYYYMMDD-HHMM_descriptive-plan-name/
        ├── 00_implementation-plan.md
        ├── 01_stage-name__planned.md
        ├── HANDOFF.md
        ├── STATUS.md
        ├── checklist.md
        └── ledger/
```

Use `stage` as the canonical term. Do not use older repository-specific planning taxonomies for new work unless `REPO_LLM_INSTRUCTIONS.md` explicitly says they remain canonical.

For a ledger-enabled plan:

- Maintain exactly one structured development-ledger state block in `00_implementation-plan.md`.
- Update that block before publishing a source-editing pass.
- Treat `ledger/PROGRESS.md` as the primary generated fresh-agent orientation after the normal handoff files.
- Never manually edit generated ledger files, especially `RUNS.jsonl`, `LATEST.json`, `PROGRESS.md`, `TRACEABILITY.md`, `MANUAL_CHECKS.md`, or `LOCAL_HANDOFF.md`.
- Keep `STATUS.md` and `checklist.md` as migration-era human context only; do not duplicate machine-generated outcomes into them indefinitely.

## Verification and Commits

- Preserve unrelated user changes.
- Run targeted tests for code changes.
- Run broader tests when the change affects shared behavior.
- Record exact commands and results through the repository validation and ledger workflow for substantial work.
- Stage only intended files.
- Do not commit unless the user explicitly approves.
