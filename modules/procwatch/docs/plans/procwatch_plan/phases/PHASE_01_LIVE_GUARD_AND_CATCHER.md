# Phase 01 — Live Window Guard & Real-Time Popup/Process Catcher

**Priority:** P0, first implementation increment.  
**Owner:** To be assigned in the next agent handoff.  
**Prerequisites:** Windows 11 interactive test host; read `../MASTER_PLAN.md` and original source `../sources/02_gemini_detailed_plan_original.txt` (Section 3's `NeutralizeEngine`).  
**Next:** [Phase 02 — Flight Recorder & Attribution](PHASE_02_FLIGHT_RECORDER_AND_ATTRIBUTION.md).

## 1. Outcome and boundaries

Deliver a working, pip-installable `procwatch` module with **live visibility into transient console windows and short-lived processes**, plus an opt-in, narrowly targeted guard that reproduces the user-reported useful suppression mechanism. Prioritize a usable local utility over deferred enterprise features. Output should already show what appeared, owning HWND/PID, a provisional process chain, known command-line evidence, and explicit `<unavailable>` / `<exited before enrichment>` states. The full SQLite flight recorder, Sysmon and Task Scheduler ingestion, Git/agent attribution, and historical queries belong to Phase 02.

**Source sequencing:** The longer detailed Gemini plan explicitly prioritizes live guard/catcher in Phase 1, unlike the earlier shorter response. Follow that phase priority. **Source default conflict:** detailed plan says `all-consoles` default; short response says `smart`. This plan resolves it as: `watch` observe-only by default; `guard` starts in `observe` unless a deliberate `-m smart` or `-m all-consoles` is requested; post-validation the configured active default for opt-in guard may be `smart`. Do not silently select `all-consoles`.

## 2. Reference implementation preservation and audit

The full Python guard listing is in `sources/02_gemini_detailed_plan_original.txt`, Section 3. Preserve it as a **reference for behavior and performance comparison**. The user states its combined `MsgWaitForMultipleObjects`/WinEvent, `LockSetForegroundWindow`, `WS_EX_NOACTIVATE`, off-screen `SetWindowPos`, `SW_SHOWMINNOACTIVE`, and `AttachThreadInput` sequence materially reduces interruptions. Retain that sequence as a testable guarded strategy rather than discard it. Its exact output is not a validated drop-in module.

Before copying source, inspect these specific defects/risks:

| Reference behavior | Risk | Required change/experiment |
|---|---|---|
| `SetWinEventHook(EVENT_SYSTEM_FOREGROUND, EVENT_OBJECT_SHOW, ...)` | Registers a broad range of intervening event IDs, not just the named events | Prefer separate focused registrations for foreground and CREATE/DESTROY/SHOW; filter event type & `OBJID_WINDOW`; measure overhead |
| `_should_intercept(...): if not title: return True` in `smart` | All newly created empty-title console windows can be intercepted, including legitimate ones | Mark undecided; reevaluate on SHOW/title/process metadata; suppress only on positive allowlisted automation evidence |
| `LockSetForegroundWindow(LSFW_LOCK)` on every call | May fail if caller is not foreground; source does not call `LSFW_UNLOCK` | Track return status, bound/restore any successful change, avoid assuming this call works; verify no lingering foreground restriction |
| `orig_ex = GetWindowLongW` on each repeated call | Re-reads style **after** injecting `WS_EX_NOACTIVATE`, making restoration incorrect | Capture original style per HWND-instance once; restore on every exit/failure/reopen path |
| Move frame to `(-32000,-32000)` | Minimized/reopened window may remain off-screen | Capture/restore window placement/rectangle and verify across multiple monitors and DPI scales |
| New HWND immediately enters `known_hwnds` | Later title/process evidence may never change classification | Use state machine `first_seen→pending→allowed/suppressed→destroyed` and reevaluation |
| Reentrant WinEvent callbacks and `on_window_event` callback | Slow callbacks or recursive window events risk stalls/inconsistent state | Callback posts bounded primitive event; no DB, Git, WMI, or blocking I/O inside callback; guard fast path must be bounded |
| Raw HWND as identity | Windows recycles handles | Give each observed window an instance-generation ID and clear state on DESTROY |
| Daemon thread + `WM_QUIT` | Hook may not be ready to receive stop message; abrupt interpreter exit can strand styles | Readiness synchronization, idempotent stop, finite join, callback lifetime, guaranteed unhook/state-restoration on shutdown |
| All-window/class controls | Broad suppression could interfere with editor/legitimate interactive terminals | `all-windows` optional experimental only, not a general CLI default; explicit acknowledgment required |

**Windows API limitations to document:** Out-of-context WinEvents are asynchronous; `LockSetForegroundWindow` has a foreground-process restriction; another process may already have stolen focus; no `<1 ms` or `<15 ms` end-to-end guarantee. Measure both hook callback delay and actual observed visibility/focus effect independently.

## 3. Components and files to implement

### 3.1 Package scaffolding

- `pyproject.toml`: modern Python package metadata, console entrypoint `procwatch`, locked/minimum supported Python version and Windows dependency extras. `pywin32`, `psutil`, `rich`, or `comtypes` should only be included if actually used; no unneeded installations or global system configuration.
- `procwatch/__init__.py`, `__main__.py`, `cli.py`, `config.py`: entrypoint; minimal CLI; config validation; per-user paths with platform-appropriate permission considerations.
- `procwatch/models.py`: `RawEvent` or `LiveEvent`, `ProcessIdentity` (provisional), `ProcessObservation`, `WindowObservation`, `GuardDecision`, and typed missing-metadata reason.
- `procwatch/mutex.py`: per-user named Windows mutex, diagnostic owner info; do not prevent unrelated CLI read operations. This phase may use one live event owner even before SQLite exists.
- `procwatch/redactor.py`: redact logging and JSONL strings before writing them; basic protected test fixtures now, full policy verification in Phase 02.
- `procwatch/renderers/console.py`: compact console line, optional ancestry tree, explicit suspected/confirmed labels and timestamp precision.

### 3.2 Window event collector and guard

- `procwatch/collectors/win_event.py`: own WinEvent hook subscriptions and message-pump lifecycle; observe CREATE/SHOW/FOREGROUND/DESTROY where emitted. Record `hwnd`, owner PID (not necessarily initiating PID), class, title, initial and updated visibility, event timestamp, callback arrival time, active foreground target.
- `procwatch/guard/window_guard.py`: `NeutralizeEngine` strategy retaining tested sequence; configurable rule engine; `observe`, `smart`, `all-consoles` modes; cautious optional focus restore; explicit safety logs.
- Snapshot existing HWNDs on startup, *but don't rely solely on snapshotting* to identify intentional launches. Set exclusions for newly user-opened terminals based on multiple pieces of evidence; unresolved cases fail open.
- Log each guard attempt and result (`matched_rule`, `reason`, `window_id`, `attempted_apis`, return/errors, final state). Record intended action separately from observed outcome.
- Avoid using title text as sole assertion of background origin. Titles can be empty, transient, user-controlled, or shared across tabs.

### 3.3 WMI trace collector and ancestry

- `procwatch/collectors/wmi_trace.py`: `Win32_ProcessStartTrace` and `Win32_ProcessStopTrace` event-based subscriptions on COM-initialized worker(s), independent of legacy `WITHIN` polling. Threaded start/stop with tested clean Ctrl+C and no deadlocks.
- `procwatch/correlator/ancestry.py`: seed a process snapshot using Toolhelp32 or psutil, then update an in-memory time-bounded cache on process events. Never key a lifetime solely by PID; retain creation time where available and unresolved provisional keys where not.
- `procwatch/correlator/decoders.py`: safe unwrapping of `cmd /c`, `pwsh/powershell -EncodedCommand` (PowerShell UTF-16LE), selected `wsl -e`; decode for display without executing payloads; preserve redaction and escape control characters.
- On process start, capture immediately available PID, PPID, image, session, timestamp; separately attempt command-line and ancestry enrichment. If the parent exited before observation, mark missing rather than invent.
- On stop, capture exit code **only from a source that provides it**, with status/uncertainty. In this phase, the WMI trace event is the expected source when available.

### 3.4 Preliminary correlation

- First associate a window with its actual host process via `GetWindowThreadProcessId`.
- Search newly started processes across a configurable nearby time interval, compare titles, ancestry, sessions, and executable evidence, and emit **candidate** initiating processes without assuming the Windows Terminal HWND owner is the command that opened it.
- Produce a readable provisional process tree; if a virtualenv shim can be confirmed, offer a collapsed *view* while preserving all underlying process observations.
- Do not promise Scheduled Task exact identities, Git branch, agent-session correlation, or complete Windows Terminal ConPTY relationships until Phase 02.

## 4. Phase 01 CLI contract

| Command | Behavior | Important flags |
|---|---|---|
| `procwatch watch` | Live read-only stream of process and window events | `-p/--popups-only`, `-c/--collapse-bursts` (simple grouping optional), `-s/--show-headless`, `-f/--filter-regex`, `-o/--output-file` |
| `procwatch watch -g/--guard-windows` | Live stream with explicitly enabled guard | `-m/--guard-mode smart|all-consoles|observe` |
| `procwatch guard` | Dedicated hook/guard loop; initial mode `observe` unless explicitly selected | `-m/--mode`, `-n/--no-focus-restore`, `-t/--title-pattern`, `-e/--exclude-pattern`, `-q/--quiet`, `-o/--output-file` |
| `procwatch --help` / subcommand help | Explain the differences among observed windows, suspected causes and suppression | `-h/--help` |

At the end of Phase 01 the remaining public commands may advertise *planned* status only in documentation; do not install placeholder commands that pretend to work. They are implemented in later phases. Never reassign existing flags silently.

## 5. Execution tasks (in order)

1. **Inventory:** determine the target scripts repository/module conventions, inspect source guard, Python version, current CLI launchers, active Git worktrees, and the status of any running agents before changing files.
2. **Baseline fixture:** reproduce the original script's suppression behavior on a controlled *disposable* console with independent timestamp/foreground tracking; record limitations.
3. **Scaffold:** create the package, config, error types, live schema, non-Windows import guards, and tests; choose exact dependencies after prototyping.
4. **WinEvent adapter:** install focused hook(s), message loop, callback filtering, cleanup, observed-window IDs, and callback-to-queue handoff.
5. **Guard strategy:** port and retain current suppression sequence as selectable; fix mutation restoration and safe targeting; default to observe-only until deliberate activation.
6. **Process stream:** WMI trace subscription, snapshot cache, provisional ancestry and fast-exit status, safe decoding; do not perform heavy per-event inspection on the hook thread.
7. **Live correlation/UI:** output window owner vs candidates, rule actions, tree and uncertainty. Integrate with the same live collector owner.
8. **Operational tests:** safe concurrent invocation, stale handle/owner, source failure/degradation, process lifetime and foreground timing measurements.
9. **Checkpoint:** commit tested stage, summarize change/test evidence and known gaps; link this phase completion report before starting Phase 02.

## 6. Verification and acceptance criteria

### Unit tests

- `tests/window_guard_test.py`: matching and exclusion matrices, empty-title handling, intentional terminals, repeated events, original style/position restoration, thread stop, no uncontrolled behavior in observe mode.
- `tests/ancestry_test.py`: fast parent exit, PID reuse, multiple generations, no false parent joins, provisional vs verified identity, collapsed view preserves raw nodes.
- `tests/decoders_test.py`: UTF-16LE PowerShell encoded commands, invalid encodings, nested CMD wrappers, argument quoting, redaction/escape safety.
- Minimal CLI/help and config validation tests, and Windows-only import guards.

### Windows integration scenarios

1. Launch disposable background Python/venv command that opens a Terminal/ConsoleHost window; independently record launcher PID/PPID, spawn/exit time, whether window visibly appeared, foreground HWND.
2. Spawn short lived (`~20 ms`) parent and child processes repeatedly. Record detection counts, metadata availability and unexplained losses; do **not** require metadata the source does not emit.
3. Start a **new intentional** Windows Terminal or PowerShell window *after* monitoring begins, including Start Menu/taskbar and VS Code terminal launches. Smart mode must not suppress any such window in the defined test suite.
4. Repeat new-window tests with empty initial titles, immediate title changes, new tabs, multiple monitors, and rapidly created/destroyed windows.
5. Verify a suppressed test popup can be intentionally reopened, remains on-screen, has its original styles and does not destabilize foreground locking.
6. Verify Ctrl+C, process exit, crashes simulated during hook lifetime, and second collector startup leave no orphan hooks or persistent window modifications.
7. Run a moderate burst load, measure queue drops and reported process data, confirm low overhead on desktop interaction.

### Phase exit gate

- The `procwatch watch` and `guard` commands work on the test Windows 11 machine, or any environment limitation is explicitly documented as a blocker rather than called success.
- Synthetic popups are observed and correlated with an honest, time-stamped **candidate** process chain; no invented command lines or parent names.
- Intentional new terminals are **not suppressed in the defined test suite**; record sample count and false-positive count.
- For target disposable automated popups, record hook callback latency, decision latency, foreground focus transitions, and suppression outcomes. The source `<1 ms`/`<15 ms` performance statements are goals for measurement, not pass-by-assertion.
- Cleanup restores styles/positions when changed and releases any successfully acquired foreground lock. A failure must not leave a window inaccessible.
- Source limitations, busy queues and access-denied cases are surfaced; a short-lived process may legitimately have incomplete enrichment.
- No global terminal/task/Sysmon configuration was changed; no real user agents or local LLM inference were run.

## 7. Deliverable evidence for the next phase

Produce phase-1 code/tests, real `procwatch --help` and sample redacted live logs, test matrix (Windows build, Python version, Terminal preference), a `known-limitations` section, and documented stable live-event model so Phase 02 can persist and reconcile the data. Identify the exact checked-out branch, commit, commands executed and observed outcomes. Do not begin Phase 02 merely because the happy-path guard worked once.

## 8. Relevant authoritative references

- [WinEvent hook semantics, message loop, asynchronous delivery](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwineventhook)
- [Foreground lock and unlock semantics](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-locksetforegroundwindow)
- [Window positioning and style-frame changes](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowpos)
- [Original unmodified Gemini guard listing](../sources/02_gemini_detailed_plan_original.txt)
