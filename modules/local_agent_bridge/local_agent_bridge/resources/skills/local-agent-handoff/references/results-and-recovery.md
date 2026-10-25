# Results and recovery

Preserve returned identifiers and inspect structured state and errors. The MCP
`content` text is useful for reading, but prose alone is not a completion signal.

| State | Next action |
| --- | --- |
| accepted / running | Observe the existing job |
| input_required | Inspect the actual question/permission request; answer within current authority or return the missing decision to the coordinator |
| completed | Review the result, evidence and diff; validate before integrating |
| failed | Read the error and identify what, if anything, was changed |
| cancelled | Confirm reported state; inspect partial work before any retry |
| unknown | Reconcile against the original session and directory; do not assume completion or resubmit |

Prefer `opencode_fire` to dispatch coding work. Record `jobId`, `sessionId`,
the initiating `messageId`, absolute `directory`, provider ID, model ID, and
explicit agent (`local-worker` or `local-reviewer`) immediately, in the current
task's notes/handoff if the work may outlive the conversation. Every follow-up
`opencode_fire` is a new turn: pass its explicit agent again and record its new
job/message IDs. A related follow-up can use the same session after the earlier
turn finishes, but the new turn needs explicit agent selection. `opencode_check`
and `opencode_wait` accept job identifiers.
Prefer `jobId` for exact turn correlation, using the same directory.
Poll with `opencode_check` and `detailed: false`, or wait with `timeoutSeconds: 30`
when that fits the client's tool timeout. Fetch detailed output when the result
or a blocker needs inspection. Avoid repeated full conversation reads.

If an observation times out, the remote job remains running; a wait that timed out
is not cancellation. Stopping a wait, losing a job handle, or an unknown/stale job ID
does not prove that the session stopped. Do not cancel or submit a duplicate job
from that evidence. Never resubmit a timed-out turn. Keep one active turn per session.

When a job ID is unknown or stale, inspect the original `sessionId` in the same
absolute `directory`. Check session state, latest messages and parts, the
recorded initiating `messageId` and submitted turn, plus pending permissions or
questions. Classify the original turn as active, completed, failed, or uncertain.
Compaction can invalidate a job lookup while the original session remains active
or later completes; reconcile before acting. A session becoming idle or showing
a later completed message does not prove that the initiating turn completed.
Match completion to the recorded message/turn. If the available MCP interface
cannot establish that match, mark it ambiguous and ask the coordinator to review.
Do not infer completion, retry by creating another job, or abort an active session
merely because the job lookup is unknown.

The pinned opencode-mcp 3.0.0 interface owns job polling outside this package.
The module does not patch that installed dependency. If its session/message APIs
cannot expose enough turn evidence, use this manual reconciliation path and
surface uncertainty; do not claim automated recovery.

For `input_required`, use `opencode_job_input` or the exposed permission/question
tools to inspect and answer the actual request. Check pending permissions and
questions during stale-job reconciliation too. Existing task authorization must
cover the action. A new authority decision goes back to the user; do not silently
approve a broader scope or an `always` grant. To stop execution, use
`opencode_job_cancel`; stopping a wait or disconnecting is not reliable cancellation.
Cancellation aborts the job's OpenCode session and can stop other work in that
session. Keep one active turn per session; inspect other activity before cancelling.

Example: after an initial call returns a job ID and `running`, observe that job
instead of repeating the original coding request. If it completes, inspect the
changed paths and checks. If it requests access outside the allowed paths, return
that request to the coordinator rather than expanding scope automatically.

Before integration, independently inspect the actual authorized changed paths,
diffs or file hashes against a baseline captured before dispatch, and focused
test output. Treat `session.summary.files = 0` as untrustworthy: a zero summary
does not disprove edits. A diff alone also does not prove this job made it. Require
an exclusive disposable workspace/worktree or another credible baseline and
ownership record before attributing changes to the turn. Verify every changed
path is allowed, then run the focused checks yourself. A permitted edit with a
matching baseline diff and passing focused tests can be accepted after review;
an empty worktree diff is no change evidence and must not be reported as a landed
edit.

Before integration, confirm:

- The result answers the requested task and cites inspectable evidence.
- Applied changes are distinguished from a proposed patch.
- Changed files are within scope; unrelated work remains intact.
- Claimed test output is available, and missing validation is stated.
- The coordinator's focused checks support the final conclusion.

If the worker's context is insufficient, provide a specific missing file/fact in
the existing session after the earlier turn finishes, with a new `opencode_fire`
call using its `sessionId` and an explicit `local-worker` or `local-reviewer`
agent. Save the new job/message IDs and observe that job, not the earlier
completed one. A same-session follow-up does not inherit the previous agent.
If the approach repeatedly fails, finish locally and retain
useful findings; do not automatically switch to a cloud model.

Reference: [OpenCode MCP 3.0.0 tool contracts](https://github.com/AlaeddineMessadi/opencode-mcp/blob/v3.0.0/docs/tools.md).
See also [job persistence and server lifecycle](https://github.com/AlaeddineMessadi/opencode-mcp/blob/v3.0.0/docs/architecture.md).
