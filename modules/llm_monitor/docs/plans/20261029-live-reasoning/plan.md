# Live Reasoning Diagnostics Implementation Plan

**Goal:** Add an opt-in, read-only OpenCode SSE observer with bounded live progress snapshots for one session.

**Architecture:** Keep transport, event normalization, part accumulation, diagnostics, and JSON snapshot construction in an independent `llm_monitor.live` module. Use the standard library and existing `OpenCodeClient` history/message APIs; do not change the recorder or telemetry schema. Add `live` CLI output in compact terminal or bounded JSON form, with raw reasoning gated by an explicit flag.

**Tech Stack:** Python 3.11+, `urllib`, deterministic pytest fixtures.

**Spec:** User request, “LLM Monitor — Live Reasoning Diagnostics Implementation”.

**Addendum:** User request, “Reasoning Configuration Provenance and Diagnostic Coverage”.

## Constraints

- Runtime verification targets installed OpenCode 1.19.3 and treats its `/doc` as authoritative.
- Do not start inference or alter the OpenCode server, other worktrees, Runmux, or telemetry databases.
- Raw reasoning is memory-only, bounded, redacted, and hidden unless explicitly requested.
- Current reasoning token count remains `null`; character counts are labeled as characters.
- A bounded observation reconciles stored state before and after its event window and labels coverage gaps.
- No automatic cancellation/restart and no LM Studio proxy.
- Bump the package minor version for the new CLI mode.

## Review Focus

- A delta received before its part update is retained and attached to the right reasoning/text part.
- A completed part snapshot replaces prior accumulated content instead of duplicating it.
- Malformed/oversized SSE frames are dropped with an incomplete-telemetry warning.
- Session and project filters prevent cross-session/project content leakage.
- A healthy stream without incremental content is not classified as a stall.
- Session-recorded variants never prove that the provider received a matching parameter.
- External request evidence is accepted only for exact session/message/creation timestamps and allowlisted fields.
- Token-limit comparisons retain source and confidence and do not imply a model defect.

## Tasks

1. Add deterministic tests and an SSE parser/transport for bounded frames, reconnect gaps, auth, and project headers.
2. Normalize OpenCode project/global event envelopes, filter exact session identity, and accumulate bounded text/reasoning/tool/completion state.
3. Reconcile stored messages/status and tool history around bounded observation windows; expose variant/config/provider/request provenance and advisory coverage diagnostics.
4. Add `live` CLI compact terminal/JSON modes, explicit raw-reasoning display, sanitized request-evidence correlation, deterministic 8K/16K fixtures, documentation, version bump, and an OpenCode 1.19.3 compatibility report.
5. Run focused and full module regression checks, inspect the final diff, commit, and push the isolated branch.
