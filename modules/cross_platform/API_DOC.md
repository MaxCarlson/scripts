# API Documentation for `cross_platform`

---
## File: `__init__.py`

*This file is empty or contains only imports/comments.*

---
## File: `clipboard_utils.py`

### Classes
#### class `ClipboardUtils`
**Methods:**
- `def get_clipboard(self) -> str:`
- `def is_termux(self) -> bool:`
- `def is_tmux(self) -> bool:`
- `def is_wsl2(self) -> bool:`
- `def os_name(self) -> str:`
- `def set_clipboard(self, text: str):`

### Functions
- `def get_clipboard() -> str:`
- `def set_clipboard(text: str):`

---
## File: `debug_utils.py`

### Functions
- `def disable_file_logging() -> None:`
- `def enable_file_logging() -> None:`
- `def print_parsed_args(args):`
- `def set_console_verbosity(level: str) -> None:`
- `def set_log_directory(filepath: str) -> None:`
- `def set_log_verbosity(level: str) -> None:`
- `def write_debug(message: str, channel: str, condition: bool, output_stream: str, location_channels) -> None:`

---
## File: `file_system_manager.py`

### Classes
#### class `FileSystemManager`
**Methods:**
- `def create_directory(self, path: str) -> bool:`
- `def delete_directory(self, path: str) -> bool:`
- `def list_files(self, path: str):`

---
## File: `fs_utils.py`

### Classes
#### class `FsSearchResult`

### Functions
- `def aggregate_counts_by_parent(files: Iterable[Path]) -> Dict[Path, int]:`
- `def delete_files(files: Iterable[Path]) -> list[tuple[Path, Exception]]:`
- `def dir_summary_lines(root: Path, counts: Dict[Path, int]) -> List[str]:`
- `def find_files_by_extension(root: Path, extension: str) -> FsSearchResult:`
- `def iter_dirs(root: Path) -> Iterator[Path]:`
- `def matches_ext(p: Path, want_ext: str) -> bool:`
- `def normalize_ext(ext: str) -> str:`
- `def relpath_str(p: Path, root: Path) -> str:`
- `def safe_relative_to(child: Path, base: Path) -> Path | str:`
- `def scanned_files_by_extension(root: Path, extension: str) -> FsSearchResult:`

---
## File: `history_utils.py`

### Classes
#### class `HistoryUtils`
**Methods:**
- `def get_nth_recent_path(self, n: int) -> str | None:`

### Functions
- `def main():`

---
## File: `network_utils.py`

### Classes
#### class `NetworkUtils`
**Methods:**
- `def reset_network(self) -> str:`

---
## File: `privileges_manager.py`

### Classes
#### class `PrivilegesManager`
**Methods:**
- `def require_admin(self):`

---
## File: `process_manager.py`

### Classes
#### class `ProcessManager`
**Methods:**
- `def kill_process(self, process_name: str) -> str:`
- `def list_processes(self) -> str:`

---
## File: `service_manager.py`

### Classes
#### class `ServiceManager`
**Methods:**
- `def service_status(self, service_name: str) -> str:`
- `def start_service(self, service_name: str) -> str:`
- `def stop_service(self, service_name: str) -> str:`

---
## File: `system_utils.py`

### Classes
#### class `SystemUtils`
**Methods:**
- `def is_termux(self) -> bool:`
- `def is_tmux(self) -> bool:`
- `def is_wsl2(self) -> bool:`
- `def run_command(self, command: str, sudo: bool) -> str:`
- `def source_file(self, filepath: str) -> bool:`

---
## File: `tmux_utils.py`

### Classes
#### class `TmuxManager`
**Methods:**
- `def attach_or_create_session(self, session_name, default_command):`
- `def capture_pane(self, start_line: str, end_line: str) -> str | None:`
- `def detach_client(self):`
- `def fuzzy_find_session(self, detached_only):`
- `def list_sessions_pretty(self):`
- `def list_sessions_raw(self, format_string):`
- `def next_available_session(self):`
- `def reattach_last_detached(self):`
- `def rename_current_session(self, new_name):`
- `def session_exists(self, session_name):`

### Functions
- `def main():`
