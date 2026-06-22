# LLM Onboarding Guide

This file is kept as a compatibility pointer for agents or humans that already look for `LLM-README.md`.

Canonical instructions now live in:

- `AGENTS.md` — repo-level agent entrypoint.
- `REPO_LLM_INSTRUCTIONS.md` — scripts-repo-specific instructions.
- `MODULE_STANDARDS.md` — compatibility entrypoint for split standards.
- `docs/agent/` — reusable Python standards, scripts-specific standards, and legacy planning migration.
- `project_root/docs/` — live project handoff and planning state.

## Core Working Loop

1. Read the relevant instruction files.
2. Run `git status`.
3. Identify `project_root`.
4. For substantial work, read or create the standard `docs/` handoff/planning files.
5. Implement in small, verifiable stages.
6. Run targeted tests and broader checks as warranted.
7. Update handoff/status/checklist docs.
8. Stage only intended files.
9. Do not commit without explicit approval.

## Legacy Note

The old task-log and `plans/modules/<module>/...` planning style is historical for new work. Use `project_root/docs/plans/` for new substantial work.
