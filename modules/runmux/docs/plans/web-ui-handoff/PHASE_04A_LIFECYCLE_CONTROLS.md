# Runmux Web UI — Phase 4A: Authorized Process Lifecycle Controls

**Status:** Future separately assignable feature | **Priority:** P1 | **Backlog:** C02–C07, applicable S01–S12

## Objective

Add the **minimal safe** browser controls for stop/terminate, restart, and pause/resume *where supported by Runmux and the operating system*. The existing Web UI process tabs are only views; closing a tab remains view-only. Phase 1's browser mutation authorization model must be integrated first.

## Work to perform when assigned

1. Inspect `runmux` CLI/backend lifecycle operations and supervisor state transitions. Verify restart identity semantics (new run ID or retained record), Windows vs POSIX support, eligible/terminal/lost states, and per-run authorization.
2. Add only supported selected-run actions, with user-initiated confirmations naming **both run name and unique Run ID** for destructive operations.
3. Show pending, result, error and refreshed state. Prevent accidental repeated actions, stale run selection and two-browser-session races; server authorizes mutation independent of UI visibility.
4. Distinguish process pause/resume from Output **follow/pause display**. Never implement a lifecycle action by closing a browser tab or input WebSocket.
5. Preserve CLI, TUI, Web UI auth, terminal sessions and supervisor FIFO input-lock invariants.

## Validation and acceptance

Use disposable synthetic registries/processes only. Test direct unauthorized/wrong-origin requests; valid and invalid state transitions; already-exited/lost runs; concurrent clients; restart identity/tab reconciliation; stop and pause semantics per supported OS; and process survival when a view is closed. No silent state changes on GET, page restore or failure retry. Document unsupported actions rather than forging UI controls.

**Out of scope:** Bulk controls, registry deletion/cleanup, scheduling, modifying process environment, expanded logs (Phase 4B), telemetry and new permission tiers. Deliver code, focused tests, docs, pushed branch and security/validation summary; **do not merge**.
