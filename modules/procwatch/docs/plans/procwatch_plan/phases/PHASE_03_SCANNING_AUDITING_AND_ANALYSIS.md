# Phase 03 — Static Scanner, Windows Trigger Auditor & Pattern Analysis

**Priority:** P1.  
**Prerequisites:** [Master Plan](../MASTER_PLAN.md), completed [Phase 02](PHASE_02_FLIGHT_RECORDER_AND_ATTRIBUTION.md) with durable incidents and coverage metadata.  
**Next:** [Phase 04 — Headless Runner & Orchestrator Integration](PHASE_04_HEADLESS_SUPERVISOR_AND_INTEGRATION.md).

## 1. Outcome

Turn ProcWatch from an observer into a **source-specific diagnosis and remediation planning tool**. Identify potentially unwanted console-launching code in Python and PowerShell, inspect likely Windows startup/Task Scheduler triggers, analyze repetitive process/popup patterns, generate conservative reviewable diffs, and quantify observed popup rates before/after a proposed fix.

This phase should help an agent answer: *Which source call or task action is likely responsible, what exactly should be changed, what risks does that change introduce, and did observed behavior improve?* It must **not** silently modify live programs or Windows task settings. Default mode is read-only analysis.

### Scope decisions

- **Python + PowerShell only** for source scanning. Future Go, Node, C++ and batch adapters are optional extensions, not implementation prerequisites.
- `analyze -b/--baseline-window` implements regression/baseline comparison. No standalone `procwatch compare` command in this ten-command interface.
- A `subprocess.run()` call without `CREATE_NO_WINDOW` is a **candidate**, not automatically a bug. An interactive process with an attached console often should retain current behavior.
- A PowerShell `Start-Process` without `-WindowStyle Hidden` is similarly not intrinsically wrong; other flags and environment context matter.
- Task XML backup is necessary but not sufficient for rollback: preserve original principal, actions, working directory, triggers, conditions, settings and permissions and verify restoration on test tasks.

## 2. Static scanner design (`procwatch/analyzers/ast_scanner.py`)

### 2.1 Discovery and scope

- `-d/--directory <path>` defaults to the working directory; traverse only requested root, honors `.gitignore` (configurable), excludes `.venv`, `node_modules`, generated/build output and vendored code by default.
- `-w/--include-worktrees` discovers active worktrees with `git worktree list --porcelain`; parse fields correctly, handle spaces/unicode/detached HEAD and missing folders, do not assume `.worktrees/` layout.
- No automatic edits to worktrees managed by active agents. Before applying anything, check `git status --porcelain` per repository/worktree, file ownership/permissions, encoding and current HEAD and inspect concurrent agent activity.
- Preserve source path, line, column, language, detected launch mechanism, surrounding function/file, confidence, potentially corresponding ProcWatch incident IDs and validation status.

### 2.2 Python adapter

Analyze AST calls including:

- `subprocess.run`, `.Popen`, `.check_call`, `.check_output`, `.call` and aliases/imported variants where resolvable;
- `asyncio.create_subprocess_exec` / `create_subprocess_shell`;
- `os.system`, `os.popen`, known wrapper functions, and `shell=True` cases;
- relevant parameters: `creationflags`, `startupinfo`, `shell`, `stdin/stdout/stderr`, `cwd`, executable and platform guards.

Avoid overly broad judgments about dynamic calls. Classify:

1. **Incident-linked launch** (runtime evidence identifies source call or script with plausible causal link).
2. **Likely unintended visible launch** (background module/task and no relevant prevention).
3. **Potential issue** (insufficient execution-context evidence).
4. **Intentional interactive** (evidence or declared configuration indicates this is desirable).
5. **Unknown / dynamic** (indirection, unresolved imports, wrapper, conditional flags).

Use `ast` for detection and optional `libcst` for formatting-preserving edits. A suggested fix should consider alternatives: inherited-console execution, `STARTUPINFO`, `CREATE_NO_WINDOW`, `DETACHED_PROCESS`, wrapping via Phase 04 `procwatch exec`, or making the parent GUI-safe. Never inject the same flag twice or replace a valid interactive path.

**Safety:** For a file with uncommitted changes, `-a/--apply-fixes` must refuse by default; even `-f/--force` may proceed only with the user's explicit authorization and preservation/backup of the pre-edit bytes. Do not alter a concurrently edited worktree. Do not use string replacement for Python code rewrites; insist on parseable output and a content hash check against the analyzed revision.

### 2.3 PowerShell adapter

Use `System.Management.Automation.Language.Parser` / AST from supported PowerShell host (with explicit spawn timeout, no arbitrary script execution). Analyze:

- `Start-Process` including `-WindowStyle`, `-NoNewWindow`, `-PassThru`, `-Wait`, redirection and argument lists;
- native command invocation and `cmd /c`, Start-Job and other common background-launch wrappers (analysis-only where AST cannot establish actual window behavior);
- PowerShell launcher flags such as `-WindowStyle Hidden`, `-EncodedCommand`, and platform conditions.

Microsoft states `Start-Process -WindowStyle` and `-NoNewWindow` cannot be combined. A proposed fix must not introduce invalid parameter combinations. PowerShell's `-WindowStyle Hidden` is not equivalent to Python's `CREATE_NO_WINDOW` in every context. Record warnings and avoid auto-fix where semantics are unknown.

Source scanner output should include source provenance, one or more suggested solutions, expected impact and test recommendations—not only “missing flag.”

## 3. Windows trigger auditor (`procwatch/analyzers/task_auditor.py`)

### Read-only discovery

Inspect only accessible, supported sources initially:

- Task Scheduler tasks: task path/name, enabled status, trigger summary, executable and arguments, working directory, principal/run level, hidden flag, execution timing/history if available, and recorded evidence linking task instance to process/popup.
- Registry Run/RunOnce entries for current user (and accessible machine hives), startup shortcuts and common Startup folders; resolve link targets where permitted.
- Default Terminal delegation under `HKCU\\Console\\%%Startup` (`DelegationTerminal`/`DelegationConsole`), reported as diagnostic context, not a popup root cause by itself.
- Services or WMI permanent consumers can be recorded as **deferred audit extensions** if evidence indicates involvement; don't overextend this phase.

Task evidence ranking should be separated into three classes: **configured to run an executable**, **observed to trigger**, **linked to an observed popup**. A configured `python.exe` action alone is not proof of a popup.

### Remediation planning

- For an incident-linked task, propose specific alternatives: adjust application launch flags, run through Phase 04 supervised wrapper (only once available), change task action to a verified headless entrypoint, or modify original code to stop unnecessary console allocation.
- `procwatch audit -a/--apply-task-fix` requires explicit authorization and a separate preview containing original vs proposed action/arguments, working directory, principal context and logging changes.
- Export complete task XML to `~/.procwatch/backups/` and checksum it **before** change; restore on failure. Do not overwrite the same backup without versioning; never modify unrelated tasks.
- If Phase 04 `exec` does not exist yet, do **not** change a task to call it. Phase 03 can generate a *future* fix proposal but cannot apply a dangling executable reference.
- Avoid changing default terminal or global system preference as a purported fix for one background command.

## 4. Periodicity, burst, and regression analysis (`procwatch/analyzers/patterns.py`)

### Required algorithms

- Derive a stable, privacy-safe process signature: normalized executable+argv skeleton, root/candidate parent, worktree/task identity when available. Normalize volatile PIDs, timestamps, temp paths and credentials without collapsing unrelated commands indiscriminately.
- Group bursty process spawns, measure count per time window, interarrival median/spread and credible recurrence interval (e.g., approximate 10-second repeated probes). Preserve individual incidents.
- Detect a meaningful new pattern against an explicit earlier baseline, accounting for collection uptime, provider availability, source gaps, different session lengths and system sleep/reboot.
- Report **observed** popup rate per collector-covered hour, not just raw counts. Distinguish `window_observed`, `process_only` and `likely` states.
- Before/after comparison: explicit start/end timestamps, same filter and source capabilities, rate ratio or difference and confidence/uncertainty where sample sizes justify it; flag when insufficient evidence prevents a conclusion.
- Avoid automatic causality statements based only on temporal proximity to a code change or agent session.

### Outputs

Provide human-readable tables and JSON versioned events usable in an agent handoff, for example:

```json
{
    "schema_version": 1,
    "pattern": "recurring_command",
    "window_coverage_hours": 2.0,
    "observed_count": 34,
    "median_interval_seconds": 10.1,
    "candidate_trigger": "Task Scheduler: candidate only",
    "confidence": "medium",
    "coverage_warning": null
}
```

This is an illustrative schema example, not actual observed data.

## 5. CLI contracts and safety modes

### `procwatch scan`

- `-d/--directory`, `-w/--include-worktrees`, `-u/--unified-diff` (reviewable diff default), `-a/--apply-fixes`, `-f/--force`, `-j/--json-output`.
- Default prints structured findings and suggested patch. JSON mode must not print extraneous progress to stdout; errors go to stderr.
- `--apply-fixes` changes only reviewable/verified high-confidence candidates, and only after authorization; it refuses untested dynamic constructs and confirms content hashes.
- Never infer that a missing flag automatically needs insertion. Diffs that require changing imports/platform guards should be complete, parseable and runnable.

### `procwatch audit`

- `-t/--target-type all|tasks|startup|defterm`, `-n/--task-name`, `-a/--apply-task-fix`.
- `audit` defaults to inspection with a ranked explanation, incident linkage and proposed remedy. `-a` is explicit user-approved mutation only. If dependencies are missing, give a preview and mark `not_applicable_yet`.

### `procwatch analyze`

- `-p/--periodicity`, `-b/--baseline-window`, `-w/--window-seconds`, `-j/--json-output`.
- Explicit coverage-aware baselines and regression comparisons; no separate top-level `compare` command.

## 6. Execution tasks (in order)

1. Establish stable Phase 02 incident schema, evidence references, and source gaps; add sample redacted incident fixture bundle.
2. Implement repository/worktree discovery and Python AST scan with path exclusions and robust alias detection; test without modifying files.
3. Add PowerShell parser adapter, including supported installed PowerShell runtime detection and parse error reporting.
4. Implement risk classification linked to recorded incidents, reviewable unified diffs, and LibCST patch prototyping on disposable fixtures.
5. Implement read-only Task Scheduler/Startup/Run/DefTerm inventory and matching to evidence graph.
6. Add strict task backup, preview, and explicit apply-only path (if permission provided). **Never apply a Phase 04 wrapper fix before Phase 04 exists.**
7. Implement periodicity grouping, coverage-adjusted baseline comparison and stable JSON output.
8. Integrate UI and evidence exports; document regression workflow.
9. Execute unit, integration and no-mutation test suite, verify source and system state unchanged by default, checkpoint tested work.

## 7. Tests and acceptance gates

### Scanner tests — `tests/ast_scanner_test.py`

- Python subprocess direct/import aliases, nested async calls, platform guarded flags, alternate valid `startupinfo`, interactive/TTY scenarios, shell wrappers, dynamic unresolved cases.
- PowerShell `Start-Process` combinations including `-WindowStyle Hidden`, `-NoNewWindow` conflict, quoting, splatting and invalid syntax.
- Worktree list parser handles spaces, nested worktrees, detached HEAD, absence of Git, inaccessible folders and missing files.
- Generated diffs have exact expected modifications and no false edits; Python output re-parses and builds; tests record file hash before/after non-apply scan.
- Dirty files remain untouched without explicit authorization, even when `-f` is present without `-a`. Make sure source was not silently rewritten from automatic formatting.
- Running `scan -j` produces stable schema and valid parseable JSON only.

### Auditor tests — `tests/task_auditor_test.py`

- Mock task XML and action paths, different triggers/principals/working dirs, explicit task permissions, disabled Task Scheduler Operational log, duplicate candidate tasks.
- Read-only audit never calls RegisterTask/SetTask/registry write APIs.
- Apply on disposable task has intact XML backup and tested restore path; applied action references a runnable, installed target (no dangling wrapper).
- Global terminal delegation not changed by a targeted remediation.

### Analyzer tests — `tests/patterns_test.py`

- Known 10-second recurring burst with ± jitter, irregular unrelated launches, duplicate raw-event source reports, sleep/reboot gaps, timestamp disorder and different coverage intervals.
- Before/after comparison correct for observation hours and source availability, including “insufficient coverage” outcome.
- Repeated analysis is deterministic for the same input and doesn't delete raw incidents.

### Phase exit gate

- `scan`, `audit`, `analyze` conform to CLI and structured JSON contracts.
- Scan finds supplied fixture defects while **not treating every command launching a shell as broken**; source-preserving diffs pass syntax/behavior tests.
- Default execution of the three commands modifies **zero files/tasks/registry values** in automated tests and on the integration host.
- Explicit apply to a disposable clean fixture has backup/restore behavior and a clear authorization audit trail. User production tasks remain unchanged unless authorized.
- Periodicity detection and baseline comparison account for source gaps and return evidence-backed findings, including inconclusive outcomes.
- Output can be used to prepare a focused code/task correction and test it against a newly reproduced incident.
- No real background worker shutdown or local LLM inference without authorization.

## 8. Artifact/checkpoint expectations

Deliver scanner and auditor tests, representative unified diffs for fixture issues, read-only task audit redacted output, a sample 10-second-process-loop analysis, before/after calculation examples, data privacy and rollback docs, and an explicit statement of any unsupported PowerShell/Windows build behavior. Report branch/commit, command outputs, test count, meaningful false-positive examples, and known limitations before Phase 04.

## 9. Source references

- [PowerShell Start-Process supported window styles](https://learn.microsoft.com/powershell/module/Microsoft.PowerShell.Management/Start-Process)
- [Original Gemini source and Phase 03 feature list](../sources/02_gemini_detailed_plan_original.txt)
