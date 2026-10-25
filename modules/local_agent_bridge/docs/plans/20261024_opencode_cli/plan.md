# OpenCode CLI Attachment and Status Implementation Plan

> **For agentic workers:** This plan is executed directly by Codex under the user's explicit no-delegation instruction.

**Goal:** Add read-only OpenCode health commands and a safe interactive attach command to `local-agent`.

**Architecture:** Add endpoint validation/resolution, `/global/health` classification, status rendering, and TUI launch to `commands.py`, keeping runtime/model lifecycle code untouched. Cover behavior in the existing commands test module and update package version, README, and module handoff.

**Tech Stack:** Python 3.11+, argparse, urllib, subprocess, pytest.

**Spec:** User request, “Local Agent Bridge — OpenCode TUI Attachment and Server Status Commands” (2026-10-24).

## Global Constraints

- Preserve existing `setup`, `model`, and `run` command behavior.
- Never start/restart OpenCode, load models, mutate sessions, or modify runtime configuration.
- Do not capture the interactive TUI's standard streams or build shell command strings.
- Use exit code 0 for healthy, 1 for unavailable/unhealthy, and 2 for local argument/configuration errors.
- Do not include credentials in output; avoid forwarding local OpenCode credentials to remote endpoints.
- Keep all changes inside `modules/local_agent_bridge/`; do not dispatch to agents or OpenCode.

## Review Focus

- Malformed, unhealthy, timed out, unauthorized, or HTTP-error health responses return useful safe diagnostics and nonzero status.
- Ambiguous URL/port values and invalid endpoint/session inputs fail before network or process activity.
- Windows `.cmd` launch and arguments containing spaces remain argument-vector based with inherited streams.
- Attach preflight failures never start or reconfigure the runtime.
- Existing setup/model/run parsers and behaviors remain compatible.

---

### Task 1: Status and endpoint resolution

**Files:**
- Modify: `local_agent_bridge/commands.py`
- Test: `tests/commands_test.py`

**Interfaces:** Add `resolve_opencode_url(args)`, a health probe returning stable structured fields, and `opencode status|ping` dispatch.

- [x] Write tests for endpoint precedence, response classification, JSON/text output, and no runtime side effects.
- [x] Run targeted tests to observe expected failures.
- [x] Implement bounded `/global/health` requests and safe diagnostics.
- [x] Run targeted tests and refine.

### Task 2: Interactive attach

**Files:**
- Modify: `local_agent_bridge/commands.py`
- Test: `tests/commands_test.py`

**Interfaces:** Add `opencode attach` with optional session and directory, preflight health/executable checks, and inherited-stream child execution.

- [x] Write tests for argument vectors, inherited streams, remote credential filtering, errors, and exit status.
- [x] Run targeted tests to observe expected failures.
- [x] Implement attach without shell command construction or lifecycle side effects.
- [x] Run targeted tests and refine.

### Task 3: Documentation, compatibility, and delivery

**Files:**
- Modify: `README.md`, `local_agent_bridge/__init__.py`, `pyproject.toml`, `docs/HANDOFF.md`

- [x] Document options, resolution, session IDs, interactive semantics, and offline troubleshooting.
- [x] Bump compatible feature version to 3.2.0.
- [x] Run focused pytest, lint, and CLI regression smokes; review the changed paths and diff.
- [x] Attempt live status/attach only if a suitable authorized OpenCode server/session is already available; never start one for acceptance. Live status was blocked by sandbox socket policy, and no session ID was supplied for live TUI attachment.
- [ ] Commit and push the feature branch only.
