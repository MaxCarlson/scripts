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
| unknown | Reconcile with the session/job; do not assume completion or resubmit |

Prefer `opencode_fire` to dispatch coding work. Record `jobId`, `sessionId`,
`messageId` and `directory` immediately, in the current task's notes/handoff if
the work may outlive the conversation. `opencode_check` and `opencode_wait` accept
job identifiers. Prefer `jobId` for exact turn correlation, using the same directory.
Poll with `opencode_check` and `detailed: false`, or wait with `timeoutSeconds: 30`
when that fits the client's tool timeout. Fetch detailed output when the result
or a blocker needs inspection. Avoid repeated full conversation reads.

An observation timeout leaves
the remote job running; it is not cancellation. An expired/lost handle likewise
does not prove that the session stopped. Default job-handle retention is 24 hours;
expiration removes the handle without cancelling the OpenCode session. Use
`opencode_job_list`/`opencode_job_get` and session metadata to reconcile work.
After a handle expires, session observations do not restore exact job correlation;
inspect the submitted turn and changes before deciding what happened.

For `input_required`, use `opencode_job_input` or the exposed permission/question
tools to inspect and answer the actual request. Existing task authorization must
cover the action. A new authority decision goes back to the user; do not silently
approve a broader scope or an `always` grant. To stop execution, use
`opencode_job_cancel`; stopping a wait or disconnecting is not reliable cancellation.
Cancellation aborts the job's OpenCode session and can stop other work in that
session. Keep one active turn per session; inspect other activity before cancelling.

Example: after an initial call returns a job ID and `running`, observe that job
instead of repeating the original coding request. If it completes, inspect the
changed paths and checks. If it requests access outside the allowed paths, return
that request to the coordinator rather than expanding scope automatically.

Before integration, confirm:

- The result answers the requested task and cites inspectable evidence.
- Applied changes are distinguished from a proposed patch.
- Changed files are within scope; unrelated work remains intact.
- Claimed test output is available, and missing validation is stated.
- The coordinator's focused checks support the final conclusion.

If the worker's context is insufficient, provide a specific missing file/fact in
the existing session after the earlier turn finishes, with a new `opencode_fire`
call using its `sessionId`. Save
the new job/message IDs and observe that job, not the earlier completed one.
If the approach repeatedly fails, finish locally and retain
useful findings; do not automatically switch to a cloud model.

Reference: [OpenCode MCP 3.0.0 tool contracts](https://github.com/AlaeddineMessadi/opencode-mcp/blob/v3.0.0/docs/tools.md).
See also [job persistence and server lifecycle](https://github.com/AlaeddineMessadi/opencode-mcp/blob/v3.0.0/docs/architecture.md).
