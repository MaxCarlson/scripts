# Shared Launchers and Invocation-History Contract

**Version:** 0.2.0  
**Specification Level:** Canonical Reference Architecture  
**Status:** Frozen Public Interface for Handoff 3 (`scripts-help`)

This document defines the formal behavioral, structural, and privacy contracts for the Scripts Toolkit shared launchers and central invocation-history infrastructure.

---

## 1. Canonical Program Identity

Every command-line entry point recognized by the toolkit maps to a globally unique canonical `program_id`:

| Target Type | Format | Example |
| :--- | :--- | :--- |
| Core Module Script | `module:<package_name>` | `module:script_logging`, `module:db-manager` |
| Standalone Python Script | `pyscript:<repo_relative_path>` | `pyscript:pyscripts/system_report.py` |
| Shell Script | `shell:<repo_relative_path>` | `shell:shell-scripts/backup.sh` |
| Unmanaged / Ad-hoc Command | `command:<invoked_name>` | `command:custom_tool` |

### Invariants:
- `invoked_name`: The alias or command name actually invoked (e.g. `mangadl` vs `mdl`).
- Multiple aliases for the same underlying program share the same `program_id`.
- Program-level usage counters aggregate across all aliases; alias-level usage counters track invocations per distinct `(invoked_name, program_id)`.

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
| `started` | No | Child process has been recorded and spawned; awaiting completion. Uncompleted runs (e.g. crash/kill/power loss) remain in this state without fake completion rows. |
| `exited` | Yes | Child process completed normally; `exit_code` reflects genuine child returncode. |
| `launch_failed` | Yes | Target process could not be spawned (target executable missing, permissions error, OS error). Exit code is typically `127`. |
| `interrupted` | Yes | Process was terminated prematurely by signal (SIGINT, Ctrl+C). Exit code reflects signal returncode (typically `130`). |
| `unknown` | Yes | Reconciled orphaned start record where process completion was never reported. |

### Fail-Open Invariant:
Database unavailability, schema mismatches, disk quota exhaustion, or concurrency locks MUST NEVER prevent genuine script execution. If SQLite fails:
1. The error is silently tolerated (or logged to stderr only when `SCRIPT_LOGGING_DEBUG=1`).
2. The target child process is spawned with exact inherited environment, working directory, and stdio streams.
3. The genuine exit code of the target process is returned.

---

## 3. Windows Argument Fidelity & Escaping Nuances

The launcher execution engine guarantees transparent argument fidelity between the caller and the target program. When invoked via native Windows `.cmd` wrappers, the following platform-specific parser rules apply:

### 3.1 Direct Launcher Execution (`launcher.py`)
- Standard Win32 `CreateProcessW` argument escaping is preserved with 100% fidelity.
- Spaces, empty arguments (`""`), quotes, unicode (UTF-8, Japanese `日本語`, emojis `🚀`), literal backslashes, and dashes (`--`) are passed without alteration.

### 3.2 Windows Batch Expansion (`%*` in `.cmd` Wrappers)
Native `.cmd` wrappers forward arguments via `%*`:
```cmd
@REM Scripts Toolkit Managed Wrapper v0.2.0
@echo off
setlocal
set "_BIN=%~dp0"
set "_ROOT=%_BIN%..\"
set "_VENV_PY=%_ROOT%.venv\Scripts\python.exe"
set "_MANIFEST=%_ROOT%scripts_manifest.json"
if not exist "%_VENV_PY%" (
  echo [ERROR] Python venv interpreter not found at %_VENV_PY% 1>&2
  exit /b 127
)
"%_VENV_PY%" -m script_logging.launcher --manifest "%_MANIFEST%" --command "%~n0" --wrapper "%~f0" -- %*
exit /b %ERRORLEVEL%
```

Nuances observed and verified:
1. **Direct Execution vs `call` Limitation**:
   - Direct execution (`wrapper.cmd "arg: ^"`) preserves carets `^` faithfully.
   - Calling a wrapper via `call wrapper.cmd "arg: ^"` triggers `cmd.exe`'s internal secondary parser pass, which doubles unescaped carets (`^` -> `^^`).
   - For commands requiring unescaped carets inside `cmd.exe`, callers should invoke the wrapper directly rather than via `call`.
2. **Empty String Arguments (`""`)**:
   - `cmd.exe`: Passes `""` through `%*` preserved when quoted.
   - PowerShell 7 (`pwsh`): Under default legacy argument passing for batch files, PowerShell strips empty strings `""` unless passed as escaped quotes `'""'` or with `$PSNativeCommandArgumentPassing = 'Standard'`.
3. **Quotes Inside Arguments**:
   - In CMD batch `%*`, double quotes embedded within an argument must be escaped (e.g. `\"`) so that CMD does not strip quotes during batch line parsing. Single quotes (`'`) are treated as literal characters by CMD.
4. **Metacharacters (`&`, `|`, `<`, `>`, `^`, `%`, `!` )**:
   - When wrapped in double quotes (e.g. `"foo & bar"`), metacharacters are safely forwarded through `%*`. Unquoted metacharacters act as CMD shell control operators.
5. **Interactive Terminal Applications (TUI)**:
   - Stdio streams are forwarded directly without buffering or piping (`stdin=None, stdout=None, stderr=None`), preserving terminal dimensions, ANSI color escapes, and raw terminal modes for TUI applications like `cli_tui`, `termdash`, and Runmux.
6. **Exit Code Propagation**:
   - Batch wrappers use `exit /b %ERRORLEVEL%` ensuring child exit codes (0, 1, 42, 127, etc.) propagate identically to caller shell environments.

---

## 4. Privacy & Redaction Policy

Raw command-line arguments are treated as potentially sensitive data:

1. **Explicit Credential Scrubbing**:
   - Flags matching sensitive patterns (e.g. `--token`, `--api-key`, `--secret`, `--password`, `-p`, `--passwd`, `--auth`, `--cookie`, `--header`) have their values replaced with `[REDACTED]`.
   - Both inline `--token=<secret>` and split `--token <secret>` formats are sanitized.
2. **URL Userinfo and Query Scrubbing**:
   - Embedded credentials in URLs (e.g. `https://user:pass@example.com/`) are replaced with `https://user:[REDACTED]@example.com/`.
   - Flags with URLs (e.g. `--repo-url=https://user:pass@host/`) have their URL credentials sanitized.
   - Query strings containing credentials or authorization keys are redacted.
3. **Truncation Bounds**:
   - Argument vectors exceeding length boundaries (default 256 arguments) are truncated with explicit marker tokens `[TRUNCATED:count=N]`.
   - Commands exceeding maximum length (default 8192 characters) are truncated with explicit marker tokens `[TRUNCATED:chars=N]`.
4. **No Raw Secrets Persisted**:
   - If redaction was performed (`is_redacted = True`), `raw_argv_json` stores the redacted representation, ensuring sensitive credentials are never written to disk.
5. **SHA-256 Pattern Fingerprinting**:
   - The aggregated pattern fingerprint (`pattern_id`) is computed exclusively over redacted arguments to avoid leaking unique secrets in usage metrics.

---

## 5. Storage & Database Schema

### Database Paths:
- **Windows**: `%LOCALAPPDATA%\ScriptsToolkit\invocations.sqlite3`
- **macOS**: `~/Library/Application Support/ScriptsToolkit/invocations.sqlite3`
- **Linux / POSIX**: `${XDG_STATE_HOME:-~/.local/state}/scripts-toolkit/invocations.sqlite3`
- **Override**: `SCRIPT_LOGGING_INVOCATION_DB` environment variable.

### Configuration:
- SQLite `journal_mode = WAL`
- `synchronous = NORMAL`
- `busy_timeout = 15000` (15 seconds)

### Tables:
```sql
CREATE TABLE schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE invocations (
    invocation_id TEXT PRIMARY KEY,
    program_id TEXT NOT NULL,
    invoked_name TEXT NOT NULL,
    origin TEXT NOT NULL,
    pattern_id TEXT NOT NULL,
    raw_argv_json TEXT NOT NULL,
    redacted_argv_json TEXT NOT NULL,
    is_redacted INTEGER NOT NULL,
    cwd TEXT NOT NULL,
    started_at_utc TEXT NOT NULL,
    started_epoch_ms INTEGER NOT NULL,
    finished_at_utc TEXT,
    duration_ms INTEGER,
    exit_code INTEGER,
    status TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);

CREATE TABLE command_patterns (
    pattern_id TEXT PRIMARY KEY,
    program_id TEXT NOT NULL,
    pattern_argv_json TEXT NOT NULL,
    invocation_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    unknown_count INTEGER NOT NULL DEFAULT 0,
    first_seen_utc TEXT NOT NULL,
    last_seen_utc TEXT NOT NULL
);

CREATE TABLE program_usage (
    program_id TEXT PRIMARY KEY,
    total_starts INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    unknown_count INTEGER NOT NULL DEFAULT 0,
    first_seen_utc TEXT NOT NULL,
    last_seen_utc TEXT NOT NULL
);

CREATE TABLE alias_usage (
    invoked_name TEXT NOT NULL,
    program_id TEXT NOT NULL,
    total_starts INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    unknown_count INTEGER NOT NULL DEFAULT 0,
    first_seen_utc TEXT NOT NULL,
    last_seen_utc TEXT NOT NULL,
    PRIMARY KEY (invoked_name, program_id)
);
```

---

## 6. Public Read-Only Query API (`script_logging`)

Consumers should interact exclusively through the frozen public read-only API:

```python
from script_logging import (
    ReadOnlyHistoryReader,
    open_invocation_reader,
    list_invocations,
    InvocationRecord,
    CommandPattern,
    ProgramStatistics,
    CommandStatistics,
    AliasStatistics,
    Page,
    ReconciliationReport,
)
```

### 6.1 Data Models:

```python
@dataclass(frozen=True)
class InvocationRecord:
    invocation_id: str
    program_id: str
    invoked_name: str
    origin: str
    pattern_id: str
    raw_argv: Tuple[str, ...]
    redacted_argv: Tuple[str, ...]
    is_redacted: bool
    cwd: str
    started_at_utc: str
    started_epoch_ms: int
    status: str                         # "started", "exited", "launch_failed", "interrupted", "unknown"
    exit_code: Optional[int]
    finished_at_utc: Optional[str]
    duration_ms: Optional[int]

@dataclass(frozen=True)
class CommandPattern:
    pattern_id: str
    program_id: str
    pattern_argv_json: str
    invocation_count: int
    success_count: int
    failure_count: int
    unknown_count: int
    first_seen_utc: str
    last_seen_utc: str

@dataclass(frozen=True)
class ProgramStatistics:
    program_id: str
    total_starts: int
    success_count: int
    failure_count: int
    unknown_count: int
    first_seen_utc: Optional[str]
    last_seen_utc: Optional[str]

@dataclass(frozen=True)
class AliasStatistics:
    invoked_name: str
    program_id: str
    total_starts: int
    success_count: int
    failure_count: int
    unknown_count: int
    first_seen_utc: Optional[str]
    last_seen_utc: Optional[str]

@dataclass(frozen=True)
class Page[T]:
    items: List[T]
    next_cursor: Optional[str]
    has_more: bool
```

### 6.2 Reader Methods:

1. `open_invocation_reader(path: Optional[Path | str] = None) -> ReadOnlyHistoryReader`:
   Opens a read-only reader using SQLite URI `file:<path>?mode=ro`. Never creates missing files or takes write locks.

2. `reader.list_invocations(...) -> Page[InvocationRecord]`:
   - `program_id`: Optional program filter (e.g. `"module:mangadl"`).
   - `invoked_name`: Optional invoked alias filter (e.g. `"mangadl"`).
   - `status`: Optional lifecycle status filter (e.g. `"exited"`).
   - `since` / `before`: Optional ISO string, epoch ms integer, or datetime object.
   - `limit`: Page size (default 50).
   - `cursor`: Opaque Base64 pagination token.

3. `reader.get_invocation(invocation_id: str) -> Optional[InvocationRecord]`:
   Fetch a single invocation record by ID.

4. `reader.list_unique_commands(...) -> Page[CommandPattern]`:
   - `program_id`: Optional program filter.
   - `sort_by`: `"count"` (default) or `"seen"`.
   - `order`: `"desc"` (default) or `"asc"`.
   - `limit`: Page size (default 50).
   - `cursor`: Opaque Base64 pagination token.

5. `reader.get_program_statistics(program_id: str) -> ProgramStatistics`:
   Returns total starts, successes, failures, and timestamp bounds for a program.

6. `reader.get_alias_statistics(invoked_name: str, program_id: str) -> AliasStatistics`:
   Returns usage statistics for a specific command alias.

### 6.3 Pagination Cursor Format:
Pagination cursors are deterministic and opaque. Cursors for invocations encode:
```
base64(f"{started_epoch_ms}:{invocation_id}")
```
Cursors provide stable reverse-chronological pagination even when new records are actively inserted between page fetches.

---

## 7. Synthetic Consumer Test Fixture

For consumers (such as `scripts-help` and automated test suites), a synthetic fixture generates a deterministic history dataset:

```python
from script_logging.fixtures.synthetic_history import generate_synthetic_database

def test_my_consumer(tmp_path):
    db_file = tmp_path / "synthetic.sqlite3"
    metadata = generate_synthetic_database(db_file)
    # metadata contains expected program counts, total invocations, and pattern statistics
```

The synthetic database provides:
- 10 total invocations across 3 programs (`module:mangadl`, `module:compresser`, `pyscript:pyscripts/run_history_process.py`).
- 9 distinct patterns with varied exit codes (0, 1, 2, 130), durations (80ms to 12s), and origins (`launcher`, `inspection`).
- Sensitive argument samples (`--token=supersecret123`) verifying that consumer queries receive properly redacted data.

---

## 8. Guidance for `scripts-help` Agent (Handoff 3)

The `scripts-help` command can safely consume invocation history:
1. **Never mutate**: Always use `open_invocation_reader()` or `list_invocations()`.
2. **Handle missing databases**: When the database does not exist, `open_invocation_reader()` raises `FileNotFoundError`. Catch this exception and display zero usage metrics.
3. **No write contention**: Because `mode=ro` is used under WAL mode, queries from `scripts-help` will never block or be blocked by active launcher runs.
4. **Origin tagging**: When `scripts-help` executes commands internally for metadata inspection, set `origin="inspection"` to allow filtering inspection runs from user usage statistics.
