# Repository Agent Instructions

This file applies to work in `scripts/`. Codex loads it automatically. Use `REPO_LLM_INSTRUCTIONS.md` for repo-specific commands and conventions. When a task targets a nested module, inspect that module's instructions and use its docs for module-owned work.

## Start with evidence

- Run `git status` before editing and before reporting completion. If the `pscripts` submodule metadata is inaccessible, use `git -c submodule.recurse=false status --ignore-submodules=all` and state that limitation.
- Preserve unrelated changes. Check the relevant source, tests, and recent commits before treating handoff text as current fact.
- Identify the project root: use this repository for shared work, or the nested module when it has its own package boundary or `docs/HANDOFF.md`.
- When started from `scripts/`, Codex does not preload instruction files below the current directory. Before editing a nested module, find and read its `AGENTS.md` if present, plus any more-specific instruction files covering the target paths. Do not scan unrelated modules.

## Read only what the task needs

| Task | Additional guidance |
| --- | --- |
| Any repo code change | `REPO_LLM_INSTRUCTIONS.md` |
| Python or CLI change | `docs/agent/PYTHON_REPO_STANDARDS.md` and `docs/agent/SCRIPTS_REPO_STANDARDS.md` |
| Module-targeted work | The target module's `AGENTS.md` if present; its `docs/README.md`, handoffs, and active plan only when they exist and are relevant |
| Shared validation or installer change | `validation-targets.json`, `Invoke-Tests.ps1`, and the relevant `docs/agent/` guide |
| Substantial or resumed multi-stage work | `project_root/docs/HANDOFF.md`, `project_root/docs/plans/HANDOFF.md`, and the active plan's `STATUS.md` and `checklist.md`; open detailed plan/stage files as needed |
| Hybrid browser/local work | `docs/agent/HYBRID_REMOTE_LOCAL_DEVELOPMENT_WORKFLOW.md` |

`MODULE_STANDARDS.md` is a compatibility index to the split standards. Read it when updating standards or following an older module reference. For module-owned planning, use the module's `docs/plans/`; use `scripts/docs/plans/` for shared or repository-wide work.

## Work and approval

- Use a lightweight path for small edits. For substantial work, use a dated plan under `project_root/docs/plans/` when multiple implementation or validation stages are needed; keep its status and checklist accurate.
- Run focused tests for changed behavior, and broader tests when shared behavior is affected. Report exact commands and failures. Minimize routine test output.
- Stage only intended files. Do not commit, push, or merge unless the user explicitly authorizes that action, including when another guide describes a remote workflow. A continuous-execution waiver must say which actions it authorizes.
- Stop for manual validation at a stage boundary when the active plan requires it or the user asks for it.
