# Read-only runtime discovery API

`agent_continuity.runtime_discovery` provides a typed, provider-independent observation for one exact native session. It is designed for LLMD list, doctor, activity and identity consumers, and for later checkpoint planning. It does not change registry state, launch providers, inspect terminal titles, or persist observations.

```python
from agent_continuity.runtime_discovery import RuntimeDiscovery, SessionKey

observer = RuntimeDiscovery()
observation = observer.observe(
    SessionKey(
        provider="codex",
        native_session_id="01a20ac0-9181-7993-bedc-6393a27e383d",
        environment_id="env_win_example",
    ),
    registry_association=True,
)
safe_payload = observation.to_dict()
```

The default observer is scoped to its local runtime. A WSL or remote observer must be constructed separately with explicit process and provider-store sources for that runtime. A target whose `runtime_kind` does not match the observer returns unavailable evidence without probing or starting another runtime.

## Independent dimensions

| Field | Meaning |
| --- | --- |
| `process_liveness` | `running` requires a current exact-session process match or a live known PID/creation identity. `exited` applies to a supplied known identity absent from a complete snapshot or replaced by a reused PID. `not_observed` means a complete snapshot had no exact match; it does not mean the provider session ended. `unknown` and `ambiguous` preserve gaps and duplicates. |
| `known_process_liveness` | Liveness of the optional PID plus creation-time identity supplied by a previous observation or receipt. |
| `process_session_match` | Whether process arguments or an exact managed association identifies this native session. Matching requires the provider's invocation syntax and the complete session ID. |
| `interactive_attachment` | `attached` is supported by a managed pane receipt or terminal-host ancestry; `detached` requires a complete ancestry ending under a recognized background host; otherwise it is `unknown`. This does not identify an exact Windows Terminal tab or geometry. |
| `management` | `managed` requires an exact managed receipt association; `unmanaged` requires a complete receipt lookup with no association; absent or incomplete receipt sources yield `unknown`; PID reuse that conflicts with a receipt yields `conflict`. |
| `availability` and component availability | Report whether process, provider-store and managed-receipt evidence was complete, partial or unavailable. No absent result from an incomplete source becomes a negative finding. |
| `confidence` and evidence | Each source has a capture time, stable evidence code and confidence. Process identities include PID and normalized creation time. Ancestry includes identities and image names, never full arguments. |
| Provider timestamps | Codex `threads.updated_at` and AGY `last_modified_time` / `last_user_input_time` are returned as provider activity metadata only. They never establish process liveness. |

## Sources and exact matching

- `CodexSessionStore` reads `~/.codex/state_5.sqlite` in SQLite read-only mode and queries `threads.id = ?`.
- `AgySessionStore` reads `~/.gemini/antigravity-cli/conversation_summaries.db` read-only and queries `conversation_summaries.conversation_id = ?`.
- These stores reuse the same native databases and activity fields as the existing Codex and AGY discovery adapters, but perform an exact-ID lookup instead of selecting the newest-N sessions.
- `PsutilProcessEnumerator` is an optional native process source. If `psutil` is unavailable or Windows denies access, it reports unavailable/partial evidence. The package does not add a `psutil` dependency.
- The Codex matcher requires `codex resume <exact-session-id>`; the AGY matcher requires `agy --conversation <exact-session-id>`. Executable recognition alone never establishes identity. Arguments are inspected in memory and omitted from observation objects, safe dictionaries, reprs and diagnostics.
- Provider activity, a registry association, an executable name, a window title, or a recent-session position alone cannot establish that a session is running.

An exact process match may still be returned when unrelated process entries are inaccessible; its positive evidence is retained and overall availability is partial. With no exact match, partial or unavailable process enumeration returns `unknown`. A complete snapshot with no match returns `not_observed`, never `inactive`.

## Optional Terminal Launcher receipts

`ManagedReceiptSource` and `ManagedPaneReference` are local protocols and dataclasses. The module does not import Terminal Launcher, so it works with the installed 0.1.x package or with no Terminal Launcher package. An integration can provide a receipt source when Terminal Launcher 0.2.0 is available and join its `launch_id` / `pane_id` to an exact LLMD provider-session association.

`managed_pane_reference_from_terminal_launcher_record()` accepts a 0.2.0 receipt by duck typing. Terminal Launcher records Windows creation times as FILETIME; `process_identity_from_windows_filetime()` converts them to the Unix-nanosecond scale used by `ProcessIdentity` and `psutil`. The adapter requires a positive spawn acknowledgment, PID and creation time. Callers remain responsible for selecting a receipt for the exact native session; the helper does not inspect registry schemas or infer associations.

## Consumer boundary

Agent Continuity owns the provider/runtime observation module and its collectors. A consumer passes the exact `SessionKey`; it may pass whether an exact registry association exists and a previously observed process identity. The runtime module only returns evidence. It does not mutate registry associations, write lifecycle events, interpret operator labels such as `IN USE`, or persist checkpoints.

LLMD list and doctor should render process state, attachment, management, provider activity, lifecycle and evidence availability as separate fields. When process enumeration is partial, show unknown rather than inactive. Future checkpoint consumers may store the returned exact identity and managed pane reference, but observed Windows Terminal tab order and exact pane geometry remain unavailable unless a supported managed receipt supplies them.

## Validation limits

Unit tests use injected process inventories and temporary provider SQLite databases. The default process enumerator is also smoke-tested on the current native host. A test harness that cannot enumerate the operator desktop must report that boundary as unavailable/partial; it must not infer inactivity or interact with unrelated processes. No provider launch, WSL startup, window closure, registry mutation or checkpoint persistence is part of this module.

Native Windows smoke (2026-11-27): `Get-CimInstance Win32_Process` raised a `CimException` in this execution context. Optional psutil 7.1.3 enumerated 723 records, with 172 inaccessible or raced entries, so the snapshot was correctly `partial`. The exact target session had provider-store activity evidence but no exact process match; its process liveness remained `unknown`.

Twelve observations per concurrency level measured process-store lookup plus enumeration: at 1 worker, p50 71.30 ms / p95 77.90 ms; at 5 workers, p50 344.00 ms / p95 462.48 ms; at 20 workers, p50 611.60 ms / p95 733.89 ms. These are per-call latencies under concurrent enumeration in this restricted host, not guarantees for an unrestricted desktop.

The observation exposes `identity_conflict` for PID/creation-time reuse against a prior identity or managed receipt, and `evidence_conflict` for contradictory sources (including multiple exact managed references or an exact live process missing from the provider store). Positive exact process evidence remains visible with the contradiction; it does not become a stopped or inactive result.

For the optional 0.2.0 integration, `TerminalLauncherManagedReceiptSource(store, associations_for_session)` accepts the managed store structurally and a callback that returns exact launch-to-terminal associations for the requested `SessionKey`. The callback is where Agent #1 can join its registry records; this module neither imports Terminal Launcher nor knows the dispatcher schema. The same package installs without 0.2.0 and runs with no receipt source.
