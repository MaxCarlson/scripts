# OpenCode terminal-message semantics

Verified against the installed OpenCode version (1.19.3) and its version-tagged primary source, 2026-10-19:

- [prompt.ts, structured-output handling](https://github.com/anomalyco/opencode/blob/v1.19.3/packages/opencode/src/session/prompt.ts#L1217): after processing finishes, successful StructuredOutput is assigned to the assistant, the existing finish reason may remain tool-calls, and the loop exits. Non-null structured data therefore can coexist with tool-calls on a terminal step; that finish reason alone does not imply an intermediate step. This source does not establish that arbitrary structured data on an intermediate step is final.
- [StructuredOutput tool](https://github.com/anomalyco/opencode/blob/v1.19.3/packages/opencode/src/session/prompt.ts#L1484): the validated tool invokes the structured-output success callback.
- Installed opencode-mcp 3.0.0 jobs.js likewise handles structured terminal messages, but job cancellation sets cached cancelled immediately after an abort response. Cached jobs never prove termination.

The benchmark requires successful fresh session lookup with exact directory/ID, exactly one submitted user turn, correlated assistant history, idle session and terminal tool states. Multiple assistant steps with missing ordering timestamps fail closed. Normal final finish reasons require a completed timestamp. For tool-calls, additionally require non-null structured, requested json_schema and a completed StructuredOutput part in the same final assistant. Errors require a named error dict, idle state and no unfinished tools; aborted messages may lack completed timestamps. All ordinary malformed-data and observation failures remain unresolved.

These are source-checked offline rules, not live cancellation validation. No live session was observed during this integration. A raw API shape/version mismatch must preserve diagnostics/workspace and stop dispatch, not weaken cleanup proof. The role profiles and fixture directories are not an OS sandbox.
