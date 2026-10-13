# Scripts Repository Instructions

`scripts/` is a personal automation toolkit used on Windows 11, WSL2/Ubuntu, and Termux. This file contains repo-specific facts for agents changing code. The root `AGENTS.md` routes task-specific reading and sets the approval boundary.

## Repository conventions

- Every user-facing CLI argument has a short and long form.
- A changed module uses its `pyproject.toml` version and any exposed `__version__` in sync. A changed standalone `pyscripts/` file bumps its embedded `__version__`.
- Add new CLIs to `modules/scripts_help/scripts_help/registry/registry.py`.
- Keep module test temp roots inside the owning module, normally `modules/<module>/.pytest_tmp_root/`.
- Prefer reusable terminal UI components in `modules/termdash`.

Read `docs/agent/PYTHON_REPO_STANDARDS.md` and `docs/agent/SCRIPTS_REPO_STANDARDS.md` for the full rules when changing Python or CLI behavior. `MODULE_STANDARDS.md` points to those split files and the legacy planning guide.

## Setup and validation

Common setup commands are `python setup.py -v` and `python setup.py -f -v`. Use the targeted test command for the affected module rather than running all repository tests by default.

For a task using the repository validation dispatcher, read `validation-targets.json` and run `./Invoke-Tests.ps1` with the relevant named targets. It writes a current `docs/test-results/<target>/LATEST.txt` and bounded history. The current report is execution evidence; verify that its target, branch, command, and time match the claim being made. Default validation should use isolated resources. Live production checks need an explicit, scoped request.

## Plans and handoffs

Use `project_root/docs/plans/YYYYMMDD-HHMM_descriptive-plan-name/` for substantial multi-stage work. A nested module with its own package boundary or handoff uses that module as `project_root`; module-owned plans and handoffs belong under that module's `docs/`. Use `scripts/docs/` only for shared or repository-wide work. When a session starts at the repository root, explicitly inspect the target module's `AGENTS.md` and any more-specific instruction files before editing; Codex does not preload descendant instructions. Read only existing docs that apply to the task. Older `plans/modules/<module>/` documents are historical; consult them only when relevant. The active plan's `STATUS.md` and `checklist.md` should identify implemented work, verification, approval state, and the next action.

For hybrid browser/local work, read `docs/agent/HYBRID_REMOTE_LOCAL_DEVELOPMENT_WORKFLOW.md`. Its publish steps describe a possible division of work; they do not authorize a commit, push, or merge. Follow the approval boundary in `AGENTS.md` and the user's instructions. Avoid simultaneous edits to the same branch from local and remote agents.
