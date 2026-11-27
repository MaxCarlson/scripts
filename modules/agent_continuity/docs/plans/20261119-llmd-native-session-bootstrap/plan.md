# Native Session Bootstrap and Resume

## Goal

For every new Codex or AGY dispatcher launch, create one durable native session, capture its ID from that invocation's structured output, persist the exact slot association, then resume the same ID interactively. Keep the existing event spool, SQLite projection, dispatcher CLI, provider adapters, and `terminal_launcher` boundary.

## Decisions

- Codex: `codex exec --json --sandbox read-only <initialization message>`; accept one `thread.started.thread_id` only after a successful `turn.completed` and zero exit status.
- AGY: `agy --print <initialization message> --output-format json --sandbox`; accept `conversation_id` only when the result status is `SUCCESS` and the process exits zero.
- Resume only after a durable activation and launch-resolution event is written.
- Persist a bootstrap-attempt observation before invoking a provider. Never automatically retry an interrupted or ambiguous attempt.
- Keep the fixed bootstrap message out of dispatcher event data and never persist provider stdout/stderr.
- Preserve previous current selection on bootstrap/capture/persistence failure; preserve a captured ID in durable process-observation events for manual recovery.

## Validation

- Mock provider output and process results for both strategies, failure recovery, concurrency, rebuild, and exact resume arguments.
- Run the full `agent_continuity` package suite, relevant scripts-help/terminal-lifecycle regressions, Ruff, compile checks, packaging and CLI smoke.
- Only perform at most one bounded live bootstrap per provider if credentials and sandbox execution permit; do not send project assignments or install global hooks.
