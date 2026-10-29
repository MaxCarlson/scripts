# Live reasoning diagnostics compatibility report: OpenCode 1.19.3

**Date:** 2026-10-29
**Scope:** Read-only runtime checks of the existing `http://127.0.0.1:4096` server and the completed Runmux pilot session authorized by the user. No inference, configuration change, service restart, or database write was performed.

## Installed API contract

- `opencode --version` returned `1.19.3`.
- `GET /global/health` returned HTTP 200 with `healthy` and `version`; the version was `1.19.3`.
- `GET /doc` returned HTTP 200. Its schema defines `GET /event` with a `directory` query parameter and a `text/event-stream` body of `Event` records. Each global event is wrapped as `{directory, payload}`. `GET /global/event` has no project query parameter, so the observer uses project-scoped `/event`.
- The runtime schema defines `message.part.delta` with `sessionID`, `messageID`, `partID`, `field`, and `delta`; `message.part.updated` includes a typed `part` with its own session/message/part identities; `message.updated` carries assistant `info`; and `session.status` carries a status object such as `{type: "busy"}`. The implementation uses these fields and the event JSON `id` for duplicate suppression.
- The observer sends `directory` in the query string, optionally uses Basic authentication from `OPENCODE_SERVER_USERNAME` and `OPENCODE_SERVER_PASSWORD`, and filters the selected session before accumulating any content.

## Completed-session observation

The authorized bounded JSON observation used the exact pilot project and session. The SSE connection succeeded, returned one unscoped frame, and returned zero events for the selected session during the observation window. The stream later had one reconnection gap, so coverage was marked incomplete. Existing completed message data remained available and the snapshot classified this session as `completion_only`.

The supplied associated message ID `msg_187f77d790011494687b8291bf` is a **user** message. It was verified with a read-only message-detail GET; its text was not printed. The session's latest assistant message was `msg_187f7a7660017yzCCeUDc0S4SH`, with `finish=length`, 16,384 reported reasoning tokens, and zero reported output tokens. The exact OpenCode provider configuration reported model `qwen38_23GB`, context limit 98,304, output limit 8,192, and an empty variants map. The latest assistant message recorded variant `medium`.

These observations demonstrate completed-message reconciliation and expose a reported difference between the assistant's reasoning usage and the configured output limit. The comparison is labeled inferred and does not establish a model defect or prove the outbound LM Studio parameters. No request-parameter capture was provided. Live LM Studio capability inventory was not queried; the addendum's `off`/`on` capability report remains user-supplied pilot evidence, not a live inventory observation.

The user's supplied telemetry path `%LOCALAPPDATA%\llm-monitor\runmux-pilot-v6.sqlite3` did not exist in this environment. It was not created or modified. OpenCode's available bounded history reported complete coverage for its message window and showed no successful file edit before the observed completion.

## Runtime classification and limitation

For this completed session, the snapshot classification is `completion_only`: stored completion metadata is available while no session-matched incremental event was observed. **Live reasoning streaming remains unverified.** A completed session cannot prove whether reasoning deltas are emitted during active inference. The deterministic SSE fixtures cover reasoning deltas, full-part updates, delta-before-update ordering, duplicate updates, filtering, disconnects, malformed frames, and size limits. A future controlled active session is needed to verify live streaming without initiating a new model request here.
