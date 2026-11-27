# Read-only runtime discovery API

`agent_continuity.runtime_discovery` provides a typed, provider-independent observation for one exact native session. It is designed for LLMD list, doctor, activity and identity consumers, and for later checkpoint planning. It does not change registry state, launch providers, inspect terminal titles, or persist observations.

```python
from agent_continuity.runtime_discovery import RuntimeDiscovery, SessionKey

observer = RuntimeDiscovery(environment_id="env_win_example")
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

An observer is bound to both `runtime_kind` and the exact `environment_id`. A target whose runtime or environment differs returns unavailable evidence without querying process, provider, or managed-receipt sources. Pass the same runtime and environment identity to an injected process snapshot; mismatched snapshots are discarded. A WSL or remote observer must be constructed separately with explicit sources for that runtime. Runtime discovery never starts WSL or a remote runtime.

## Independent dimensions

| Field | Meaning |
| --- | --- |
| `process_liveness` | `running` requires a current exact-session process match or a live known PID/creation identity. `exited` applies to a supplied known identity absent from a complete snapshot or replaced by a reused PID. `not_observed` means a complete snapshot had no exact match; it does not mean the provider session ended. `unknown` and `ambiguous` preserve gaps and duplicates. |
| `known_process_liveness` | Liveness of the optional PID plus creation-time identity supplied by a previous observation or receipt. |
| `process_session_match` | Whether process arguments or an exact managed association identifies this native session. Matching requires the provider's invocation syntax and the complete session ID. |
| `session_identity_state` | `exact` means the process selects an existing native session; Claude `--session-id` is reported as `reserved`, since that UUID alone does not prove a durable or resumable session exists. |
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
- The Codex matcher requires a supported `codex resume` form with one unambiguous exact positional ID; AGY requires exactly one `--conversation` selector; Claude accepts exactly one `--resume` or `--session-id` selector. Claude `--resume` is existing-session identity, while `--session-id` is reserved identity. Executable recognition alone never establishes identity. Supported Node entry-point wrappers must identify the provider at `argv[0]` / `argv[1]`; names found elsewhere in arguments are ignored. Unknown or conflicting options, duplicate identity selectors and `--` boundaries are rejected conservatively, so unsupported invocation forms may remain `unknown` until their syntax is explicitly qualified. Arguments are inspected in memory and omitted from observation objects, safe dictionaries, reprs and diagnostics.
- Provider activity, a registry association, an executable name, a window title, or a recent-session position alone cannot establish that a session is running.

`RuntimeDiscovery` accepts additional exact-match callables through `process_matchers: Mapping[str, ProcessSessionMatcher]` and exact-ID read-only stores through `provider_stores: Mapping[str, SessionStore]`. This lets provider integrations supply their own evidence without changing the runtime observer. When no Claude `SessionStore` is supplied, provider-store activity remains unavailable even if an exact process selector is observed. A reserved Claude `--session-id` with a negative provider-store lookup is not reported as contradictory evidence. The matcher receives raw argv only for the duration of the call; implementations must not retain or log it.

An exact process match may still be returned when unrelated process entries are inaccessible; its positive evidence is retained and overall availability is partial. With no exact match, partial or unavailable process enumeration returns `unknown`. A complete snapshot with no match returns `not_observed`, never `inactive`.

## Batch snapshots

`capture_snapshot()` returns a transient `ProcessSnapshot` containing one `ProcessInventory`, `runtime_kind`, and exact `environment_id`. `observe_many(keys, snapshot=...)` reuses that enumeration across at most 256 sessions and returns observations in input order. If no snapshot is supplied, the method captures one enumeration for the whole batch. `observe(key, ...)` remains source-compatible and delegates to a one-key batch.

Snapshots are accepted only when both environment dimensions match and their capture time is within two seconds of the observer clock. Stale, future-dated, or foreign snapshots produce unavailable process evidence; absent rows from them are never used as negative liveness evidence. Provider and receipt sources still receive each exact key independently. Capture one snapshot per user operation (for example one `llmd list`, `doctor`, or checkpoint preview), then pass it through `observe_many`.

## Process identity precision

`ProcessIdentity` keeps the normalized PID, creation time, and `precision_ns` uncertainty radius. Terminal Launcher Windows FILETIME receipts are exact at 100 ns resolution. `psutil` supplies floating-point seconds, so `process_identity_from_psutil()` records a bounded uncertainty radius. `compare_process_identities()` returns `same` only for equal exact identities, `different` only when the PID differs or the time uncertainty ranges do not overlap, and `ambiguous` when a rounded timestamp could represent the same process. Safe JSON includes the precision radius so checkpoint recovery does not accidentally reinterpret an approximate timestamp as exact. Ambiguous comparison keeps liveness `unknown` and does not report PID reuse. Never reduce this to raw integer equality or infer ownership from PID alone.

## Optional Terminal Launcher receipts

`ManagedReceiptSource` and `ManagedPaneReference` are local protocols and dataclasses. The module does not import Terminal Launcher, so it works with the installed 0.1.x package or with no Terminal Launcher package. An integration can provide a receipt source when Terminal Launcher 0.2.0 is available and join its `launch_id` / `pane_id` to an exact LLMD provider-session association. The association must include the exact `SessionKey`, pane ID, terminal-session ID, and `current` or `historical` state. Every receipt lookup is filtered to that exact pane within its launch. A historical receipt is reported separately and cannot be promoted to current merely because the launch still exists.

`managed_pane_reference_from_terminal_launcher_record()` accepts a 0.2.0 receipt by duck typing. Terminal Launcher records Windows creation times as FILETIME; `process_identity_from_windows_filetime()` converts them to the Unix-nanosecond scale used by `ProcessIdentity`. The adapter requires a positive spawn acknowledgment, PID and creation time. The association adapter enforces the exact pane/session join; it does not inspect registry schemas or infer associations.

## Consumer boundary

Agent Continuity owns the provider/runtime observation module and its collectors. A consumer passes the exact `SessionKey`; it may pass whether an exact registry association exists and a previously observed process identity. The runtime module only returns evidence. It does not mutate registry associations, write lifecycle events, interpret operator labels such as `IN USE`, or persist checkpoints.

LLMD list and doctor should render process state, attachment, management, provider activity, lifecycle and evidence availability as separate fields. When process enumeration is partial, show unknown rather than inactive. Checkpoint consumers should pass the exact `SessionKey`, one fresh environment-bound `ProcessSnapshot`, and any previously observed exact `ProcessIdentity` to the batch API. Persist observation time, evidence availability/confidence, identity comparison result, exact provider/session/environment identity, and an optional exact managed pane reference as evidence; do not turn an ambiguous or unavailable result into a confirmed inactive state.

Checkpoint and restoration design must remain ordered behind the authoritative LLMD prerequisites: stable immutable slot identity and monotonic numbering (LLMD-49), persistent profile and workflow type contracts (LLMD-25/48), and cross-GUI membership/transfer semantics (LLMD-55). Checkpoints should reference immutable slot/checkpoint identities rather than display names or reusable numbers; the restoration queue should deduplicate by checkpoint plus immutable slot identity. Capture actually observed sessions, not every slot labeled active. Keep requested topology separate from observed topology, and mark changed or missing source evidence stale. This module supplies observation evidence only; it owns no checkpoint persistence, registry schema, numbering, workflow, transfer, queue, or restoration policy.

The runtime API can observe process identity and coarse attachment evidence. It cannot currently report reliable Windows Terminal tab order, exact pane geometry, or close an identity-targeted UI pane. Those remain unsupported until a supported managed receipt provides them.

## Validation limits

Unit tests use injected process inventories and temporary provider SQLite databases. The default process enumerator is also smoke-tested on the current native host. A test harness that cannot enumerate the operator desktop must report that boundary as unavailable/partial; it must not infer inactivity or interact with unrelated processes. No provider launch, WSL startup, window closure, registry mutation or checkpoint persistence is part of this module.

Native Windows smoke (2026-11-27): `Get-CimInstance Win32_Process` raised a `CimException` in this execution context. Optional psutil enumerated 725 records, with 172 inaccessible or raced entries, so the snapshot was correctly `partial`. No provider was launched. A repeated-versus-batched benchmark used three measurements per size and a harmless in-memory provider store: at 1 session, repeated p50/p95 was 81.8/196.5 ms and batch was 74.3/75.3 ms (1 enumeration each); at 5 sessions, repeated was 420.1/450.3 ms with 5 enumerations and batch was 88.6/121.1 ms with 1; at 20 sessions, repeated was 1693.1/1750.9 ms with 20 enumerations and batch was 102.8/109.1 ms with 1. Values are host- and permission-specific; partial enumeration means absent processes remain unknown.

The observation exposes `identity_conflict` for PID/creation-time reuse against a prior identity or managed receipt, and `evidence_conflict` for contradictory sources (including multiple exact managed references or an exact live process missing from the provider store). Positive exact process evidence remains visible with the contradiction; it does not become a stopped or inactive result.

For the optional 0.2.0 integration, `TerminalLauncherManagedReceiptSource(store, associations_for_session)` accepts the managed store structurally and a callback that returns exact launch-to-terminal associations for the requested `SessionKey`. The callback is where Agent #1 can join its registry records; this module neither imports Terminal Launcher nor knows the dispatcher schema. The same package installs without 0.2.0 and runs with no receipt source.
