# ADR-002: Phase 2 Verified Hook Contracts & Normalized Event Design

- **Status:** Accepted (Stage A Complete)
- **Date:** 2026-11-19
- **Module:** `modules/agent_continuity`
- **Branch / Worktree:** `feature/agent-continuity-m2` (`../scripts-agent-continuity-m2`)
- **Base Commit:** `59e124f4ff570f30d53c36267e2871862b690e42` (descends from M1 `ab9195acbfe0093e6a6683a723495b0347b7c718`)

---

## 1. Verified Provider Hook Contracts (Stage A)

### 1.1 Codex CLI (`codex-cli 0.170.0`, Windows)
- **Feature state:** `codex features list` reports `hooks` is `stable` (`true`).
- **Configuration file:** `<codex_home>/hooks.json` (user-level `~/.codex/hooks.json`). Existing `~/.codex/config.toml` (`notify`) is separate and must be preserved untouched.
- **Compiled event names & fields inspected in `codex.exe`:**
  - Events: `SessionStart` (with `source`: `startup | resume | clear | fork`), `UserPromptSubmit`, `Stop`, `SessionEnd` (plus `PreToolUse`, `PostToolUse`, `PreCompact`, `PostCompact`, `SubagentStart`, `SubagentStop`, `PreModelRequest`, `PostModelRequest`).
  - Common/event fields: `session_id`, `hook_event_name`, `cwd`, `transcript_path`, `prompt` (on `UserPromptSubmit`), `source` (on `SessionStart`).
  - Windows handler config supports `commandWindows` alongside `command`, plus `timeout`.
- **Trust behavior:** Codex tracks hook/plugin trust (`plugin contents changed; hook approval required`). Hook shims must keep a stable command invocation (`agents hook-shim -p codex`) and never self-modify.
- **Fail-open stdout contract:** Return `{}` on stdout and exit `0`.

### 1.2 Antigravity CLI (`agy`)
- **Windows (`1.5.12`):** Documented in `~/.gemini/antigravity-cli/builtin/skills/agy-customizations/docs/hooks.md`:
  - Events: `SessionStart`, `PreInvocation`, `PostInvocation`, `Stop`, `PreToolUse`, `PostToolUse`.
  - Common stdin camelCase JSON: `conversationId`, `workspacePaths`, `transcriptPath`, `artifactDirectoryPath`, `modelName`, `lastUserInput`, `hookEventName`, `cwd`.
  - `PreInvocation` adds `invocationNum`, `initialNumSteps`.
  - `Stop` adds `executionNum`, `terminationReason`, `error`, `fullyIdle`, `continuationActive`.
- **WSL2 Ubuntu (`1.2.11`):** Diffing `1.2.11` `hooks.md` against `1.5.12` `hooks.md` revealed two critical version differences:
  1. `SessionStart` is **not documented/supported** in `1.2.11`.
  2. `lastUserInput`, `hookEventName`, and `cwd` are **absent** from `1.2.11`'s documented common stdin fields (only `workspacePaths`, `transcriptPath`, `artifactDirectoryPath`, `modelName` are listed, with `conversationId` if emitted).
- **Design consequence:**
  - `PreInvocation` (not `SessionStart`) is the primary cross-version hook for observing both new and resumed AGY sessions.
  - The AGY hook installer omits `SessionStart` when targeting older/WSL2 `1.2.x` versions or accepts an explicit `--include-session-start` option, while `AgyAdapter.normalize_hook_event()` handles missing `lastUserInput` / `hookEventName` / `cwd` gracefully.
  - `PreToolUse` is **never** installed for telemetry because its stdout gates tool execution (`decision: allow|deny|ask`).
  - Safe stdout for `SessionStart`, `PreInvocation`, `PostInvocation`, and `Stop` is `{}` (exit `0`).

---

## 2. Normalized Hook Event & Marker Decisions

1. **Normalized event types:** `session.created`, `session.observed`, `turn.submitted`, `turn.completed`, `session.ended`.
2. **Durable persistence:** Hook shims emit `EventEnvelope` with `event_type = "hook.event"` into `<home_dir>/events/<environment_id>/` via `append_event()`. No SQLite migrations, no git subprocesses, no full transcript reads, and no raw prompt storage occur in the hook hot path.
3. **Marker grammar:**
   - Canonical: `Workflow-ID: <wf_id_or_slug>` (standalone line, outside fenced code blocks, blockquotes, and inline code).
   - Legacy alias: `[wf:<wf_id_or_slug>]` (standalone/non-fenced).
   - Multiple distinct markers in a single prompt trigger `conflict=True` rather than silent selection.
4. **Session repurposing & precedence:**
   - Manual `confirmed` associations take precedence over hook-inferred `strong` associations. If a hook observes a marker for a different workflow on a `confirmed` session, a `conflict` association is recorded without overwriting the manual confirmation.
   - If a session has only a `strong` (hook-derived) association and a subsequent turn carries a valid marker for a different workflow, the prior `strong` association is `superseded` cleanly and the new workflow becomes active from that turn onward.
   - Untagged turns inherit the active workflow **only** when the session has a single unambiguous active (`confirmed` or `strong`) association and zero active conflicts.
