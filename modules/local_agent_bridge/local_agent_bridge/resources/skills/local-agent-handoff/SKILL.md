---
name: local-agent-handoff
description: Use when coordinating repository work in Codex or Antigravity and a bounded exploration, review, draft, or implementation task can be delegated to the connected LM Studio worker through opencode_worker.
---

# Local agent handoff

Give the local worker a task it can complete and the coordinator can verify.
Use it proactively for suitable subtasks within the user's authorized work.
An instruction disabling delegation takes precedence. If you are the delegated
worker rather than the coordinator, carry out your assigned task directly.

## Choose and prepare the task

Good tasks include exploring a bounded set of files, a focused review, drafting
tests or documentation, and a small edit with clear acceptance criteria. Keep tiny
tasks in the coordinator when composing and reviewing a handoff would cost more
than completing them. Resolve requirements and architectural choices first.

Use the tools actually exposed by `opencode_worker`; this connection is not a native
Codex/agy subagent. On first use or reconnection, use `opencode_setup` and, if needed,
`opencode_context` with the absolute project `directory` to confirm readiness, the
local provider/model and available agents. Reuse confirmed facts within the task.
If the bridge is unavailable, continue locally or report the gap.
Installing tools or changing bridge settings is separate work.

Send the objective, absolute workspace, relevant context/instructions, allowed work,
exclusions, checks and expected result. Use the
[task envelope](references/task-envelope.md) when composing a handoff.
Give file paths and targeted context so the worker can inspect source directly;
do not copy the parent conversation or entire repository into the handoff.
For shared checkouts, let only one actor edit overlapping paths. Give parallel
writers separate worktrees before dispatch; a session is not filesystem isolation.

## Dispatch and continue

Select the intended local provider/model, explicit `directory` and verified worker
agent using the discovered tool schema. Never silently select a cloud fallback.
Use `local-worker` for authorized edits or `local-reviewer` for inspection without
edits or shell execution, after confirming the chosen agent exists. Both can use the bundled
[worker prompt](resources/local-worker.md); its presence in this folder does not
make it active in OpenCode.

Every `opencode_fire` call starts a distinct turn, including a follow-up in the
same session. Pass the explicit agent (`local-worker` or `local-reviewer`) on
every call. Record its returned `jobId`, `sessionId`, initiating `messageId`,
absolute `directory`, provider ID and model ID together; do not rely on a prior
turn's agent selection or default model.

For coding work, prefer `opencode_fire` followed by `opencode_check` or bounded
`opencode_wait` calls. Keep the returned `jobId`, `sessionId`, initiating
`messageId`, directory, provider/model and explicit agent. Observe by job ID so
an earlier session response cannot satisfy a new task.
Keep waits shorter than the client's tool timeout. Codex documents a 60-second
default; the pinned bridge's `opencode_run` defaults to a 600-second observation.
For a short synchronous run, set `maxDurationSeconds` explicitly within that budget.

Use a fresh session for an unrelated task and the original session for a related
follow-up. A follow-up is new work with a new job ID; a timeout resumes observation
of the existing job. Never resubmit work just because a wait expired.

For delayed responses, required input or failures, read
[results and recovery](references/results-and-recovery.md). Respect existing task
authority when handling requests for more access or a missing decision.

## Review the result

Fetch compact progress with `opencode_check` (`detailed: false`). Read full
conversation history only to investigate missing evidence or a failure.
Check the requested deliverable, supporting evidence, changed paths and reported
validation. Inspect relevant source/diffs and run appropriate focused checks before
integration. A completed tool response does not establish that the work is correct.

If the worker cannot make progress, narrow the task or finish it locally. Preserve
its useful evidence and report unresolved work instead of repeating blind retries.
The coordinator remains responsible for integration and the final user response.
