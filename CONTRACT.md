# Shared Launchers and Invocation-History Contract

**Version:** 0.2.0  
**Specification Level:** Canonical Reference Architecture

This document defines the formal behavioral, structural, and privacy contracts for the Scripts Toolkit shared launchers and invocation-history infrastructure.

---

## 1. Canonical Program Identity

Every command-line entry point recognized by the toolkit maps to a globally unique `program_id`:

| Target Type | Format | Example |
| :--- | :--- | :--- |
| Core Module Script | `module:<package_name>` | `module:script_logging` |
| Standalone Python Script | `pyscript:<repo_relative_path>` | `pyscript:pyscripts/system_report.py` |
| Shell Script | `shell:<repo_relative_path>` | `shell:shell-scripts/backup.sh` |
| Unmanaged / Ad-hoc Command | `command:<invoked_name>` | `command:my_custom_tool` |

### Invariants:
- `invoked_name`: The alias or command name actually invoked (e.g. `mangadl` vs `manga-download`).
- Multiple aliases for the same tool share the same `program_id`.
- The combination `(invoked_name, program_id)` in `alias_usage` tracks usage per alias.

---

## 2. Invocation Lifecycle & Status Semantics

An invocation progresses through an explicit, transaction-safe lifecycle:

```
[Start Invocation]
       │
       ▼
    started ───► launch_failed   (target missing, permission denied, OS error)
       │
       ├───► interrupted         (SIGINT / Ctrl+C / KeyboardInterrupt)
       │
       └───► exited              (normal completion with child exit code)
```

| Status | Terminal | Meaning |
| :--- | :--- | :--- |
| `started` | No | Child process has been recorded and spawned; waiting for completion. |
| `exited` | Yes | Child process completed normally; `exit_code` reflects genuine returncode. |
| `launch_failed` | Yes | Target process could not be spawned (target missing, bad permissions, OS error). Exit code is typically `127`. |
| `interrupted` | Yes | Process terminated prematurely by signal (SIGINT, Ctrl+C). Exit code reflects signal or `130`. |
| `unknown` | Yes | Reconciled orphaned start record where process completion was never reported (e.g. power loss). |

### Fail-Open Invariant:
Database unavailability, schema mismatches, disk quota exhaustion, or concurrency locks MUST NEVER prevent genuine script execution. If SQLite fails:
1. The error is silently tolerated (or logged only when `SCRIPT_LOGGING_DEBUG=1`).
2. The target child process is executed with exact stdio and environment inheritance.
3. The genuine exit code of the target process is returned.

---

## 3. Windows Argument Fidelity & Escaping Nuances

The launcher execution engine guarantees transparent argument fidelity between the caller and the target program. When invoked via native Windows `.cmd` wrappers, the following platform-specific parser rules apply:

### 3.1 Direct Launcher Execution (`launcher.py`)
- Standard Win32 `CreateProcessW` argument escaping is preserved with 100% fidelity.
- Spaces, empty arguments (`""`), quotes, unicode (UTF-8, Japanese, emojis), literal backslashes, and dashes (`--`) are passed without alteration.

### 3.2 Windows Batch Expansion (`%*` in `.cmd` Wrappers)
Native `.cmd` wrappers forward arguments via `%*`:
```cmd
@echo off
"%_VENV_PY%" -m script_logging.launcher --manifest "%_MANIFEST%" --command <name> --wrapper "%~f0" -- %*
exit /b %ERRORLEVEL%
```

Nuances observed and verified:
1. **Empty String Arguments (`""`)**:
   - `cmd.exe`: Passes `""` through `%*` preserved when quoted.
   - PowerShell 7 (`pwsh`): Under default legacy argument passing for batch files, PowerShell strips empty strings `""` unless passed as escaped quotes `'""'` or with `$PSNativeCommandArgumentPassing = 'Standard'`.
2. **Quotes Inside Arguments**:
   - In CMD batch `%*`, double quotes embedded within an argument must be escaped (e.g. `\"`) so that CMD does not strip quotes during batch line parsing. Single quotes (`'`) are treated as literal characters by CMD.
3. **Metacharacters (`&`, `|`, `<`, `>`, `^`, `%`, `!` )**:
   - When wrapped in double quotes (e.g. `"foo & bar"`), metacharacters are safely forwarded through `%*`. Unquoted metacharacters act as CMD shell control operators.
4. **Exit Code Propagation**:
   - Batch wrappers use `exit /b %ERRORLEVEL%` ensuring child exit codes (0, 1, 42, 127, etc.) propagate identically to caller shell environments.

---

## 4. Privacy & Redaction Policy

Raw command-line arguments are treated as potentially sensitive data:

1. **Explicit Credential Scrubbing**:
   - Flags matching sensitive patterns (e.g. `--token`, `--api-key`, `--secret`, `--password`, `-p`) have their values replaced with `[REDACTED]`.
   - Both inline `--token=<secret>` and split `--token <secret>` formats are sanitized.
2. **URL Userinfo and Query Scrubbing**:
   - Embedded credentials in URLs (e.g. `https://user:pass@example.com/`) are replaced with `https://[REDACTED]@example.com/`.
   - Query strings containing credentials or authorization keys are redacted.
3. **Truncation Bounds**:
   - Argument vectors exceeding length boundaries are truncated with explicit marker tokens `[TRUNCATED: +N args]`.
   - Individual strings exceeding maximum string length are truncated with `...[TRUNCATED: N chars]`.
4. **SHA-256 Pattern Fingerprinting**:
   - The aggregated pattern fingerprint (`pattern_id`) is computed exclusively over redacted arguments to avoid leaking unique secrets in usage metrics.

---

## 5. Storage & Database Schema

Database path resolution:
- Windows: `%LOCALAPPDATA%\ScriptsToolkit\invocations.sqlite3`
- macOS: `~/Library/Application Support/ScriptsToolkit/invocations.sqlite3`
- Linux / POSIX: `${XDG_STATE_HOME:-~/.local/state}/scripts-toolkit/invocations.sqlite3`
- Override: `SCRIPT_LOGGING_INVOCATION_DB` environment variable.

Configuration:
- SQLite `journal_mode = WAL`
- `synchronous = NORMAL`
- `busy_timeout = 15000` (15 seconds)

---

## 6. Public Read-Only Query API

The `script_logging.reader` module provides `ReadOnlyHistoryReader`:
- Uses SQLite URI `file:<path>?mode=ro`.
- Will **never** create missing directories, create missing database files, or acquire write locks.
- Provides cursor-based keyset pagination with stable Base64-encoded cursors over `(started_epoch_ms DESC, invocation_id DESC)`.
