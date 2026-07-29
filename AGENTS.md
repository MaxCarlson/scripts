# Repository Agent Instructions

## Scope

This file is the repository-level `AGENTS.md`. It is intentionally short and reusable across repositories.

It extends global instructions with repo-local routing. Put repo-specific details in `REPO_LLM_INSTRUCTIONS.md` and standards documents instead of making this file long.

## Required Reading

Before changing this repository:

1. Read this file.
2. Read `REPO_LLM_INSTRUCTIONS.md` if present.
3. Read `docs/agent/README.md` if present.
4. Read `docs/agent/PYTHON_REPO_STANDARDS.md` for Python work when present.
5. Read repo-specific standards such as `MODULE_STANDARDS.md`, `CONTRIBUTING.md`, or equivalent files when present.
6. Identify `project_root`.
7. If `project_root/docs/` exists, read `docs/README.md`, `docs/HANDOFF.md`, and `docs/plans/HANDOFF.md`.
8. Run `git status` before editing.

## Repo-Specific Instructions

Repo-specific instructions belong in:

```text
REPO_LLM_INSTRUCTIONS.md
```

That file should contain durable facts about this repository: setup commands, validation commands, package layout, project-specific constraints, important modules, and any local conventions that should not be global.

Keep this `AGENTS.md` generic enough to copy into every repo.

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

Nested `AGENTS.md` files are optional. A normal single-project repo needs only this root file.

## Planning System

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
        └── checklist.md
```

Use `stage` as the canonical term. Do not use older repo-specific planning taxonomies for new work unless `REPO_LLM_INSTRUCTIONS.md` explicitly says they remain canonical.

## Verification and Commits

- Preserve unrelated user changes.
- Run targeted tests for code changes.
- Run broader tests when the change affects shared behavior.
- Record exact commands and results in the handoff/status docs for substantial work.
- Stage only intended files.
- Do not commit unless the user explicitly approves.
