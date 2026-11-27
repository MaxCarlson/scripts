# Managed Terminal Lifecycle Contract

This contract is provider-independent. It gives future workspace checkpoint code stable process identities and honest
runtime receipts without storing prompts or launch command lines. It does not add dispatcher commands or schemas.

## API

- `WindowsTerminalBackend.launch_managed(plan, launch_id=None, store=None, startup_timeout=2.0)` requires
  `plan.target_window` to be explicit. A caller may provide a stable opaque `launch_id`; otherwise the backend creates
  a UUID. Per-pane IDs are `<launch_id>:<tab_index>:<pane_index>`.
- `ManagedLaunchResult.submission` describes only the `wt.exe` request result. `spawn_acknowledged_pane_ids` and
  `panes` describe child acknowledgments independently. `startup_timed_out` identifies incomplete acknowledgments.
- `ManagedProcessStore.enumerate_processes(launch_id=None)` returns persisted launch/pane identities, a stable hash of
  the requested window name, requested tab and pane indexes/layout, PID and creation FILETIME, timestamps,
  failure/exit receipts, and graceful-shutdown progress.
- `ManagedProcessStore.request_graceful_shutdown(pane_id)` validates both exact child identity and owning relay identity,
  then queues a request for that pane's relay. It never signals a Windows Terminal host process.

`ManagedProcessState` distinguishes `unknown`, `started`, `running`, `exited`, `failed`, and `stale`. A relay spawn
receipt sets `spawn_acknowledged` even if process-identity access is unavailable; in that case runtime state remains
`unknown` and graceful closure is refused. A process that still exists under the PID but has a different creation time
is `stale`. A process that cannot be queried is `unknown`, not assumed exited. A missing exit receipt after relay
interruption is therefore recoverable without inventing success or failure.

The SQLite store defaults to
`%LOCALAPPDATA%\terminal-launcher\managed-processes.sqlite3`. It persists opaque launch/pane IDs, the requested
window name hash returned as `window_id_hash`, requested topology, exact process identities, lifecycle timestamps, numeric exit codes, and
short failure codes. It never persists argv, environment, cwd, tab/pane titles, prompts, or credentials. Callers should
keep IDs opaque and non-sensitive. Store files inherit the user's local application data permissions.

The relay starts children as a distinct Windows process group. Shutdown requests are queued in SQLite and delivered by
the pane relay, which shares the pane's console and sends Ctrl+Break only after revalidating PID plus creation time,
using the [Windows process-group control event](https://learn.microsoft.com/en-us/windows/console/generateconsolectrlevent).
Delivery means the control event was sent; it does not mean the child exited. The relay records exit only after the
child process exits. No force termination or Windows Terminal host termination is used.

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

Suggested provider-independent boundary:

```python
class ManagedTerminalProvider(Protocol):
    def launch_managed(self, plan: TerminalLaunchPlan, *, launch_id: str) -> ManagedLaunchResult: ...
    def enumerate_processes(self, launch_id: str | None = None) -> tuple[ManagedProcessRecord, ...]: ...
    def capture_layout(self, window_identity: str) -> ObservedLayout | UnsupportedCapability: ...
    def request_graceful_shutdown(self, pane_id: str) -> ShutdownRequestResult: ...
```

Only launch, process enumeration, and graceful child shutdown have concrete APIs here. Layout capture and UI closure are
future optional capabilities.

## ProcWatch interoperability

Do not add a global ProcWatch bypass or treat a PowerShell title as proof of ownership. The existing `smart` mode may
classify the default `PowerShell 7` title using its current interactive-title rule; other guard modes retain their normal
behavior.

For future attribution, ProcWatch can consume a managed receipt and correlate a process event only when both PID and
creation FILETIME match the pane record. Record the exact launch/pane ID as diagnostic context; keep the existing
window classifier and suppression decision unchanged. If a future targeted exemption is considered, require a
separate, short-lived registration bound to an observed HWND plus the Windows Terminal owner PID and creation time,
and only use it when an event can be correlated to that exact registration. Without such an observed correlation,
annotate only and do not bypass suppression. This avoids process-name, title-only, and all-console exemptions.
