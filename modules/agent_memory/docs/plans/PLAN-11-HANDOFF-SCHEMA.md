# agent_memory Handoff Schema and Acknowledgment Support — Revised Implementation Plan

> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Standardize handoff notes and acknowledgment artifacts so heterogeneous coding agents can parse current state reliably before continuing work.

**Architecture:** `agent_memory` owns handoff payload schemas, rendering, parsing, validation, and note creation helpers. `agent_sync` later owns orchestration/enforcement. Handoff notes use V2 frontmatter for routing plus a marked machine-readable JSON block and concise Markdown narrative body.

**Recommended order:** Implement this plan after PLAN-8 and before PLAN-9. Context retrieval should understand structured handoff payloads instead of treating handoffs as opaque text.

**Prerequisites:** PLAN-5 and PLAN-6 complete. PLAN-7 recommended. PLAN-8 recommended.

**Working directory:** `/home/mcarls/scripts/modules/agent_memory/`

---

## File Map

| File | Responsibility |
|---|---|
| `agent_memory/handoff.py` | Handoff dataclasses, render/parse/validate helpers |
| `agent_memory/store.py` | Helper for creating handoff and ACK notes |
| `agent_memory/frontmatter.py` | V2 metadata compatibility if new handoff fields are frontmatter-exposed |
| `agent_memory/cli.py` | Optional handoff validate/render commands |
| `tests/handoff_test.py` | Handoff schema tests |
| `tests/store_test.py` | Store helper tests |
| `tests/cli_test.py` | Optional CLI tests |
| `docs/PROJECT_STATUS.md` | Status update |
| `pyproject.toml` | Version bump |
| `agent_memory/__init__.py` | Version bump |

---

## Handoff Frontmatter Requirements

Handoff notes should remain normal V2 notes, but include routing metadata in frontmatter when available:

```yaml
schema_version: 2
kind: handoff
project: agent-memory
status: active
layer: working
source_agent: claude-code
session_id: 20260531T120000Z_claude
handoff_id: 20260531T120000Z_handoff_abcd1234
task_id: agent-memory-plan-11
handoff_type: transfer
target_agent: codex
review_required: false
```

If adding `handoff_id`, `task_id`, `handoff_type`, or `target_agent` to frontmatter, add them as V2 optional fields in the implementation even if PLAN-5 did not initially include them.

---

## Handoff Body Format

Use a marker before the JSON block so parsers do not confuse arbitrary JSON examples with the handoff payload:

```markdown
<!-- agent_memory:handoff:v1 -->
```json
{
    "schema_version": 1,
    "artifact_type": "agent_memory_handoff",
    "handoff_id": "20260531T120000Z_handoff_abcd1234",
    "task_id": "agent-memory-plan-11",
    "from_agent": "claude-code",
    "to_agent": "codex",
    "project": "agent-memory",
    "goal": "Implement structured handoff schema support.",
    "current_status": "Plan ready; implementation not started.",
    "repo_path": "/home/mcarls/scripts/modules/agent_memory",
    "worktree_path": null,
    "branch": "main",
    "base_commit": null,
    "current_commit": null,
    "dirty_state": "unknown",
    "completed_steps": [],
    "pending_steps": [],
    "changed_files": [],
    "files_to_avoid": [],
    "commands_run": [],
    "test_results": [],
    "known_blockers": [],
    "decisions": [],
    "assumptions": [],
    "risks": [],
    "requested_next_action": "Start implementation from Task 1.",
    "validation_status": "not_run",
    "confidence": 0.9,
    "created_at": "2026-05-31T12:00:00Z"
}
```

## Narrative Summary

Human-readable summary for the receiving agent.
```

The actual Markdown file can include normal prose after the JSON block.

---

## Target Handoff Payload Fields

Required fields:

```text
schema_version
artifact_type
handoff_id
task_id
from_agent
project
goal
current_status
completed_steps
pending_steps
changed_files
known_blockers
requested_next_action
confidence
created_at
```

Recommended optional fields:

```text
to_agent
repo_path
worktree_path
branch
base_commit
current_commit
dirty_state
files_to_avoid
commands_run
test_results
decisions
assumptions
risks
validation_status
```

Structured object recommendations:

```json
{
    "path": "agent_memory/store.py",
    "status": "modified",
    "summary": "Added create_handoff_note helper.",
    "risk": "medium"
}
```

```json
{
    "command": "/home/mcarls/scripts/.venv/bin/python -m pytest tests/handoff_test.py -v",
    "cwd": "/home/mcarls/scripts/modules/agent_memory",
    "result": "passed",
    "summary": "12 tests passed."
}
```

```json
{
    "description": "Index schema migration may be stale in existing user indexes.",
    "severity": "medium",
    "mitigation": "Run agent-memory index rebuild after implementation."
}
```

---

## ACK Body Format

ACK artifacts should reference the original handoff ID.

```markdown
<!-- agent_memory:handoff_ack:v1 -->
```json
{
    "schema_version": 1,
    "artifact_type": "agent_memory_handoff_ack",
    "ack_id": "20260531T121500Z_ack_beef1234",
    "handoff_id": "20260531T120000Z_handoff_abcd1234",
    "task_id": "agent-memory-plan-11",
    "agent": "codex",
    "received_at": "2026-05-31T12:15:00Z",
    "understood_goal": "Implement structured handoff schema support.",
    "understood_constraints": [
        "Do not implement agent_sync orchestration in agent_memory."
    ],
    "planned_first_action": "Create agent_memory/handoff.py dataclasses and tests.",
    "questions": [],
    "will_not_touch": [
        "agent_sync orchestration code"
    ],
    "confidence": 0.88
}
```
```

ACK notes can use `kind: handoff` or a future dedicated kind only if taxonomy is updated. For this plan, prefer `kind: handoff` with `handoff_type: ack` in frontmatter.

---

## Task 1: Define handoff dataclasses

**Files:**
- Create: `agent_memory/handoff.py`
- Create: `tests/handoff_test.py`

- [ ] Add `HandoffPayload` dataclass with required and optional fields.
- [ ] Add nested dataclasses where useful: `ChangedFile`, `CommandResult`, `RiskItem`, `TestResult`.
- [ ] Add `HandoffAck` dataclass.
- [ ] Add constants for artifact types and marker comments.
- [ ] Validate field types and required fields.
- [ ] Validate `confidence` range.
- [ ] Add tests for valid payloads, missing fields, malformed JSON, wrong artifact type, and readable Markdown body.

---

## Task 2: Add renderer/parser helpers

**Files:**
- Modify: `agent_memory/handoff.py`
- Modify: `tests/handoff_test.py`

- [ ] Add `render_handoff(payload, narrative)`.
- [ ] Add `parse_handoff_body(markdown)`.
- [ ] Add `render_handoff_ack(ack, narrative=None)`.
- [ ] Add `parse_handoff_ack_body(markdown)`.
- [ ] Require marker comments before parsing machine-readable blocks.
- [ ] Ensure arbitrary unrelated JSON blocks do not parse as handoff payloads.
- [ ] Add roundtrip tests.

---

## Task 3: Add store helpers

**Files:**
- Modify: `agent_memory/store.py`
- Modify: `tests/store_test.py`

- [ ] Add `create_handoff_note()` or equivalent helper.
- [ ] Add `create_handoff_ack_note()` or equivalent helper if useful.
- [ ] Ensure handoff notes require explicit project.
- [ ] Store routing fields in frontmatter when available: `handoff_id`, `task_id`, `handoff_type`, `source_agent`, `target_agent`, `session_id`.
- [ ] Store full payload in Markdown body using standard rendering.
- [ ] Add tests that handoff notes are searchable, parseable, and validate correctly.

---

## Task 4: Add acknowledgment support without orchestration enforcement

**Files:**
- Modify: `agent_memory/handoff.py`
- Modify: `tests/handoff_test.py`
- Maybe modify: `agent_memory/store.py`
- Maybe modify: `tests/store_test.py`

- [ ] Define ACK fields: `ack_id`, `handoff_id`, `task_id`, `agent`, `received_at`, `understood_goal`, `understood_constraints`, `planned_first_action`, `questions`, `will_not_touch`, `confidence`.
- [ ] Validate ACK references a handoff ID.
- [ ] Keep enforcement out of `agent_memory`.
- [ ] Document that `agent_sync` will require ACK before edits later.

---

## Task 5: Optional CLI support

**Files:**
- Modify only if useful: `agent_memory/cli.py`
- Modify only if useful: `tests/cli_test.py`

- [ ] Add `agent-memory handoff validate` if useful.
- [ ] Recommended flags: `-r/--root`, `-p/--project`, `-f/--file`, `-j/--json`, `-v/--verbose`.
- [ ] Avoid duplicating future `agent_sync` orchestration commands.
- [ ] Ensure every new flag has short and long forms.

---

## Task 6: Update docs and version

**Files:**
- Modify: `docs/PROJECT_STATUS.md`
- Modify: `pyproject.toml`
- Modify: `agent_memory/__init__.py`

- [ ] Document the handoff schema and ACK responsibility split.
- [ ] Document that PLAN-11 should be implemented before PLAN-9.
- [ ] Bump MINOR version for new helper/API behavior.

---

## Tests to Add

- [ ] Handoff payload render/parse roundtrip.
- [ ] ACK payload render/parse roundtrip.
- [ ] Missing marker comment does not parse arbitrary JSON.
- [ ] Missing required fields produce validation issues.
- [ ] `confidence` outside 0.0-1.0 fails validation.
- [ ] `create_handoff_note()` requires project.
- [ ] Handoff notes are searchable by task ID, handoff ID, changed file path, and requested next action.
- [ ] ACK references the correct handoff ID.

---

## Validation

```bash
cd /home/mcarls/scripts/modules/agent_memory && /home/mcarls/scripts/.venv/bin/python -m pytest tests/ -v --tb=short
```

```bash
cd /home/mcarls/scripts/modules/agent_memory && /home/mcarls/scripts/.venv/bin/python -m ruff check agent_memory tests
```

```bash
cd /home/mcarls/scripts/modules/agent_memory && /home/mcarls/scripts/.venv/bin/python -m ruff format --check agent_memory tests
```

---

## Definition of Done

- [ ] Handoff notes have strict machine-readable marked JSON blocks.
- [ ] Handoff notes remain human-readable Markdown.
- [ ] Coding-agent handoff state includes repo/worktree/branch/commit/dirty-state fields.
- [ ] Store helpers create valid handoff and ACK notes.
- [ ] ACK shape references the source handoff ID.
- [ ] `agent_memory` does not implement `agent_sync` orchestration enforcement.

---

## Risks, Edge Cases, and Compatibility Notes

- Do not parse arbitrary JSON code examples as handoff payloads; require marker comments.
- Do not require Git metadata fields to be present on systems where Git is unavailable; allow `null` or `unknown`.
- Do not put all large command output into handoff payloads. Store summaries and references, not megabytes of logs.
- Keep schema version inside the handoff payload separate from frontmatter `schema_version`.
- `agent_sync` should later enforce ACK-before-edit; this plan only defines artifacts.
