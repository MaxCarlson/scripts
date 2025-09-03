# File: scripts/modules/cross_platform/docs/API.md
# cross_platform — Full Module API

**Purpose:** A small, composable standard library for your scripts that behaves consistently across **Windows 11**, **WSL2 (Ubuntu)**, and **Termux (Android/Linux)**.

This document is designed for **humans and LLMs**:
- Clear function/class signatures
- Short “when to use” guidance
- Deterministic behavior and return types
- Minimal side effects (helpers return data; your scripts decide how to print/format)

> Tip: Public helpers avoid interactive prompts and handle common cross-platform edge cases (path anchors/drives, missing tools) gracefully.

---

## Table of Contents

- [Design & Conventions](#design--conventions)
- [Top-Level Re-exports](#top-level-re-exports)
- [Submodules](#submodules)
  - [debug_utils](#debug_utils)
  - [system_utils](#system_utils)
  - [clipboard_utils](#clipboard_utils)
  - [network_utils](#network_utils)
  - [process_manager](#process_manager)
  - [service_manager](#service_manager)
  - [privileges_manager](#privileges_manager)
  - [history_utils](#history_utils)
  - [tmux_utils](#tmux_utils)
  - [fs_utils](#fs_utils)
- [Common Patterns](#common-patterns)
- [Versioning & Stability](#versioning--stability)

---

## Design & Conventions

- **Pure helpers:** Return strings/data structures; the caller controls printing and logging.
- **Consistent errors:**
  - Programmer/setup errors raise (e.g., invalid args).
  - Operational helpers prefer **graceful fallbacks** and **empty strings/None** over hard crashes where appropriate.
- **Logging:** Use `debug_utils.write_debug(...)` for structured console/log output.
- **OS detection:** Inherit from `SystemUtils` for `os_name`, `is_termux()`, `is_wsl2()`, `run_command(...)`.
- **Paths:** Prefer `fs_utils.safe_relative_to(...)` and `fs_utils.relpath_str(...)` for robust path rendering.

---

## Top-Level Re-exports

Importing from `cross_platform` yields these symbols:

```python
from cross_platform import (
    # Base + utilities
    SystemUtils, debug_utils,

    # Managers
    ClipboardUtils, NetworkUtils, ProcessManager, FileSystemManager,
    ServiceManager, PrivilegesManager, HistoryUtils, TmuxManager,

    # Filesystem helpers (fs_utils)
    FsSearchResult, normalize_ext, matches_ext, iter_dirs, find_files_by_extension,
    delete_files, safe_relative_to, relpath_str, aggregate_counts_by_parent,
    dir_summary_lines, scanned_files_by_extension,
)
```

> Note: `debug_utils` is a module (namespace import). Other names are classes/functions.

---

## Submodules

### debug_utils

Rich, controllable console and log output. No global prompting; safe in non-TTY.

**Public API**
```python
def set_console_verbosity(level: str = "Debug") -> None
def set_log_verbosity(level: str = "Warning") -> None
def set_log_directory(filepath: str) -> None
def enable_file_logging() -> None
def disable_file_logging() -> None

def write_debug(
    message: str = "",
    channel: str = "Debug",                 # Verbose|Debug|Information|Warning|Error|Critical
    condition: bool = True,
    output_stream: str = "stdout",          # "stdout" | "stderr"
    location_channels=None,                 # True | list[str] to include caller location
) -> None

def print_parsed_args(args) -> None         # Pretty-print argparse.Namespace
```

**Example**
```python
from cross_platform.debug_utils import write_debug, set_console_verbosity

set_console_verbosity("Information")
write_debug("Starting scan", channel="Information")
write_debug("Verbose details", channel="Verbose", condition=False)  # skipped
```

---

### system_utils

Base class for cross-platform helpers. Many managers inherit from this.

**Class:** `SystemUtils`

**Attributes**
- `os_name: str` — `"windows"`, `"linux"`, `"darwin"` (lowercase)

**Methods**
```python
def is_termux(self) -> bool
def is_tmux(self) -> bool
def is_wsl2(self) -> bool

def run_command(self, command: str, sudo: bool = False) -> str
# Runs command; returns stdout or "" on failure.

def source_file(self, filepath: str) -> bool
# Linux/macOS: attempts "source" in zsh subshell. Else False.
```

**Example**
```python
from cross_platform.system_utils import SystemUtils
sysu = SystemUtils()
print(sysu.os_name)
print(sysu.run_command("echo hello").strip())
```

---

### clipboard_utils

Cross-platform clipboard I/O.

**Class:** `ClipboardUtils(SystemUtils)`

**Methods**
```python
def get_clipboard(self) -> str
def set_clipboard(self, text: str) -> None
```

**Backends**
- Termux: `termux-clipboard-get/set`
- WSL2: `win32yank` if available
- Linux: `xclip -selection clipboard`
- macOS: `pbpaste` / `pbcopy`
- Windows: PowerShell `Get-Clipboard` / `Set-Clipboard`

**Shortcuts**
```python
from cross_platform.clipboard_utils import get_clipboard, set_clipboard
```

---

### network_utils

Quick network reset actions per OS.

**Class:** `NetworkUtils(SystemUtils)`

**Method**
```python
def reset_network(self) -> str
# Returns command output (may be empty).
```

Backends (typical):
- Termux: `svc wifi disable && svc wifi enable`
- Windows: `netsh`/`ipconfig`
- Linux: `systemctl restart NetworkManager`
- macOS: `ifconfig en0 down && up` plus DNS flush

---

### process_manager

List/kill processes with sane defaults.

**Class:** `ProcessManager(SystemUtils)`

**Methods**
```python
def list_processes(self) -> str       # "tasklist" | "ps aux" | ""
def kill_process(self, process_name: str) -> str  # taskkill/pkill; returns output (may be "")
```

---

### service_manager

Query and control services/daemons.

**Class:** `ServiceManager(SystemUtils)`

**Methods**
```python
def service_status(self, service_name: str) -> str
def start_service(self, service_name: str) -> str
def stop_service(self, service_name: str) -> str
```

Backends: `sc` (Windows), `systemctl` (Linux), `launchctl` (macOS). Returns command output or `""`.

---

### privileges_manager

Gate actions behind admin/root requirements.

**Class:** `PrivilegesManager(SystemUtils)`

**Method**
```python
def require_admin(self) -> None
# Non-admin -> raises PermissionError
```

---

### history_utils

Parse shell history for recent path-like tokens (zsh/bash/pwsh).

**Class:** `HistoryUtils(SystemUtils)`

**Public Methods**
```python
def get_nth_recent_path(self, n: int) -> str | None
# Returns nth most recent path token or None.
```

---

### tmux_utils

Session ergonomics for `tmux` (with optional `fzf` integration).

**Class:** `TmuxManager`

**Key Methods**
```python
def list_sessions_raw(self, format_string="'#{session_name}'") -> str
def list_sessions_pretty(self) -> None
def capture_pane(self, start_line: str = '-', end_line: str = '-') -> str | None
def session_exists(self, session_name: str) -> bool
def attach_or_create_session(self, session_name: str, default_command: str | None = None) -> None
def next_available_session(self) -> str
def reattach_last_detached(self) -> None
def fuzzy_find_session(self, detached_only: bool = False) -> str | None
def rename_current_session(self, new_name: str) -> None
def detach_client(self) -> None
```

**CLI Entrypoint**
```python
from cross_platform.tmux_utils import main  # argparse CLI
```

> Requires `tmux`. Methods no-op gracefully (with logs) when tools are missing.

---

### fs_utils

Robust, centralized filesystem helpers.

**Data Class**
```python
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class FsSearchResult:
    searched_dirs: list[Path]
    matched_files: list[Path]
```

**Functions**
```python
def normalize_ext(ext: str) -> str

def matches_ext(p: Path, want_ext: str, *, case_sensitive: bool = False) -> bool

def iter_dirs(
    root: Path,
    *,
    follow_symlinks: bool = False,
    exclude_dir_globs: Sequence[str] | None = None,
    max_depth: int | None = None,
) -> Iterator[Path]

def find_files_by_extension(
    root: Path, extension: str, *,
    case_sensitive: bool = False,
    follow_symlinks: bool = False,
    exclude_dir_globs: Sequence[str] | None = None,
    max_depth: int | None = None,
) -> FsSearchResult

def scanned_files_by_extension(...) -> FsSearchResult  # convenience alias

def delete_files(files: Iterable[Path]) -> list[tuple[Path, Exception]]

def safe_relative_to(child: Path, base: Path) -> Path | str
# Relative Path if child inside base; else absolute string. Never raises.

def relpath_str(p: Path, root: Path, *, absolute_paths: bool = False) -> str

def aggregate_counts_by_parent(files: Iterable[Path]) -> dict[Path, int]

def dir_summary_lines(
    root: Path, counts: dict[Path, int], *,
    top_n: int = 50,
    show_all: bool = False,
    absolute_paths: bool = False,
) -> list[str]
```

**Quick Example**
```python
from pathlib import Path
from cross_platform.fs_utils import scanned_files_by_extension, aggregate_counts_by_parent, dir_summary_lines

root = Path("stars")
res = scanned_files_by_extension(root, "jpg")
counts = aggregate_counts_by_parent(res.matched_files)
print("\n".join(dir_summary_lines(root, counts, top_n=25)))
```

---

## Common Patterns

**Structured logging everywhere**
```python
from cross_platform.debug_utils import write_debug
write_debug("Something happened", channel="Information")
write_debug("Verbosity example", channel="Verbose")
write_debug("Warn about fallback", channel="Warning")
```

**Safe command execution**
```python
from cross_platform.system_utils import SystemUtils
sysu = SystemUtils()
out = sysu.run_command("echo hello")
```

**Clipboard roundtrip**
```python
from cross_platform.clipboard_utils import get_clipboard, set_clipboard
set_clipboard(get_clipboard().upper())
```

**Process control**
```python
from cross_platform.process_manager import ProcessManager
pm = ProcessManager()
print(pm.list_processes())
pm.kill_process("someproc.exe")
```

**Network reset (per OS)**
```python
from cross_platform.network_utils import NetworkUtils
print(NetworkUtils().reset_network())
```

**Service control**
```python
from cross_platform.service_manager import ServiceManager
svc = ServiceManager()
print(svc.service_status("ssh"))
svc.start_service("ssh")
```

**Admin gating**
```python
from cross_platform.privileges_manager import PrivilegesManager
PrivilegesManager().require_admin()
```

**History jump**
```python
from cross_platform.history_utils import HistoryUtils
path = HistoryUtils().get_nth_recent_path(1)
if path: print("Jump to:", path)
```

**tmux workflows**
```python
from cross_platform.tmux_utils import TmuxManager
tm = TmuxManager()
tm.attach_or_create_session("work")
```

**Robust scanning & deletion**
```python
from pathlib import Path
from cross_platform.fs_utils import find_files_by_extension, delete_files
res = find_files_by_extension(Path("."), "part", exclude_dir_globs=[".git", "__pycache__"])
failures = delete_files(res.matched_files)
```

---

## Versioning & Stability

- The API above is considered **stable**. New helpers may be added over time.
- Behavioral guarantees:
  - Display/path helpers never raise due to relativity issues.
  - Command wrappers return strings (possibly empty) rather than crashing.
  - Privilege checks and unsupported OS paths raise/return as documented.
