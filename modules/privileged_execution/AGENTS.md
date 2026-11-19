# Module Agent Instructions — `modules/privileged_execution`

This module owns `modules/privileged_execution/**` (`privexec` CLI and `PrivExecBroker`).

## Read first

1. `docs/README.md` — architecture, build/test commands, security boundaries, and doc map.
2. `docs/HANDOFF.md` — current phase, branch, commit, verification state, and next action.
3. `docs/plans/HANDOFF.md` — active plan index.
4. Active plan under `docs/plans/20261119-privexec-session-broker/`.

## Module rules

- Follow `REPO_LLM_INSTRUCTIONS.md`, `docs/agent/PYTHON_REPO_STANDARDS.md`, and `docs/agent/SCRIPTS_REPO_STANDARDS.md`.
- Do not modify `modules/resource_coordinator/**`, `modules/agent_sync/**`, or `modules/vm_lab/**` from this module's work.
- Do not invoke real elevated installation, Hyper-V VM mutations, or local LLM inference during automated tests.
- Keep pytest temp roots under `modules/privileged_execution/.pytest_tmp_root/`.
- Never log, persist, or accept guest credentials from agent CLI requests.
