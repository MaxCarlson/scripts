# Pending Receipt Recovery Design

## Intent

When an execution command finds a persisted pending-worker receipt, it should try to reconcile the prior attempt before refusing to start. This avoids leaving the user with a mysterious permanent blocker while preserving a deliberate stop when remote execution may still be active.

## Goals and limits

- Automatically release a receipt only when no submission occurred or fresh correlated evidence confirms termination.
- For an uncorrelated submission, inspect the exact prepared session, project, and workspace. Release only when repeated fresh reads show the session is still empty and idle.
- If recovery remains uncertain after supported cancellation and fresh observation, preserve the receipt and stop with a specific recovery diagnostic. Never bypass the block.
- Run recovery before any model transition or new dispatch for `run`, `experiment run`, and `smoke`.

## Non-goals

- Never delete remote sessions, trial evidence, or workspaces as part of startup recovery.
- Never kill or unload shared OpenCode/LM Studio processes.
- Do not provide a force-clear flag or continue without proof that the prior worker stopped.

## Approaches

- Blindly delete any receipt: rejected because a remote worker may still be active and writing to its workspace.
- Stop on every receipt: current behavior, but leaves users without an automatic recovery path.
- Reconcile first and safely abort the exact prior session when necessary: selected because it permits progress only after the earlier worker is confirmed finished.

## Behavior

With the benchmark command lock held, read the pending receipt and its lifecycle journal. Release it automatically when the journal proves dispatch never started or termination was already confirmed. If complete job/session/message IDs exist, request cancellation and require fresh correlated termination confirmation. If IDs are incomplete but a prepared-session binding exists, validate its exact session ID, workspace directory, and Git project ID. An empty history and idle status must remain unchanged through the full confirmation grace. If a turn exists, abort the exact benchmark-owned session through OpenCode's session-abort API, then require fresh matching-turn completion, idle session status, and no running tools. Repeat observations within the existing grace budget. Persist any new lifecycle evidence before release. Preserve all evidence and workspace files.

If these checks fail or are inconclusive, keep the receipt and stop before any model transition or new dispatch. Explain which evidence was missing and point to the preserved trial evidence. Do not ask the user to accept an unresolved worker risk.

Direct CLI workers (Codex/Gemini) are not safely recoverable from legacy receipts that record only a PID: process start identity and full process-tree ownership were not persisted. Detect those receipts explicitly and stop without signaling the PID. A future change can add durable process identity before dispatch and recover only with that stronger ownership evidence.

## Constraints

- Serialize recovery with benchmark commands using the existing OS command lock.
- Do not overwrite canonical scores or rewrite historical trial results.
- Package version follows repository CLI feature versioning.
