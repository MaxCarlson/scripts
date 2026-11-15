# Phase 02 — Persistent Flight Recorder, Evidence Correlation & Attribution

**Priority:** P0; begins after Phase 01 live event/guard safety gate.  
**Prerequisites:** [Master Plan](../MASTER_PLAN.md), [Phase 01](PHASE_01_LIVE_GUARD_AND_CATCHER.md), original source files in `../sources/`.  
**Next:** [Phase 03 — Scanning, Auditing & Analysis](PHASE_03_SCANNING_AUDITING_AND_ANALYSIS.md).

## 1. Outcome

Convert the live Phase 01 monitor into a bounded **persistent incident flight recorder** capable of reconstructing process execution and observed desktop-window incidents after processes exit. Add existing Sysmon and Task Scheduler event-log evidence, transactional replay checkpoints, accurate process and window identities, Git/worktree and agent context, confidence-scored causal explanations, user incident bookmarks and a read-only diagnostic command.

**Critical distinction:** Sysmon can show that a process existed *before* ProcWatch began, assuming logging was already enabled. It cannot prove whether a window was visually displayed when no WinEvent/window telemetry was active. Historical incident output must make this distinction explicit.

**No silent elevated changes:** Detect Sysmon (built-in Windows feature or standalone installation), check effective channel permissions and configuration, but don't install/reconfigure it, change Security auditing, enable Task Scheduler logs, register startup tasks, or elevate without the user's separate authorization. WMI/WinEvent remain a useful degraded mode.

## 2. Storage and data contracts

### 2.1 Canonical SQLite storage

Implement `procwatch/storage.py` with versioned migrations and WAL. Default per-user data directory `~/.procwatch/` (resolved to a sensible local Windows profile path), DB `events.db`; configurable separate size and time retention. Database connections should be managed explicitly with busy timeouts, transactions and bounded writes; no persistent raw secret data should reach the DB or WAL.

**Required tables** (keep the source names; extend columns only through documented migrations):

| Table | Required fields, semantics and constraints |
|---|---|
| `schema_meta` | schema version, migration timestamp; migrate atomically and refuse unsupported newer versions |
| `collector_state` | per source/channel status, last durable Event Log bookmark, event counts, queue drops, last error, last durable offset, observed coverage state |
| `raw_events` | auto ID, machine/boot ID, provider/channel/source, source record ID, event type, event UTC time, arrival time, optional monotonic time, **redacted** source payload and dedupe unique key |
| `processes` | provisional/canonical process key; boot, PID/PPID, GUID if present, verified kernel creation time when available, executable/command, source-specific metadata status, start/stop and optional exit status, capability flags |
| `windows` | observed HWND *instance* key, class, owner process, title timeline, visibility, foreground changes, attempted guard action/result, event timestamps |
| `evidence_edges` | typed from/to identities, relation, supporting raw-event IDs, method, confidence/known status, time bound, normalized direction |
| `incidents` | stable incident ID, category, window observations, candidate initiators, primary hypothesis, alternative hypotheses, rule hits, summary and confidence |
| `bookmarks` | **user marks**: timestamp, label and matched incident IDs; not Windows Event Log checkpoints |
| `ingest_gaps` (extension) | source/channel, start/end bounds when known, reason (`log_cleared`, `stale_bookmark`, `access_denied`, `queue_overflow`, `collector_down`), remediation/backfill status |

A single incident may have multiple window events and multiple competing processes. If source's single `window_instance_id` column is insufficient, use a small incident-window mapping table rather than forcing a premature single match. Reserve canonical IDs for direct facts and keep heuristics in separate typed edges.

### 2.2 Identity reconciliation

- **Process:** primary stable match via existing Sysmon ProcessGuid + machine/boot context if available. Fallback `(machine, boot, PID, *verified* kernel create time)`. Initially assign provisional identity to ambiguous WMI observations; never treat coarse time buckets as authoritative identities.
- Reconcile multiple WMI/Sysmon events with source timestamp tolerances and actual create time/parent fields; merge only when evidence is sufficiently strong. When in doubt, keep two candidate records and a low-confidence association.
- Preserve original IDs and `supersedes` relationship on promotion; update references transactionally, avoid cycles, and ensure replay is idempotent.
- PID can be reused; parents may have exited before the observer starts. Maintain explicit unresolved/missing reasons.
- **Window:** HWND is reusable. Create an observed-instance generation keyed by boot + HWND + first-observation generation, not a fictional exact CREATE time when that event was missed. On destruction, finalize and free guard state; reused handle gets a new instance.
- **Boot:** derive a boot/session identity that survives ProcWatch restarts within the same OS boot; don't make it merely a newly generated per-process UUID. Document Fast Startup/hibernation ambiguity and reconcile with source semantics.

### 2.3 Evidence and capability contract

Use typed edges such as `parent_of`, `triggered_by`, `hosted_by`, `correlated_with`, `supersedes`. For every inferred relationship, preserve evidence IDs, matching features, ambiguity and alternative candidates; confidence labels `high/medium/low` are not substitutes for an explanation. Keep an explicit `unknown` state.

Process capabilities/status: `process_created`, `process_terminated`, `exit_code_known`, `window_observed`, `command_line_captured`, `ancestry_complete`, plus metadata failure cause (`access_denied`, `not_emitted`, `exited_before_query`, `source_offline`, `queue_dropped`, `unknown`). Sysmon Event ID 5 is **not** an exit-code source; use a suitable process-stop source where available.

## 3. Event Log collectors and durable checkpoints

### 3.1 Existing Sysmon collector (`procwatch/collectors/sysmon_evt.py`)

- Detect channel availability and distinguish absent, installed but disabled, configured/excluded events, read-access denied, and active.
- Consume Process Create (Event ID 1) and Process Terminated (Event ID 5) when recorded; retain Sysmon ProcessGuid, parent ProcessGuid/PID, image and command line as emitted, after redaction.
- Optionally inspect event source metadata for schema differences; do not assume every machine has the same Sysmon version or event filter config.
- Catch up from available history when installed/configured; label historical process execution as such, **not confirmed historical popup**.
- Prefer Event Log API subscription/query bookmarks with source-level state and clear error surfacing. If `pywin32` bindings are used, verify exact `EvtSubscribe`/bookmark API behavior on the target Windows version.

### 3.2 Task Scheduler collector (`procwatch/collectors/task_events.py`)

- Read Task Scheduler Operational events relevant to task trigger/action lifecycle (source suggests IDs 100, 129, 200, 201). Verify actual event-field semantics from rendered XML and fixture samples rather than assuming a task's engine PID equals the action PID.
- Correlate task path, instance GUID, action executable, action arguments and event time to process starts. Store task identities and candidate edges. Report multiple matching tasks or incomplete telemetry honestly.
- Keep COM task enumeration as an optional targeted enrichment of candidate tasks; no system modifications.

### 3.3 Transactional subscription checkpoints

Event Log `EvtSubscribe` callbacks are not inherently database transactions. Implement a durable ingestion boundary:

1. Read event and identify `channel+provider+record ID`, source timestamp and bookmark XML.
2. Sanitize payload in memory before persistence; if sanitization fails, persist an explicit **redacted error stub** (not unredacted content) and count the lost enrichment.
3. `BEGIN IMMEDIATE`; `INSERT ... ON CONFLICT DO NOTHING` for event IDs; persist any normalized observations and the bookmark advancing **only through durable input**; `COMMIT`.
4. Replayed events are idempotent; source checkpoint and event records must never diverge under crash injection.
5. Handle `ERROR_EVT_INVALID_BOOKMARK`, log cleared, record overwrite/retention, altered channel access, provider absent: detect coverage gap; attempt supported earliest-available backfill; if only future subscription remains possible, clearly mark unavailable interval. Do not silently reset-to-future.

Check multi-event batching, WAL checkpoint behavior and queue overload. A separate `source_record_id` dedupe key alone may collide across providers/channels/log rotations; include provider/channel and log generation/capability context in canonical dedupe design.

## 4. Enrichment and causality

### 4.1 CWD, executable type and Git worktrees (`correlator/peb_git.py`)

- Read live CWD through supported means (`psutil`/native APIs) with documented privilege/bitness limits, only while the process exists. PEB `RTL_USER_PROCESS_PARAMETERS` is best-effort and OS-implementation-sensitive. Do not assert `CREATE_NO_WINDOW` absent/present by reading `WindowFlags` alone.
- Inspect PE subsystem independently where practical; console (`CUI`) vs GUI is useful evidence, but not proof a popup was created.
- Resolve `.git` worktree pointers and `git rev-parse --show-toplevel`/current branch from a trustworthy CWD or script path; cache results by filesystem location and bound Git invocation timeouts.
- Keep evidence for originating command path, resolved repo path, worktree, branch and (optionally) commit. Do not traverse untrusted path content as executable shell commands.

### 4.2 Terminal hosting (`correlator/terminal_session.py`)

- Keep distinct identities for initiating client process, classic conhost/OpenConsole, WindowsTerminal.exe host, HWND, and an optional terminal tab/pane association.
- Inspect Default Terminal configuration (`HKCU\\Console\\%%Startup`) read-only and record relevant delegation state. Avoid equating `GetWindowThreadProcessId(hwnd)` to the initiating Python/CMD process.
- Use title, same desktop/session, temporal neighborhood, process/host relationships, and task/agent evidence together; don't rely solely on a 250-ms threshold or a `.venv` title.
- Preserve alternative candidates, including the possibility that the observed window was opened by an interactive user. Do not claim tab/pane GUIDs when the API cannot observe them.

### 4.3 Agent context (`PROCWATCH_CONTEXT`)

- Support opt-in structured, versioned context propagated by *instrumented* launchers. Recommended payload: version, random execution correlation ID, agent kind, agent session, phase/work item, repo/worktree, producer identity. Encode as validated JSON or a canonical safe format rather than unescaped semicolon key/value concatenation.
- Recognize passive heuristic signals (ancestor names, paths, selected non-secret environment keys) separately. Inherited context is *corroborating evidence* and may outlive the initiating agent; never call it automatically 100% certain.
- Initially ingest when present, but do not mutate production launchers in Phase 02; full orchestrator integration and permissions are Phase 04. Provide fixture launchers to validate the contract.
- Elide credentials and restrict env collection. Prefer explicit environment context passed by agent/launcher over PEB walking of foreign processes.

### 4.4 Evidence scoring (`correlator/scorer.py`)

- Score separately: direct process lineage, independent trigger instance, executable/args match, window host, time/session coherence and agent-context provenance.
- Do not sum correlated duplicate source observations as though independent evidence.
- Provide `high`, `medium`, `low`, `unknown`, competing candidates, and textual reasons. Record software scorer/version for future re-evaluation.
- Prevent circular edges and accidental certainty from timestamp proximity alone. `explain` should distinguish **observed owner**, **most likely initiator**, and **unresolved elements**.

## 5. Command delivery

| Command | Phase 02 requirement |
|---|---|
| `procwatch doctor` | **Read-only** capability matrix: Windows build, Python, current terminal delegation, WinEvent/WMI/Sysmon/Task log status, effective access, owner health, SQLite WAL/retention and observed drops; JSON via `-j/--json-output` |
| `procwatch history` | Search recent incidents, filter popup or agent, replay source timeline with timestamp delta, export redacted evidence bundle; maintain source coverage footnotes |
| `procwatch explain` | `-i/--incident-id` or `-p/--pid`: process chain, window host vs initiator, strong/weak evidence, missing data, alternative candidates; `-j/--json-output` versioned |
| `procwatch mark` | Create user timestamp mark with label (`-l/--label`) and matching radius (`-w/--window-seconds`), even while collector owner is running; transaction-safe and no duplicate collector |
| `procwatch watch` / `guard` | Continue functioning through DB lag/restart; when configured, persist observations and guard outcomes. Existing terminal-safe behavior must not regress |

`mark` is a *write* to user data; it is not a read-only command. Concurrent CLI processes should use separate read connections or bounded writer coordination. Read-only `doctor` must not enable Sysmon, change registry settings or create Scheduled Tasks.

## 6. Execution tasks (in order)

1. Inventory Phase 01 implementation and collected test evidence; do not refactor proven guard unnecessarily.
2. Freeze event model v1 and begin SQLite schema/migration fixtures; add source identifiers and event gap representation.
3. Implement durable writer/redactor and atomic bookmark checkpoint API; unit-test crash injection before wiring subscriptions.
4. Integrate existing Sysmon event ingestion, capability detection, record dedupe and historical backfill.
5. Add Task Scheduler Operational ingestion and optional read-only COM task enumeration; distinguish scheduled-task engine events from child process creation.
6. Implement process ID promotion/reconciliation and typed graph edges; migrate provisional Phase 01 live event observations into normalized records without losing original relationships.
7. Add window/terminal host association and Git/worktree enrichment; keep PEB inspection opportunistic and latency-bounded.
8. Ingest versioned agent context and implement conservative scorer + incident grouping; create controlled examples of competing initiators.
9. Deliver history/explain/mark/doctor UI + JSON schema and opt-in export; verify restart behavior, storage caps and redaction.
10. Run Windows integration and the full Phase 01 regression suite; checkpoint and report.

## 7. Verification and phase exit gate

### Storage tests (`tests/storage_test.py`, `tests/redactor_test.py`)

- Clean initialization, zero-data migration, upgrade from each preceding schema version and reject unknown future schema.
- 100% dedupe under repeated event replay and recovery. Use known stable event identity fixtures for Sysmon/task channels.
- Crash injection *before*, *during* and *after* atomic event+bookmark transaction; durable event records and checkpoint are consistent.
- Stale bookmarks/log rollover produce a persisted gap marker; available older records are recovered where feasible.
- Fixed secret fixtures in command lines, decoded PowerShell, XML, agent context, JSONL export, SQLite main database and WAL must not appear in raw form. Run byte-level scans of output artifacts after closing/checkpointing SQLite.
- Time+size retention, database busy contention, queue overload, migration error and disk-full scenarios retain bounded memory usage and report errors without disrupting existing guard.

### Correlation tests (`tests/correlator_test.py`, `tests/ancestry_test.py`)

- WMI start precedes Sysmon create; inverse order; duplicate Sysmon; out-of-order stop; process creation with missing create time; PID reuse; reboot/new boot ID; conflicting PIDs/GUIDs.
- Different process lifetimes within the same coarse time bucket must not merge incorrectly.
- `supersedes` relationships don't invalidate incident foreign keys or evidence IDs; replay is idempotent and alternatives survive.
- Windows Terminal host PID differs from launching client PID; title heuristic alone does not imply causation.
- Task action matching with multiple candidates, no parent data, no source permission; unknown/low confidence rather than fabricated task name.
- Git resolution across `.git` file worktree structure; branch detached, repo absent, process CWD inaccessible.
- Agent inherited context vs trusted instrumented IDs; malformed context does not crash or become trusted.

### Controlled Windows integration scenarios

- Sysmon enabled/configured (if already present), Sysmon absent, Sysmon channel access denied, Task Operational disabled or unavailable, WMI trace working. Record active capabilities for every run.
- After collector restart, replay existing event-log records without duplicating incidents or skipping records. Simulate crash during in-flight batch.
- Correlate synthetic task/agent launches with windows and process trees where evidence exists. Historical records without live window events must be labeled `process_only`/`visibility_unobserved`.
- Continue verifying guard/no user terminal suppression from Phase 01; durable writer must not block window callbacks.
- Query/export with secrets injected; exported JSON should be self-contained, redacted, schema-versioned and include evidence IDs, not copied screenshots or raw environments.

### Exit criteria

1. `history`/`explain`/`mark`/`doctor` run with documented CLI contracts; `doctor` is side-effect-free with respect to Windows system settings.
2. Event Log replay/deduplication/transaction tests pass; gaps are visible and no continuity is invented.
3. Process identity matching handles tested PID reuse and retains unresolved cases.
4. `explain` produces a realistic evidence summary with window-owner-vs-trigger distinction, including competing candidates where applicable.
5. No known test fixture secrets are recoverable from SQLite/export artifacts; limitations of best-effort redaction disclosed.
6. Capture rate, source availability and coverage must be **measured** on actual Windows configuration; no universal zero-miss promises.
7. Phase 01 guard tests remain green; no unapproved Windows configuration or local LLM inference.

## 8. Files, artifacts and status report

Primary source files: `storage.py`, `redactor.py`, `collectors/sysmon_evt.py`, `collectors/task_events.py`, `correlator/engine.py`, `terminal_session.py`, `peb_git.py`, `scorer.py`, CLI/renderers, tests. Update schema documentation, data privacy policy, and user-facing source coverage explanations. Provide sample redacted incident JSON, DB migration history, replay test evidence, benchmark and OS/build/capability matrix, branch/commit and tests. Gate Phase 03 on demonstrated durable history and a stable incident query interface.

## 9. Source verification links

- [Sysmon overview](https://learn.microsoft.com/en-us/windows/security/operating-system-security/sysmon/overview)
- [Sysmon event categories](https://learn.microsoft.com/en-us/windows/security/operating-system-security/sysmon/sysmon-events)
- [Built-in Sysmon setup prerequisites](https://learn.microsoft.com/en-us/windows/security/operating-system-security/sysmon/how-to-enable-sysmon)
- [Original detailed source](../sources/02_gemini_detailed_plan_original.txt)
