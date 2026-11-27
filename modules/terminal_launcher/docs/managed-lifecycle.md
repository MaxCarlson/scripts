# Managed Terminal Lifecycle Contract

This contract is provider-independent. It gives future workspace checkpoint code stable process identities and honest
runtime receipts without storing prompts or launch command lines. It does not add dispatcher commands or schemas.

## API

- `WindowsTerminalBackend.launch_managed(plan, launch_id=None, store=None, startup_timeout=2.0,
  submission_timeout=10.0)` requires `plan.target_window` to be explicit. A caller may provide a stable opaque
  `launch_id`; otherwise the backend creates a UUID. Per-pane IDs are `<launch_id>:<tab_index>:<pane_index>`.
- `ManagedLaunchResult.submission` describes only the `wt.exe` request result. `spawn_acknowledged_pane_ids` and
  `panes` describe child acknowledgments independently. `startup_timed_out` identifies incomplete acknowledgments.
- `ManagedProcessStore.reserve_launch(launch_id, window_id, panes)` atomically reserves every pane in the plan.
  `claim_pane()` gives one relay a durable one-time claim before it may spawn a child. Existing callers may still use
  the deprecated one-pane `register_submission()` compatibility API; new launch paths must reserve the full plan.
- `ManagedProcessStore.enumerate_processes(launch_id=None)` returns persisted launch/pane identities, a stable hash of
  the requested window name, requested tab and pane indexes/layout, PID and creation FILETIME, timestamps,
  failure/exit receipts, liveness, owning-relay liveness, submission state, and interruption progress.
- `ManagedProcessStore.request_interrupt(pane_id)` validates exact child and owning-relay identities and liveness, then
  queues one at-most-once Ctrl+Break interruption request for that pane's relay. It never signals a Windows Terminal
  host process. `request_graceful_shutdown()` remains as a deprecated compatibility alias; it does not promise graceful
  shutdown.

`LaunchSubmissionState` distinguishes `reserved`, `submitting`, `accepted`, `rejected`, and `ambiguous`. A nonzero
`wt.exe` result is a definite rejection; timeout, interrupted wait, or other uncertain submission is ambiguous. A
definite rejection marks only still-reserved panes failed. Existing claims and child receipts are preserved. A late
relay from an ambiguous original submission may claim its pane once. A rejected or already-claimed pane cannot be
claimed again; callers must not automatically retry an ambiguous pane.

Pane state distinguishes `reserved`, `claimed`, `started`, `running`, `exited`, `failed`, `stale`, and `unknown`.
`claimed` means one relay owns the pane but no child-start receipt is durable yet. A child-start receipt is a positive
spawn acknowledgment even when process identity cannot be read. Process identity (PID plus creation FILETIME) and
actual liveness are recorded separately: matching creation time with an exited process handle reports `unknown` plus
`liveness=exited` until the relay persists its exit code. A PID with a different creation time is `stale`; inaccessible
identity or liveness is `unknown`, never presumed exited. If a relay dies between claim, spawn, and receipt, recovery
preserves `claimed`/`unknown` and does not retry that pane automatically.

The SQLite store defaults to
`%LOCALAPPDATA%\terminal-launcher\managed-processes.sqlite3`. It persists opaque launch/pane IDs, the requested
window name hash returned as `window_id_hash`, requested topology, exact process identities, lifecycle timestamps, numeric exit codes, and
short failure codes. It never persists argv, environment, cwd, tab/pane titles, prompts, or credentials. Callers should
keep IDs opaque and non-sensitive. Store files inherit the user's local application data permissions.

The relay starts children as a distinct Windows process group. Interruption requests are queued in SQLite and delivered
only by the owning pane relay after revalidating PID plus creation time and liveness, using the
[Windows process-group control event](https://learn.microsoft.com/en-us/windows/console/generateconsolectrlevent).
Before signal delivery, the relay atomically moves the request from `pending` to `delivering`. It then records
`delivered` or `unknown`. If the relay is interrupted between signal and receipt persistence, `delivering` remains
ambiguous and is never signaled a second time. Delivery means Ctrl+Break was sent; this is an **interruption request**,
not guaranteed graceful shutdown or child exit. No force termination or Windows Terminal host termination is used.

Each relay checks only its own pane's interruption row; it does not scan all managed panes. Child waiting uses adaptive
polling: the default timeout starts at 50 ms and doubles to a 1 s maximum while idle. A queued interruption resets the
timeout to the short interval. If start/exit receipt writes fail, the relay reports a diagnostic and keeps supervising
the child while retrying; a permanently unavailable store leaves the pane explicitly claimed/unknown instead of
silently claiming a durable receipt.

### Idle polling measurement

Measured on 2026-11-27 with Python 3.12 and native PowerShell 7 children on Windows. Each child ran
`pwsh.exe -NoLogo -NoProfile -NonInteractive -Command "Start-Sleep -Seconds 3; exit 0"`; no Windows Terminal or WSL
window was opened. All children exited with recorded exit code 0. The measurement times only the pane-specific SQLite
interruption query and the relay parent process CPU (not PowerShell child CPU):

| Managed children | Wall time | Pane queries | SQLite query time, total | Query time per child-second | Relay parent CPU |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 3.284 s | 6 | 8.78 ms | 2.927 ms | 46.88 ms |
| 5 | 3.324 s | 30 | 37.48 ms | 2.499 ms | 46.88 ms |
| 20 | 3.533 s | 120 | 278.96 ms | 4.649 ms | 359.38 ms |

This is one short local run per size, useful as a bounded overhead check rather than a long-duration benchmark. Query count
stays proportional to each active pane's adaptive idle schedule; no relay queries unrelated panes.

## Requested versus observed layout

The store captures **requested** tab order, pane index, and layout name only. Windows Terminal's supported [`wt.exe`
command line](https://learn.microsoft.com/en-us/windows/terminal/command-line-arguments) documents named-window
targeting, `new-tab`, `split-pane`, titles, and working directories. The documented CLI does not provide a query for
current tab order, pane grouping, or pane geometry. Windows UI Automation exposes a read-only accessibility tree
([tree overview](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-treeoverview)), but its structure is
provider-dependent. This backend therefore reports unsupported/unobserved fields rather than copying launch requests
into observed snapshots.

| Capability | Status | Evidence boundary |
| --- | --- | --- |
| Open/reuse a named window | Supported | `wt.exe --window <name>` request; live native window observed in qualification |
| Request multiple tabs and split arrangements | Supported as commands | CLI command submission; managed per-child spawn receipts are separate |
| Top-level native window handle, class, owner PID, and title | Read-only observable | Win32 enumeration in the isolated live test; title names only the currently selected tab |
| Tab names and order | Read-only UI Automation observation | `TabItem` controls in the isolated window were returned in displayed order; this query is not yet integrated into the backend |
| Child PID plus creation time, spawn, exit code | Supported for managed relay | Durable relay receipt and PID-reuse validation |
| Generic application readiness | Unknown | No generic readiness probe is defined |
| Pane membership, split orientation, and geometry | Not reliably observable by this backend | The tested UI Automation tree exposed generic `Pane` containers, not one stable element per Terminal pane; the returned rectangles were outside the visible desktop bounds |
| Safe tab/pane/window UI closure | Unsupported | No documented identity-targeted close command; process-group shutdown is limited to the owned child |

A future layout provider may expose an optional `capture_layout(window_identity) -> ObservedLayout` operation. It may
use read-only UI Automation for tab names/order, but must return unknown for pane grouping or geometry until a stable
per-pane element and valid bounds are observed. It must return observed data with source and confidence, and may return `unsupported`; `ObservedLayout` must remain distinct
from `TerminalLaunchPlan`. A restoration plan is a separate object derived from an observed checkpoint, not an assertion
that replaying the original plan restored the same geometry.

## Checkpoint integration shape

Future consumers can store launch ID, pane IDs, exact process identities, receipts, and any separately captured
`ObservedLayout`. A restoration planner can compare checkpointed identities against `enumerate_processes`, classify
each as running/exited/failed/stale/unknown, and produce explicit actions for review. It should preserve partial and
interrupted launches as progress instead of retrying panes whose state is ambiguous.

Suggested provider-independent boundary (names can be adapted without depending on Windows Terminal):

```python
class ManagedTerminalProvider(Protocol):
    def launch_managed(self, plan: TerminalLaunchPlan, *, launch_id: str) -> ManagedLaunchResult: ...
    def enumerate_managed_processes(self, launch_id: str | None = None) -> tuple[ManagedProcessRecord, ...]: ...
    def capture_layout(self, window_identity: str) -> ObservedLayout | UnsupportedCapability: ...
    def restore_plan(self, snapshot: ObservedLayout) -> RestorationPlan: ...
    def request_interruption(self, pane_id: str) -> ShutdownRequestResult: ...
    def close_owned_child(self, pane_id: str) -> CloseResult: ...
```

The current implementation provides managed launch, runtime enumeration, and interruption requests as concrete
operations. `ObservedLayout`, restoration plans, and identity-targeted UI closure are future optional capabilities;
pane geometry and safe UI closure remain unsupported. A checkpoint consumer should persist the requested plan and any
observed layout as separate data. Restoration must be an explicit plan and must never infer that a command submission
or an ambiguous pane has already been restored.

## ProcWatch interoperability

Do not add a global ProcWatch bypass or treat a PowerShell title as proof of ownership. The existing `smart` mode may
classify the default `PowerShell 7` title using its current interactive-title rule; other guard modes retain their normal
behavior.

For future intentional-launch recognition, ProcWatch can consume a managed receipt and correlate a process event only
when both PID and creation FILETIME match the pane record. Record the exact launch/pane ID as diagnostic context; keep
the existing window classifier and suppression decision unchanged. Do not create a blanket popup-guard bypass. If a
future targeted exemption is considered, require a separate, short-lived registration bound to an observed HWND plus
the Windows Terminal owner PID and creation time, and use it only when an event correlates to that exact registration.
Without that observed correlation, annotate only and do not bypass suppression. This avoids process-name, title-only,
and all-console exemptions.
