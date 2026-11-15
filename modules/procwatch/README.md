# `procwatch` (v0.4.0)

Windows 11 live console/terminal popup guard, SQLite WAL flight recorder, causal attribution engine, static/system auditor, periodicity analyzer, and Windows Job Object headless supervisor.

## Implemented Capabilities (Phases 1–4)

1. **Live Window & Process Guard (`watch`, `guard`):**
   - `SetWinEventHook` + `MsgWaitForMultipleObjects` observer for `CREATE`, `SHOW`, `DESTROY`, `NAMECHANGE`, and `FOREGROUND` transitions.
   - Safe `observe` (default), `smart` (positive automation evidence only), `all-consoles`, and `all-windows` modes with window style/placement/foreground-lock restoration.
   - `Win32_ProcessStartTrace` / `Toolhelp32` process ancestry cache, payload decoders (`-EncodedCommand`, `cmd /c`, `wsl -e`), and pre-output secret redaction.
2. **Persistent Flight Recorder & Attribution (`doctor`, `history`, `explain`, `mark`):**
   - SQLite WAL storage (`~/.procwatch/events.db`, schema v2) with atomic Event Log bookmark checkpoints (`Sysmon/Operational`, `TaskScheduler/Operational`), `IngestGap` tracking, provisional-to-canonical `SUPERSEDES` reconciliation, and age/size retention pruning.
   - Live CWD, PE `CUI`/`GUI` subsystem, `.git` worktree/branch resolution, `HKCU\Console\%%Startup` read-only delegation inspection, and `PROCWATCH_CONTEXT` attribution.
3. **Static Scanner, System Auditor & Pattern Analyzer (`scan`, `audit`, `analyze`):**
   - Python `ast` and PowerShell `System.Management.Automation.Language.Parser` scanners with `git worktree list --porcelain` discovery, unified diffs, dirty-file guards, and SHA-256 verified backups.
   - Read-only Task Scheduler, Registry `Run`/`RunOnce`, Startup folder, and Default Terminal auditing.
   - Privacy-safe command signature normalization, periodic/burst detection, and coverage-normalized baseline comparisons.
4. **Headless Supervisor (`exec`):**
   - Runs background commands under `CREATE_NO_WINDOW` (`headless` profile) and Windows Job Objects (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`) with concurrent bounded `stdout`/`stderr` capture, truncation accounting, timeout/cancellation tree cleanup, `PROCWATCH_CONTEXT` propagation, and SQLite run telemetry.
   - **Caveat:** `exec` is designed for non-interactive background commands; child processes that explicitly allocate their own GUI/console windows or break away from a nested job are reported in `RunResult` rather than silently suppressed.

## Usage Examples (PowerShell)

```powershell
# 1. Inspect collector readiness, terminal delegation, and DB health (read-only)
procwatch doctor -v

# 2. Observe popups live with smart guard and persistent recording
procwatch watch -p -g -m smart

# 3. Query recent popups and explain a specific incident
procwatch history -t 24h -p
procwatch explain -i 1

# 4. Scan a repository (and active worktrees) for unintended console launches
procwatch scan -d C:\path\to\repo -w -u

# 5. Audit Windows Scheduled Tasks, Startup folders, and Default Terminal (read-only)
procwatch audit -t all

# 6. Detect 10s polling loops and compare against a 24h baseline
procwatch analyze -p -w 3600 -b 24h

# 7. Run a background command headlessly with bounded capture and Job Object cleanup
procwatch exec -t 30 -j -- python.exe -m scripts_help --help
```
