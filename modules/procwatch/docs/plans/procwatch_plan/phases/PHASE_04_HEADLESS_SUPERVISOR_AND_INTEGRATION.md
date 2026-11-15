# Phase 04 — Observable Headless Supervisor, Agent Integration & End-to-End Verification

**Priority:** P1, final planned implementation increment.  
**Prerequisites:** [Master Plan](../MASTER_PLAN.md), completed [Phases 01–03](../README.md), tested Windows 11 host, permission to modify targeted launchers/tasks where applicable.  
**End state:** ProcWatch is usable as a persistent observation-and-diagnosis tool, safe optional popup guard, static/task analyzer, and supported background-process supervisor. The separate agent handoff will be prepared later, outside this ZIP.

## 1. Outcome

Implement `procwatch exec`: an explicitly invoked **headless subprocess supervisor** which (for supported console programs) does not open an unwanted terminal, records command, redacted bounded stdout/stderr, exit code, duration, and subprocess-tree lifecycle, and propagates opt-in `PROCWATCH_CONTEXT` attribution. Integrate first with disposable wrappers, then optionally with approved existing CLI-agent/scheduler launchers. Complete controlled end-to-end Windows validation and report observed improvements without overstating guarantees.

Unlike a retroactive buffer scraper, supervised execution controls the child's standard handles from launch and can capture stream content reliably for compatible programs. It is not a terminal emulator: interactive programs requiring a real TTY/console, programs that open their own windows, descendants escaping the job, or elevation/desktop-crossing scenarios need explicit caveats or alternative execution profiles.

## 2. Supervisor design (`procwatch/runner/supervisor.py`)

### 2.1 Launch API and profiles

- Expose library API `execute(argv: Sequence[str], *, cwd, env_overrides, profile, timeout, output_limits, context) -> RunResult` (exact names may vary as long as CLI/public contract remains stable).
- Default initial profile: `headless` using `subprocess.CREATE_NO_WINDOW` for eligible Windows console programs with `stdout/stderr=PIPE` and appropriate stdin; no shell interpolation by default.
- Allow explicit `inherited-console` for compatible foreground workflows. A later optional `conpty` profile is deferred; do not claim ConPTY without implementing PTY session management and tests.
- Support both `procwatch exec -c/--command <argv...>` and a raw `-- <argv...>` delimiter for robust argument passing. The parser must not silently join strings and reinterpret quoting.
- Working-directory argument `-w/--working-dir`; validate executable/path, show useful errors; preserve Unicode and paths with spaces.
- Optional timeout `-t/--timeout-seconds`, nonzero-exit notification `-k/--keep-console-on-error` (historical source name—document that the wrapper should notify non-intrusively rather than magically reopen a console). Short flags are single dash and long flags double dash.
- Program exit code is returned faithfully unless ProcWatch itself failed (then use documented distinct exit codes). Timeout/cancellation status is distinct from child failure.

### 2.2 Windows Job Objects and descendant management

- Use `CreateJobObjectW`, `AssignProcessToJobObject`, process handle management, and `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` where appropriate.
- Address race between spawning child and assigning it to a Job Object: evaluate starting suspended before assignment then resuming (including cleanup on assignment failure) for workloads where descendant containment is required. This requires careful implementation/testing.
- Respect pre-existing job membership, permitted nested job behavior and child breakaway. A job is not a universal kill guarantee; report when assignment is denied or a descendant is outside the managed set.
- On timeout or explicit cancellation: request clean shutdown where supported, allow bounded grace period if configured, then terminate **controlled** job/process tree; don't terminate unrelated processes by PID alone. Avoid accidental process creation or new console on error.
- Close all handles, read stdout and stderr concurrently and finish draining pipes after child exit; avoid deadlock when one stream fills.
- Never invoke arbitrary subprocesses through `shell=True` unless a separate explicit documented shell mode is requested. Protect command string/argv in logs through redaction.

### 2.3 Output, retention and failure reporting

- Capture stdout/stderr as distinct ordered chunks with timestamps and source, acknowledging that independent streams have no globally guaranteed original interleaving.
- Enforce byte limits per stream, total job, and retention; if truncated, store an explicit truncation marker and count dropped bytes.
- Decode with configurable encoding and robust replacement handling without mangling raw binary outputs or logging secrets to exception traces; keep sensitive content transient until scrubbed.
- Persist `RunResult`: execution_id, executable/argv(redacted), cwd, UTC start/end, monotonic duration, exit code or status (`timeout`, `launch_failed`, `cancelled`, `unknown`), assigned job status, output-limits and metadata.
- SQLite writer backpressure must never deadlock child pipe readers. Stage bounded sanitized chunks and report losses. If DB unavailable, preserve process safety, report degraded logging and choose a documented fallback (e.g., bounded local redacted JSONL) without writing secret-rich raw dumps.
- Failure alert should be non-intrusive and conditional; it must not start a new popup console. The source `--keep-console-on-error` is retained for CLI compatibility, but actual behavior is notification/logging.

## 3. Agent/orchestrator context and integrations

### 3.1 Versioned context contract

Adopt the Phase 02 `PROCWATCH_CONTEXT` contract:

```json
{
    "version": 1,
    "execution_id": "<new random correlation ID>",
    "agent": "codex",
    "agent_session": "<opaque ID>",
    "phase": "validation",
    "repository": "<repo path>",
    "worktree": "<worktree path>",
    "producer": "<instrumented launcher identity>"
}
```

This is a *schema example*, not a known current value. Whitelist fields and length limits; do not place API keys, credentials, complete unfiltered environments, or user secrets in this variable. Validate/normalize untrusted data; distinguish inherited context from verified wrapper-authored execution IDs.

- Direct ProcWatch supervised runs receive an execution ID and the corresponding run record.
- Child processes can inherit context when intended; passive process observations can then be correlated with run IDs, but provenance is recorded as `instrumented`/`inherited`/`heuristic` and not silently treated as proof.
- No need to modify an existing agent's implementation to get core features; passive process observation continues working.
- On Windows, environment variables can persist through nested descendants or be forged; report trust accordingly. Keep marker format/version stable.

### 3.2 Target integration and approval policy

Gemini's source refers to `local_agent_bridge` and `scheduler`; the user's broader workflows may use other wrappers/CLI telemetry. **Discover actual names/paths from the repository during implementation rather than assume those modules exist.** First integrate on a disposable fixture wrapper; inspect ownership and active agents before touching production wrappers.

Possible approved integration points: central script launcher, CLI agent dispatcher, scheduled background worker, notification service, repository validation runner. The order of preference is:

1. Instrument launcher context only (non-behavior-changing, with agent/test authorization).
2. Replace one targeted problematic launch with `procwatch exec` using explicit consent and recorded rollback.
3. Scale to other launches after measured benefit and regression validation.

Do not independently install auto-start tasks or change a live Scheduled Task as part of a test. Do not terminate, restart, or drive local LLM inference. Any new persistent background task requires explicit authorization and an uninstall/rollback procedure.

## 4. End-to-end integration harness (`tests/integration_win32_test.py`)

### 4.1 Ground truth independence

The harness must create synthetic launch sequences and record independently known spawn/exit/parent/window/foreground facts *outside* ProcWatch's event pipeline. It should support both positive tests (popup intended from a disposable background command) and negatives (interactive terminal intentionally opened).

- 20 ms-ish simple process lifetime fixtures, plus longer-lived ones; capture start/stop/PID with a separate test controller, not inferred from ProcWatch's own DB.
- Parent exits before child; nested CMD/PowerShell/Python venv launcher; multiple near-simultaneous launches; PID reuse stress where practical; reboots or simulated boot IDs.
- Both Windows Terminal and classic Console Host/default-terminal preference where the test machine supports them; record selected mode/build.
- Foreground focus sensitive tests while active typing/mouse drag; no unintended window minimization in smart/observe mode.
- Known task trigger and known instrumented agent context with correlated execution ID; `explain` should identify them where evidence is observed.
- Crashes, DB busy, event log disabled/cleared, stale bookmark, WMI failure, queue saturation, duplicate owner, post-restore intentional window launch.
- Bounded `exec` output (large stdout/stderr), nonzero exit, Unicode, command with spaces, shell flags and timeout/cancellation/job children.
- Strictly separate `window_observed` from historical `process_only` after replay.

### 4.2 Metrics and quality gates

| Metric | Required reporting | Acceptance interpretation |
|---|---|---|
| Process-start recall | Observed/ground-truth under each configured source set and lifetime bin | Source's `≥95% at 20ms` is a **conditional target** to evaluate per scenario, not a universal release promise; missing data explained |
| Window-observation recall | Observed windows/ground-truth windows while hook active | Report source coverage and exactly which cases failed |
| Smart guard false positives | Suppressed legitimate new windows / intentionally launched control windows | **0 observed in defined test suite** plus sample size; fail release on any observed unintended suppression until fixed |
| Guard latency | Process/window start to hook, decision, actual minimize/focus effect | Measure distribution (median/p95/max) and test machine; `MsgWaitForMultipleObjects` wakeup does not prove entire pipeline <1ms |
| Attribution | Correct primary initiator and alternatives vs independent fixture truth | High confidence only with independent evidence; unknown/low is preferable to false confidence |
| Event log durability | Lost or duplicate committed events across crash/replay tests | No silent missing committed input; idempotent restore; gaps detected where source records unavailable |
| Secret safety | Fixture secret material in DB, WAL, JSONL, errors and exports | No fixture secret leaks; best-effort limits documented |
| `exec` fidelity | Exit status, output capture, duration, timeout/cancel | All defined supported fixture commands meet contracts; no claim for unsupported interactive workloads |
| System overhead | CPU/memory, queue occupancy/drops, storage growth | Record bounded, sustainable behavior; explicit thresholds set from measured baseline before enabling always-on mode |

**Coverage classification:** report `pass`, `fail`, `skipped` (with reason), and `not_available` separately. Do not call an untested feature supported, and do not suppress test errors to meet a numerical KPI.

## 5. Final UI, packaging and operational validation

- Ten CLI commands all appear with stable `-h/--help`, short and long flags, correct exit/error codes; no duplicate phantom `compare` command.
- Portable unit tests run without requiring Win32 imports for pure model/decoder/storage modules; Windows-only tests explicitly skip on non-Windows systems rather than error during collection.
- All events and exports use versioned, documented JSON schemas and redaction; no user secrets in logs.
- Per-user collector ownership prevents duplicate WinEvent hooks; `guard` and `watch` connect to existing owner or fail with actionable error.
- `doctor` reports capabilities, source gaps, collector owner and DB health without making Windows system changes.
- Document installation from supported package method, start/stop, opt-in background/autostart procedure, retention privacy, and complete rollback/uninstall path; **do not execute** system-changing setup without authorization.
- Release README contains copyable PowerShell examples for watch/guard/history/explain/mark/scan/audit/analyze/exec/doctor; examples do not claim performed system actions.
- Compatibility: note native Windows focus; WSL/Linux may be able to consume portable exported evidence but not run Win32 hooks directly.

## 6. Execution tasks (in order)

1. Review Phases 01–03 state and architecture; freeze `RunResult` and `PROCWATCH_CONTEXT` schemas after tests.
2. Build `runner/supervisor.py` with explicit Win32 creation flags, safe argv handling, captured pipe drains, timeout/cancel semantics and process handle management.
3. Add guarded Job Object integration (with assignment/containment reporting) and a safe exit strategy; test job nesting/assignment errors.
4. Integrate storage of redacted output and run metadata with bounded limits, plus error notification without console creation.
5. Implement `procwatch exec` CLI, raw `--` argv behavior, output/exit code contract and help.
6. Implement versioned context propagation in isolated launchers; verify passive and instrumented attribution are distinguished.
7. Identify optional real repository launchers; obtain authorization for any production integration. Preserve active agent processes and worktrees.
8. Expand independent Windows integration harness, collect measured recall, focus outcomes, source gaps, storage/secret test results.
9. Run complete unit + controlled integration tests; examine redacted evidence bundles and compare before/after on synthetic and approved real workloads.
10. Produce release checklist, docs, rollback plan, configuration examples, final agent-style status report and checkpoint commit.

## 7. Tests and acceptance gate

### Supervisor tests (`tests/supervisor_test.py`)

- Standard success and nonzero exit; exact child args with Unicode and spaces, working dir, environment overrides.
- High-volume dual-stream output without pipe deadlock; output truncation with explicit accounting; binary/unexpected encoding.
- Start failure, permission denied, executable not found; no phantom success or missing exit error.
- Timeout and Ctrl+C, child process descendants, clean handles, job assignment failure and simulated existing-job membership.
- Secret fixture not stored in DB/JSONL/notification/log; fallback failure behavior well defined.
- Headless profile produces no unwanted terminal on supported fixtures; intentional interactive commands are classified and not silently broken.
- `PROCWATCH_CONTEXT` trace ID appears in expected child metadata; malformed/untrusted context remains marked heuristic.

### Integration tests (`tests/integration_win32_test.py`)

- Run selected independent scenarios from §4 across active telemetry backends, including `guard` in smart mode and a newly user-opened `wt.exe` terminal.
- Verify Phases 01–03 tests remain green and no regressions in WinEvent callback/SQLite writer latency.
- Validate `doctor` reports an accurate capability matrix; Sysmon-absent scenario does not throw; disabled task log yields explicit degraded coverage.
- Verify opt-in remediation in a disposable task/fixture only. If approval to modify production tasks is not granted, mark production remediation as **not tested**, not successful.
- Evaluate before/after rate reduction on fixed synthetic scenarios with matched window-observation coverage; explicit inconclusive result when observation was insufficient.

### Final project sign-off

The project is ready for user acceptance when: the targeted original popup can be reproduced or reliably matched in a recorded live incident, the guard protects the tested workflow without unintended new-terminal suppression, the evidence graph shows grounded origins/alternatives, durable history and replay work within observed source coverage, scanner/auditor report useful fixes without unapproved mutation, `exec` works for supported background tasks and preserves diagnostics, and a complete result report identifies both passed and untested conditions. Any global system change requires a separate explicit approval.

## 8. Deliverables and verification report

Provide versioned code, package metadata, documentation and tests, measured Windows integration results, redacted incident examples, sample comparison output, SQLite migration/checkpoint evidence, source coverage report, guard A/B and foreground-impact measurements, known limitations, installation/uninstallation guidance, and optional launcher integration proposal. Report exact branch/commit, working-tree status, platform/runtime, commands executed, failures/skips and next decisions. No future agent handoff is generated by this phase plan itself.

## 9. Technical references

- [Windows Job Objects overview / API guidance](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
- [SetWinEventHook semantics](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwineventhook)
- [Sysmon events](https://learn.microsoft.com/en-us/windows/security/operating-system-security/sysmon/sysmon-events)
- [Original detailed source](../sources/02_gemini_detailed_plan_original.txt)
