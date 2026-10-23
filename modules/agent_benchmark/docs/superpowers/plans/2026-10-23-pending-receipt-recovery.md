# Pending Receipt Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconcile and, when needed, terminate a pending worker before a new benchmark run; never start while prior execution may still be active.

**Architecture:** Add asynchronous recovery around the existing receipt, journal, OpenCode bridge, and lifecycle confirmation. All execution entry points attempt recovery before dispatch. Confirmed no-submission or terminated-session evidence removes only the receipt and preserves evidence/workspaces; unresolved state remains blocked without a bypass.

**Tech Stack:** Python 3.12, argparse, asyncio, httpx/OpenCode bridge, existing JSON receipt and lifecycle journal.

**Spec:** `docs/superpowers/specs/2026-10-23-pending-receipt-recovery-design.md`

## Global Constraints

- Preserve the existing command lock and token-checked receipt release.
- Never clear `pending.json` or dispatch while a prior worker may still be active.
- Do not treat cancellation acknowledgement as termination proof.
- Preserve prior unrelated changes and user-owned untracked artifacts.

## Review Focus

- A worker accepted before its response was lost: require fresh correlated terminal state or keep the pending receipt and stop.
- A pending direct CLI worker with only a stored PID: refuse to signal it because process-start identity and process-tree ownership were not persisted.
- Prepared session belongs to another directory/project: refuse automatic release.
- Session history is nonempty or status is active/unknown: keep pending state.
- Session-abort acknowledgement without fresh terminal evidence: keep the receipt and stop.
- Concurrent run starts during recovery: serialize with the existing OS lock.

---

### Task 1: Reconcile pending state safely

**Files:**
- Modify: `agent_benchmark/bridge.py`
- Modify: `agent_benchmark/runner.py`
- Modify: `agent_benchmark/state.py` only if needed for token-checked release

**Interfaces:**
- Produce an async pending-recovery function that checks the current receipt under the command lock and returns only after receipt removal is supported by safe evidence.
- Reuse `confirm_termination` for complete worker handles, then fall back to the exact session-abort endpoint if needed.
- Validate prepared-session identity and the exact stored prompt; require empty/idle evidence or a matching terminal turn.

- [x] Persist fresh reconciliation evidence before releasing a confirmed receipt.
- [x] Preserve workspace and evidence after recovery; never call `cleanup_workspace` from startup recovery.
- [x] Keep receipt unchanged on mismatches, transport errors, active status, or inconclusive observations.

### Task 2: Wire safe recovery into execution commands

**Files:**
- Modify: `agent_benchmark/cli.py`
- Modify: `agent_benchmark/scheduler.py`
- Modify: `agent_benchmark/runner.py`
- Modify: `agent_benchmark/diagnostic.py`

**Interfaces:**
- Run automatic recovery before `run`, `experiment run`, and `smoke` can transition models or dispatch.
- Do not add a prompt or force-clear flag. Unresolved recovery keeps the receipt and stops with a specific diagnostic.

- [x] Ensure all dispatch entry points recover OpenCode work first; unsupported direct CLI receipts stop with an explicit identity diagnostic.
- [x] Keep the 100%-off runtime RAM percentage default and independent 4 GiB available-RAM floor.
- [x] Bump the agent-benchmark minor version and update user documentation.

### Task 3: Handoff and delivery

**Files:**
- Modify: `README.md`
- Modify: `docs/HANDOFF.md`
- Modify: this plan's status/checklist as work progresses

- [x] Record the recovery semantics, no-override behavior, worktree/branch, and validation limits.
- [x] Review the exact staged paths; preserve `integration-acceptance/` and `reports/`.
- [x] Stage and commit the completed benchmark branch, then merge it into local `src/scripts` `main` as explicitly requested.
