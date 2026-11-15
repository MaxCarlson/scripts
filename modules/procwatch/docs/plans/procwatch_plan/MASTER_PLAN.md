# ProcWatch — Master Engineering Plan

**Status:** Implementation-ready planning baseline; no implementation or Windows integration testing has been performed by this plan-authoring pass.  
**Target:** Windows 11, 64-bit, Python CLI/module, interactive user session; a non-Windows development environment may run portable unit tests but cannot validate Win32 behavior.  
**Priority:** Stop disruptive transient console/Windows Terminal popups **while** recording enough evidence to identify and fix their actual origin.  
**Phase sequence:** [01 Live Guard & Catcher](phases/PHASE_01_LIVE_GUARD_AND_CATCHER.md) → [02 Flight Recorder & Attribution](phases/PHASE_02_FLIGHT_RECORDER_AND_ATTRIBUTION.md) → [03 Scan, Audit & Analysis](phases/PHASE_03_SCANNING_AUDITING_AND_ANALYSIS.md) → [04 Headless Runner & Integration](phases/PHASE_04_HEADLESS_SUPERVISOR_AND_INTEGRATION.md).

## 1. Authority and scope of this plan

The archive includes the **unaltered** source materials in `sources/`:

- `01_gemini_reconciliation_original.txt`: Gemini's response reconciling previous review points, including its recommendation to preserve the existing `NeutralizeEngine` behavior with smarter targeting.
- `02_gemini_detailed_plan_original.txt`: the detailed engineering specification, original `window_guard.py` reference listing, CLI contract, package layout, and phase-by-phase instructions.

**Conflict resolution:** The *detailed* source explicitly prioritizes the **guard/live catcher in Phase 1**, then persistence in Phase 2. The shorter response describes a different sequence, and recommends `smart` as the default whereas the detailed spec sets `all-consoles` as the default. This consolidated plan follows the detailed **phase order** but uses `observe` as the safe initial configuration and `smart` as the intended activation default after validation; `all-consoles` remains a clearly labeled, explicit opt-in reproduction of the preexisting standalone behavior. This is a documented engineering decision, not a claim that either attached text already implements it.

**Source fidelity:** Treat the original guard listing as a preservation/reference artifact, not automatically as production-ready or validated source code. The user reports that its suppression pipeline works in their live environment. Preserve the core strategy for A/B comparison, but do not copy its unsafe lifecycle or classification behavior unquestioningly. This plan identifies mandatory corrections below.

## 2. Problem and user outcomes

A background task, `.venv\\Scripts\\python.exe`, PowerShell/CMD wrapper, service-triggered action, or coding-agent subprocess can cause Windows Terminal (`CASCADIA_HOSTING_WINDOW_CLASS`) or classic console (`ConsoleWindowClass`) to appear and steal focus. Windows Terminal may host the window from a process different from the initiating command; fast-exiting processes may have disappeared before a snapshot resolves their command line or parent.

Users must be able to:

1. Run a low-overhead monitor before the next flash and **observe** exactly which window appeared and which processes were temporally correlated.
2. Opt into a targeted **guard** that minimizes known unwanted popups without disrupting terminal windows opened intentionally.
3. Inspect a process tree, command line, likely trigger (agent/task/service), Git worktree, and source evidence; recognize unresolved attributions explicitly.
4. Investigate recent incidents after an application exits, using persistent local process and window history when telemetry existed.
5. Diagnose code and scheduled-task configurations and generate safe, reviewable fixes; verify before/after behavior.
6. Supervise willing background workloads without creating an unwanted console, preserving bounded logs, exit codes, and cancellation diagnostics.

### Non-goals

- No universal guarantee of zero missed ETW/WMI/Sysmon events, `<1 ms` end-to-end window suppression, or complete process metadata for sub-20-ms lifetimes.
- No retroactive reconstruction of actual window visibility when window monitoring was not active; historical Sysmon events establish **process activity**, not observed popups.
- No silent user-input hijacking, global default-terminal changes, broad process termination, service removal, permanent Sysmon installation, or automatic source rewrites.
- No general-purpose EDR, forensic memory dumper, persistent environment-variable harvester, network observability suite, or multi-language compiler project.
- No local LLM inference in the implementation/verification phases unless separately authorized.

## 3. Core architecture

```text
Interactive user session (not Session 0)
  WinEvent CREATE/SHOW/FOREGROUND/DESTROY hooks ──► Window observer
                                     │                       │
  WMI ProcessStartTrace/StopTrace ──► Bounded event intake   ├──► Targeted NeutralizeEngine (opt-in)
                                     │                       │
Optional existing Sysmon + TaskScheduler Operational logs ──┘
                                     │
                          Redaction / normalization
                                     │
                Provisional identity + canonical reconciliation
                                     │
               Process/window/trigger typed evidence graph
                                     │
                   SQLite WAL flight recorder (Phase 2)
                                     │
  watch / guard / history / explain / mark / analyze / scan / audit / exec / doctor
```

**Collector boundary:** Lightweight callbacks emit minimal observations to a bounded queue. Enrichment, database writes, Git invocations, logging, console rendering, and any expensive API use stay outside the WinEvent callback. A guarded fast path may act on a *known, explicitly approved* window class/rule but must never block on SQLite or slow ancestry resolution. Maintain event-source lag, overflow, and loss counters. If guard classification requires unresolved data, fail open (observe but do not suppress).

**Privilege boundary:** Window hooks and guard run under the user's interactive desktop session. Read-only collectors use available privilege; restricted channels report `degraded/unavailable`. Any optional privileged helper must be a separate, narrowly scoped later capability—not a prerequisite for the MVP. Configuration of Sysmon/task XML is a separately authorized write operation.

**One owner:** A single per-user collector process owns hooks, live subscriptions, the SQLite writer, and guard state. Use a named per-user mutex plus an owner/heartbeat record to distinguish a live owner from stale storage state. Another `watch`/`guard` invocation should connect to or report the existing collector; never steal ownership or install duplicate conflicting hooks. Read-only commands may use SQLite WAL readers. `mark` writes a small bookmark transaction or contacts the owner through a tested local IPC path; do not advertise it as read-only.

**Security:** Pre-persistence redaction applies to originals **and decoded payloads**, command lines, user-supplied labels, event-log XML, log records, exported bundles, and agent context. Capture only approved environment keys, and prefer passing context by instrumentation over inspecting arbitrary process environments. A fail-closed redaction policy should drop sensitive payload fields rather than accidentally store raw secrets when sanitization fails. Protect DB/backups with user-local permissions.

### Proposed package tree

```text
procwatch/
├── pyproject.toml
├── README.md
├── procwatch/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── models.py
│   ├── mutex.py
│   ├── redactor.py
│   ├── storage.py
│   ├── guard/
│   │   ├── __init__.py
│   │   └── window_guard.py
│   ├── collectors/
│   │   ├── __init__.py
│   │   ├── win_event.py
│   │   ├── wmi_trace.py
│   │   ├── sysmon_evt.py
│   │   └── task_events.py
│   ├── correlator/
│   │   ├── __init__.py
│   │   ├── engine.py
│   │   ├── ancestry.py
│   │   ├── terminal_session.py
│   │   ├── peb_git.py
│   │   ├── decoders.py
│   │   └── scorer.py
│   ├── analyzers/
│   │   ├── __init__.py
│   │   ├── ast_scanner.py
│   │   ├── task_auditor.py
│   │   └── patterns.py
│   ├── runner/
│   │   ├── __init__.py
│   │   └── supervisor.py
│   └── renderers/
│       ├── __init__.py
│       ├── console.py
│       └── doctor_view.py
└── tests/
    ├── window_guard_test.py
    ├── ancestry_test.py
    ├── decoders_test.py
    ├── storage_test.py
    ├── redactor_test.py
    ├── correlator_test.py
    ├── ast_scanner_test.py
    ├── task_auditor_test.py
    ├── patterns_test.py
    ├── supervisor_test.py
    └── integration_win32_test.py
```

File names and public modules follow the detailed source unless an accepted change is recorded. Optional internal modules may be added for maintainability; changes to documented CLI names and behavior require explicit plan updates.

## 4. Critical design decisions and unresolved source issues

| ID | Decision / implementation constraint | Rationale and verification |
|---|---|---|
| D01 | **Phase 1 guard + live catcher first.** | Detailed source's explicit priority; users get immediate observable QoL value. Phase 1 operates with provisional in-memory evidence before the durable recorder exists. |
| D02 | **Initial guard mode = `observe`; intended active default = `smart` after Windows tests; `all-consoles` explicit.** | Reconciles conflicting source defaults and protects new user-initiated windows. `watch` never guards unless `-g` is supplied. |
| D03 | Preserve and benchmark the **reported-working NeutralizeEngine suppression sequence** as a reference, then make changes behind tests and rules. | Live user observation is evidence of local utility, not proof of zero-flicker correctness or safety on every Windows build. |
| D04 | **Never suppress simply because the title is empty** at `EVENT_OBJECT_CREATE`. | The source `_should_intercept()` currently returns true for empty titles in `smart`, meaning legitimate new terminals can be caught. Re-evaluate on subsequent events, do not immediately add unknown HWNDs to a permanent allow/deny list. |
| D05 | **Foreground locking is conditional and lifecycle-safe.** | `LockSetForegroundWindow` is restricted to the foreground process; the reference calls `LSFW_LOCK` but never explicitly balances with `LSFW_UNLOCK`. Capture API success/errors, scope changes, restore/cleanup, and test focus behavior. |
| D06 | Preserve original extended styles **and window position**, restore them reliably if intervention occurs, and handle repeated events without overwriting originals. | Source's restore-on-SHOW reads an already modified style; moving to `(-32000,-32000)` must not strand an intentionally reopened terminal. Test taskbar restoration and monitor layout changes. |
| D07 | Split/filter WinEvent event ranges; safely handle callback reentrancy. | Source's `SetWinEventHook(EVENT_SYSTEM_FOREGROUND, EVENT_OBJECT_SHOW)` is a broad numeric range; register focused hooks or narrow callback processing, and keep callbacks minimal. |
| D08 | No fixed causal time window or unverified 100% agent certainty. | Window host ≠ launching process; independently sourced edges, session IDs, timestamps and confidence required. |
| D09 | **Source-specific capabilities**, not guessed exit status or window visibility. | Sysmon ID 5 gives termination, not exit code. WMI stop trace can expose exit status; access can still fail. |
| D10 | **At-least-once Event Log ingestion with checkpoint + raw-event insert in one SQLite transaction** and dedupe. | Prevent silent loss on crashes. For stale bookmarks or log clearing, backfill from earliest available, report a gap; never claim uninterrupted history. |
| D11 | Provisional identities upgrade to canonical identity without losing evidence, and detect PID/HWND reuse. | `(boot, pid, coarse time bucket)` is a temporary lookup key, **not** adequate canonical truth. |
| D12 | Scanner defaults to analysis/diff only; task changes require explicit apply and restore plan. | Missing `CREATE_NO_WINDOW`/`-WindowStyle Hidden` is not automatically a bug. Preserve interactive programs and dirty worktrees. |
| D13 | `exec` is a supervisor with **headless** profile first, not a universal terminal emulator. | Pipes and job objects are useful but can change console/TTY behavior; document unsupported commands. |
| D14 | Keep **ten commands** with short & long flags; use `analyze` for before/after comparison. | No phantom `compare` command; `doctor` is read-only. |

### Explicit Win32 reference-code audit gate (Phase 1)

Before treating the pasted `NeutralizeEngine` as production code, assess (with an isolated test harness): hook event-range breadth, `EVENT_OBJECT_DESTROY`, the premature `known_hwnds` decision, empty-title suppression, API error handling, ctypes types/64-bit pointer safety, callback lifetime/reentrancy, WinEvent message loop startup/stop synchronization, global foreground lock/unlock semantics, state restoration, HWND reuse, `orig_ex` restoration after repeated calls, position restoration, `AttachThreadInput` detach on all paths, foreground-window ownership, no-active-click dragging, and desktop/user changes. **Do not delete the proven mechanism merely because an API has limitations; preserve it as a selectable behavior for A/B validation.** Do not claim sub-millisecond guaranteed popup suppression based solely on `MsgWaitForMultipleObjects` wakeup behavior.

## 5. Event, identity and persistence contracts

### 5.1 Raw vs. normalized evidence

Use the detailed-source tables as the base: `schema_meta`, `collector_state`, `raw_events`, `processes`, `windows`, `evidence_edges`, `incidents`, `bookmarks`. For Phase 2 add or reserve an appropriately migrated `collector_gap`/`ingest_gaps` record and `agent_context`/`execution_runs` only where needed. Data elements:

- Raw event identity: `machine_id` or installation identity, `boot_id`, `channel/provider`, source record identity, original UTC event time, ingestion UTC time, source-specific monotonic time **when available**, redacted payload, ingestion/gap state. Do not fabricate monotonic timestamps for imported historical records.
- Process identity: canonical Sysmon ProcessGuid when available, otherwise boot+PID+verified kernel create time; provisional IDs when neither available. Reconciliation must be idempotent and may **fail to match** rather than join different processes.
- Windows: HWND + **observed instance generation** and owner PID/process identity, title/class history, visibility and foreground transitions. CREATE event may be missed; synthesize an observed-first-seen instance, not fictitious create-time precision.
- Edges: typed `parent_of`, `triggered_by`, `hosted_by`, `correlated_with`, `supersedes`; each carries source, supporting event IDs, method, and confidence/known-unknown classification. Graph edges are directional and documented.
- Capabilities: `process_created`, `process_terminated`, `exit_code_known`, `window_observed`, `command_line_captured`, `ancestry_complete`. Add missing-data reasons such as `not_emitted`, `exited_before_enrichment`, `access_denied`, `source_unavailable`, `queue_overflow`.
- Incident: one or more window observations, candidate process(es), initiator candidates, confidence and alternative hypotheses; never infer `visible_popup` solely from Sysmon historical events.
- Bookmarks: user-created timestamp labels are distinct from Windows Event Log subscription checkpoints; use clearly named code entities (`user_marks` vs `evt_bookmarks`) even if source DB table `bookmarks` is retained.

### 5.2 Event log recovery semantics

1. Detect existing built-in **or** standalone Sysmon; never install, uninstall, or reconfigure it by default.
2. For each subscribed channel, establish a stable source key and read available records with a persisted XML bookmark when possible.
3. Redact before persistence. Begin SQLite transaction, upsert all new raw-event IDs, update the checkpoint corresponding to **committed** events, and commit. Replay/dedupe after restart.
4. If a bookmark is stale/invalid or a log was cleared, detect and record a **coverage gap**, attempt supported backfill from available records, and resubscribe at a clear point. The source proposal's unconditional reset-to-future would silently discard still-available history; it is a last resort with explicit gap reporting.
5. Protect against duplicate subscriptions and multiple writers, `SQLITE_BUSY`, schema changes, interrupted migrations, and retention cleanup while readers are active.

### 5.3 Security/retention defaults

- No collection of complete remote process environments, handles, or stdout without user selection; suppress credentials in `/token`, `-key`, `--password`, URI userinfo, PowerShell `-EncodedCommand` decoded text, and known key/value formats. Unknown secrets may still exist; document redaction limitations and keep access local.
- Store both raw-within-redaction and normalized records; **never** persist unredacted input to debug files or exception reports.
- Configurable time + byte retention with rotation/vacuum policies that do not block live callbacks; bounded queue/capture sizes and collection drop counters.
- Separate temporary guard state and durable evidence state, so a SQLite failure cannot cause uncontrolled window mutations.

## 6. Public CLI contract (ten commands)

| Command | Contract and primary flags | Mutability |
|---|---|---|
| `guard` | `-m/--mode observe|smart|all-consoles`, `-n/--no-focus-restore`, `-t/--title-pattern`, `-e/--exclude-pattern`, `-q/--quiet`, `-o/--output-file`; optional `all-windows` remains **experimental/unsafe**, not default | Opt-in window changes outside observe |
| `watch` | `-p/--popups-only`, `-g/--guard-windows`, `-m/--guard-mode`, `-c/--collapse-bursts`, `-s/--show-headless`, `-f/--filter-regex`, `-o/--output-file` | Read-only unless `-g` |
| `history` | `-t/--time-window`, `-p/--popups-only`, `-a/--agent-filter`, `-r/--replay-timeline`, `-e/--export-bundle` | DB query, optional export file |
| `explain` | `-i/--incident-id` or `-p/--pid`, `-j/--json-output` | Read-only |
| `mark` | `-l/--label`, `-w/--window-seconds` | Adds user mark to DB (explicit command) |
| `analyze` | `-p/--periodicity`, `-b/--baseline-window`, `-w/--window-seconds`, `-j/--json-output` | Read-only |
| `scan` | `-d/--directory`, `-w/--include-worktrees`, `-u/--unified-diff`, `-a/--apply-fixes`, `-f/--force`, `-j/--json-output` | Read-only by default; explicit `-a` writes |
| `audit` | `-t/--target-type`, `-n/--task-name`, `-a/--apply-task-fix` | Read-only by default; explicit `-a` writes |
| `exec` | `-c/--command`, `-w/--working-dir`, `-t/--timeout-seconds`, `-k/--keep-console-on-error`; support `--` raw-argv form | Executes explicitly supplied command |
| `doctor` | `-v/--verbose`, `-j/--json-output` | Strictly read-only |

Every option with a short spelling has an equivalent double-dash long spelling; no extra CLI short flag invented without defining its meaning. Keep `-h/--help` universal, deterministic error codes, useful errors, no `shell=True` by default, exact argv preservation (avoid lossy string concatenation), JSON structured schema versioning, and robust Ctrl+C cleanup. For tasks/fixes, present a preview and require explicit approval for material external changes. `watch` may attach to the existing collector rather than spawning a second one; define the transport explicitly during implementation.

## 7. Phases and dependencies

| Phase | Priority | Product increment | Depends on | Exit gate |
|---|---|---|---|---|
| [01](phases/PHASE_01_LIVE_GUARD_AND_CATCHER.md) | P0 | Working package; live WinEvent watcher and WMI process start/stop, ancestral cache; opt-in guard with verified smart targeting; live CLI | Existing reference guard + Windows test fixture | Reproducible synthetic popups observed, guard can be enabled without suppressing tested interactive launches; known gaps reported |
| [02](phases/PHASE_02_FLIGHT_RECORDER_AND_ATTRIBUTION.md) | P0 | SQLite flight recorder; Sysmon & Task logs; reconciled IDs; Git and agent context; explain/history/mark/doctor | Phase 1 stable event contract | Replay/restart/checkpoint/secret tests and evidence-backed incident explanations pass |
| [03](phases/PHASE_03_SCANNING_AUDITING_AND_ANALYSIS.md) | P1 | Python/PowerShell code scanner; Scheduled Task/startup auditor; periodicity and before/after analysis | Phase 2 history & incident data | Reproducible suggestions/diffs, no unapproved changes, correct comparison methodology |
| [04](phases/PHASE_04_HEADLESS_SUPERVISOR_AND_INTEGRATION.md) | P1 | Headless supervised executor; job objects; bounded logs; launcher integration; end-to-end validation | Phases 1–3 contracts | Supported tasks run without unwanted windows, preserve logs/exits, terminate controlled children, and validate remediation |

**Recommended checkpoints:** Separate branch/commit for each phase, with the phase's tests, CLI help, docs and changelog updated. Avoid starting the next phase until the preceding phase's reported test results and limitations are documented. If independent work can be parallelized, use separate worktrees/branches and merge only after compatible integration tests; no conflicting edits in one checkout.

## 8. Verification strategy and minimum evidence

- **Unit:** imports, decoders (especially PowerShell UTF-16LE `-EncodedCommand`), event models, 64-bit identity and HWND generation, rule evaluation, redactor, SQL migration/recovery, parse/scan fixtures, periodicity, output and cancellation. No Windows-only import failures in portable pure-Python modules.
- **Windows end-to-end:** controlled ground-truth launcher independently records process PID/create/exit/parent, shell and venv variants, interactive PowerShell/Windows Terminal, default-terminal settings, and genuine transient windows. Test both with existing Sysmon and without; never alter global Sysmon state just to pass tests without approval.
- **Guard safety:** intentional `wt.exe`/PowerShell windows opened after startup, tab restoration from taskbar, interactive VS Code terminal, input while dragging or typing, repeated CREATE/SHOW, stale HWND reuse, multi-monitor coordinates, foreground-lock return codes. Count false positives and regressions; **0 observed in the defined suite** is not a universal guarantee.
- **Observability:** test source unavailable/access denied, fast parent exit, queue saturation, Event Log stale bookmark/log clearing, DB locked/disk full, restart/crash during bookmark transaction, self-monitoring, duplicate collector startup, NUL/non-ASCII titles and paths.
- **Performance:** record test machine, Windows build, terminal mode, hook-to-action and end-to-end window timings, process recall vs ground truth, event loss, CPU/memory/disk cost. The source `<1 ms` and `<15 ms` figures are experimental hypotheses; never use as unverified release guarantees.
- **Release evidence:** `pytest` results, integration harness summary, collector capability matrix, diagnostic sample incidents with redacted secrets, benchmark sample sizes, known limitations, reviewer approval of guard safety.

## 9. Execution, permissions and handoff discipline

1. Inspect existing repository/branch/worktree, status, active processes/agents, and source implementation before editing; do not overwrite productive work or uncommitted user changes.
2. Work in a dedicated branch/worktree as authorized. Do not call or run local LLM inference. Respect existing packaging/conventions (`scripts` repo integration if chosen).
3. Implement the next phase only; leave phase boundaries and schema/API migration plans clear. Keep CLI and tests synchronized.
4. System changes (scheduled tasks, Sysmon enablement, startup registration, default terminal settings, administrator elevation) require **user authorization and a rollback plan**; do not make these changes during passive diagnosis.
5. For every checkpoint, report: branch/commit, changed paths, exact commands/tests executed, pass/fail and skipped tests, OS/runtime/build, measured metrics, unresolved issues, and suggested integration point.
6. Preserve the original Gemini detailed guard listing as an auditable source. The next-turn agent handoff can refer to this ZIP and individual phases; **no agent handoff is included or initiated in this deliverable**.

## 10. Key source/API references (for implementation verification)

- [SetWinEventHook — Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwineventhook): callback range, asynchronous out-of-context notification, message-loop requirement and reentrancy.
- [LockSetForegroundWindow — Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-locksetforegroundwindow): foreground-process restriction and explicit lock/unlock semantics.
- [SetWindowPos — Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowpos): position and frame-style behavior.
- [Sysmon overview — Microsoft Learn](https://learn.microsoft.com/en-us/windows/security/operating-system-security/sysmon/overview): optional built-in feature and collection role.
- [Sysmon events — Microsoft Learn](https://learn.microsoft.com/en-us/windows/security/operating-system-security/sysmon/sysmon-events): process-create and termination semantics.
- [Enable/configure Sysmon — Microsoft Learn](https://learn.microsoft.com/en-us/windows/security/operating-system-security/sysmon/how-to-enable-sysmon): prerequisites, permissions and standalone coexistence.
- [Start-Process — Microsoft Learn](https://learn.microsoft.com/powershell/module/Microsoft.PowerShell.Management/Start-Process): `-WindowStyle` and incompatible `-NoNewWindow` semantics.

## 11. Definition of complete project

The final result is a usable Python module/CLI, not just passing unit tests: it can observe transient terminal windows without global configuration changes, explain incidents with credible evidence and missing-data transparency, maintain bounded local history, protect intentional terminals under validated targeting rules, analyze and suggest fixes without destructive defaults, execute supported background workloads with retained diagnostics, and demonstrate measurable results on the user's real Windows 11 environment. All four phase gates must be recorded and all external changes authorized. Handoff composition is a **separate next-turn task**.
