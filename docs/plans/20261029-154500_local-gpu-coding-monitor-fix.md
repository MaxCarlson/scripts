# Local GPU Coding and Monitor Scope Fix Plan

> **For agentic workers:** The coordinator executes this plan inline; no worker dispatch is authorized for implementation.

**Goal:** Make bounded local-worker edits more action-oriented and make LLM Monitor's selected OpenCode project scope explicit, then verify a fresh local coding session end to end.

**Architecture:** Keep OpenCode/LM Studio configuration and runtime untouched until observed evidence identifies the exact request fields and supported reasoning controls. Update the canonical worker prompt and the recorder's sanitized scope diagnostics; preserve provider/session identity and the user's existing telemetry database.

**Tech Stack:** Python 3.11+, pytest, OpenCode 1.19.3 MCP, LM Studio, SQLite telemetry.

**Spec:** User request, “Local GPU Agent — Diagnose and Fix Coding Failures and Monitoring Gaps” (2026-10-29).

## Global Constraints

- Preserve the existing Runmux pilot and setup-status worktrees.
- Do not modify the original recorder or telemetry database.
- Keep test jobs bounded and use one significant inference setting per trial.
- No prompt/source/tool-output logging or unrelated global setting changes.
- Commit and push the isolated feature branch when implementation and verification finish; do not merge.

## Review Focus

- Recorder discovery is project scoped: print endpoint and project scope, and redact URL userinfo/path/query.
- `--all` with no `--project-directory` means server-default project, not every project on the OpenCode server.
- Bounded coding tasks need an early-edit instruction without changing review or delegation permissions.
- Runtime model request settings are unknown until evidenced; do not infer they were sent from config alone.

### Task 1: Recorder project-scope diagnostics

**Files:** `modules/llm_monitor/llm_monitor/cli.py`, `modules/llm_monitor/tests/cli_test.py`, `modules/llm_monitor/README.md`, `modules/llm_monitor/pyproject.toml`.

- [x] Add a failing CLI test for an `--all --project-directory` recorder invocation; assert the project and sanitized server endpoint are visible and endpoint userinfo/query are absent.
- [x] Run the focused test and confirm the expected assertion fails.
- [x] Print `server`, `scope`, and explicit project path in JSON and text progress; clarify CLI help and README that `--all` is scoped to the selected/default project.
- [x] Bump `llm-monitor` PATCH version to 0.5.1.
- [x] Run focused CLI tests (17 CLI/history tests passed).

### Task 2: Bounded worker action guidance

**Files:** `modules/local_agent_bridge/local_agent_bridge/resources/skills/local-agent-handoff/resources/local-worker.md`, `modules/local_agent_bridge/tests/resources_test.py`, `modules/local_agent_bridge/pyproject.toml`.

- [x] Add a failing prompt-resource test requiring a first-edit milestone and bounded reconnaissance for small coding tasks.
- [x] Run the focused test and confirm it fails on the missing guidance.
- [x] Update the canonical prompt without changing roles, permissions, or delegation boundaries.
- [x] Bump `local-agent-bridge` PATCH version to 3.5.1.
- [x] Run focused resource tests (5 passed).

### Task 3: Controlled live validation

- [x] Verify LM Studio model identity/load/context and OpenCode URL/project directory without changing model-load state.
- [x] Verify LLM Monitor discovers the target project before dispatch; record into a new isolated database.
- [x] Dispatch one fresh MCP `local-worker` session to a disposable worktree, requiring an early edit to a tiny Python file.
- [x] Inspect OpenCode usage/finish/tool events and independently inspect and validate the exact file change.
- [x] Verify the isolated monitor database contains the new session and its inference/tool events; report exact coverage.

### Task 4: Integration and handoff

- [ ] Review the diff, rerun focused tests, confirm both source worktrees are unchanged, and inspect final status.
- [ ] Commit and push this feature branch only; leave it unmerged.
- [ ] Record confirmed causes, settings, evidence, uncertainties, and next experiment in the final handoff.
