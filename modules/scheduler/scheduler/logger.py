"""
Logging subsystem: strictly formatted central system log and task output retention.
"""
from __future__ import annotations

import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import ExecutionResult


def sanitize_filename(name: str) -> str:
    """Convert name to safe file/folder name."""
    clean = re.sub(r"[^\w\-\.]+", "_", name.strip())
    return clean or "unnamed_task"


class CentralLogger:
    """
    Central system logger.
    Strictly formats each entry as:
    [YYYY-MM-DD HH:MM:SS] | [LOGITEM_TYPE]: "message"
    """

    _lock = threading.Lock()

    def __init__(self, log_path: Path) -> None:
        self.log_path = Path(log_path).resolve()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, log_type: str, message: str, dt: Optional[datetime] = None) -> str:
        """Write a strictly formatted entry to the central system log."""
        if dt is None:
            dt = datetime.now()
        timestamp = dt.strftime("%Y-%m-%d %H:%M:%S")
        clean_type = log_type.strip().upper().replace(" ", "_")
        # Escape internal quotes in the message
        safe_msg = message.replace('"', '\\"')
        entry = f"[{timestamp}] | [{clean_type}]: \"{safe_msg}\""

        with self._lock:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        return entry

    # ── Semantic Helper Methods ──

    def log_schedule_create(self, name: str, timing_desc: str) -> str:
        return self.log("SCHEDULE_CREATE", f"Created schedule '{name}' ({timing_desc})")

    def log_schedule_edit(self, name: str, details: str) -> str:
        return self.log("SCHEDULE_EDIT", f"Updated schedule '{name}': {details}")

    def log_schedule_delete(self, name: str, orphaned_tasks: List[str]) -> str:
        msg = f"Deleted schedule '{name}'"
        if orphaned_tasks:
            msg += f" (orphaned tasks: {', '.join(orphaned_tasks)})"
        return self.log("SCHEDULE_DELETE", msg)

    def log_schedule_trigger(self, name: str, task_count: int, is_catchup: bool = False) -> str:
        kind = "catch-up trigger" if is_catchup else "trigger"
        return self.log("SCHEDULE_TRIGGER", f"Schedule '{name}' {kind} ({task_count} task(s) queued)")

    def log_task_create(self, name: str, env: str, admin: bool, schedule: Optional[str]) -> str:
        link_str = f"linked to '{schedule}'" if schedule else "standalone"
        return self.log("TASK_CREATE", f"Created task '{name}' (env={env}, admin={admin}, {link_str})")

    def log_task_edit(self, name: str, details: str) -> str:
        return self.log("TASK_EDIT", f"Updated task '{name}': {details}")

    def log_task_delete(self, name: str) -> str:
        return self.log("TASK_DELETE", f"Deleted task '{name}'")

    def log_task_attach(self, name: str, schedule: str) -> str:
        return self.log("TASK_ATTACH", f"Attached task '{name}' to schedule '{schedule}'")

    def log_task_detach(self, name: str) -> str:
        return self.log("TASK_DETACH", f"Detached task '{name}' from schedule")

    def log_task_start(self, name: str, env: str, admin: bool) -> str:
        return self.log("TASK_START", f"Starting task '{name}' [env={env}, admin={admin}]")

    def log_task_completion(self, name: str, exit_code: int, duration_sec: float) -> str:
        log_type = "TASK_SUCCESS" if exit_code == 0 else "TASK_FAILURE"
        return self.log(log_type, f"Task '{name}' finished with exit code {exit_code} (duration: {duration_sec:.2f}s)")

    def log_warning(self, message: str) -> str:
        return self.log("WARNING", message)

    def log_error(self, message: str) -> str:
        return self.log("ERROR", message)

    def log_system_info(self, message: str) -> str:
        return self.log("SYSTEM_INFO", message)

    def read_recent_entries(self, n: int = 50) -> List[str]:
        """Read the last N entries from the system log."""
        if not self.log_path.exists():
            return []
        with self._lock:
            with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = [line.rstrip("\r\n") for line in f if line.strip()]
        return lines[-n:] if n > 0 else lines

    def clear(self) -> None:
        """Clear the central system log."""
        with self._lock:
            if self.log_path.exists():
                with open(self.log_path, "w", encoding="utf-8") as f:
                    f.truncate(0)


class TaskLogger:
    """
    Dedicated task output logger.
    Stores execution output in a single log file per task (e.g. logs/tasks/<task_name>.log).
    Implements bounded retention within each task's log file so only the output
    from the N most recent runs is retained, automatically truncating older runs.
    """

    _lock = threading.Lock()
    DELIM_START = "=== [RUN START]"
    DELIM_END = "=== [RUN END] ==="

    def __init__(self, base_dir: Path, default_retention: int = 10) -> None:
        self.base_dir = Path(base_dir).resolve()
        self.default_retention = max(1, default_retention)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_task_log_path(self, task_name: str) -> Path:
        slug = sanitize_filename(task_name)
        return self.base_dir / f"{slug}.log"

    def _split_runs(self, raw_content: str) -> List[str]:
        """Split single-file log content into individual run blocks."""
        blocks: List[str] = []
        if not raw_content.strip():
            return blocks

        # Split on the start delimiter
        raw_parts = raw_content.split(self.DELIM_START)
        for part in raw_parts:
            part = part.strip()
            if not part:
                continue
            # Re-attach start delimiter
            full_block = f"{self.DELIM_START} {part}"
            blocks.append(full_block)
        return blocks

    def log_run(self, result: ExecutionResult, script_code: str = "", retention: Optional[int] = None) -> Path:
        """Append run result to task log file, retaining at most N most recent runs."""
        retention_limit = retention if retention is not None else self.default_retention
        log_file = self.get_task_log_path(result.task_name)

        # Build run block
        header_banner = "=" * 80
        status_str = "SUCCESS" if result.exit_code == 0 else f"FAILURE (Code {result.exit_code})"
        block_lines = [
            f"{self.DELIM_START} {header_banner[len(self.DELIM_START) + 1:]}",
            f"TASK EXECUTION REPORT: {result.task_name}",
            f"Schedule:    {result.schedule_name or 'None (Manual Run)'}",
            f"Timestamp:   {result.timestamp}",
            f"Environment: {result.environment} (Admin: {result.admin})",
            f"Exit Code:   {result.exit_code}",
            f"Duration:    {result.duration_sec:.3f} seconds",
            f"Status:      {status_str}",
            "-" * 80,
        ]

        if result.error_message:
            block_lines.extend([
                "--- ERROR MESSAGE ---",
                result.error_message,
                "",
            ])

        block_lines.extend([
            "--- SCRIPT CODE ---",
            script_code if script_code else "(no script code recorded)",
            "",
            "--- STANDARD OUTPUT ---",
            result.stdout if result.stdout else "(empty stdout)",
            "",
            "--- STANDARD ERROR ---",
            result.stderr if result.stderr else "(empty stderr)",
            f"{self.DELIM_END} {header_banner[len(self.DELIM_END) + 1:]}",
        ])

        new_block = "\n".join(block_lines)

        with self._lock:
            existing_blocks: List[str] = []
            if log_file.exists():
                try:
                    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                        raw = f.read()
                    existing_blocks = self._split_runs(raw)
                except OSError:
                    existing_blocks = []

            # Append the new run block
            existing_blocks.append(new_block)

            # Circular rotation / bounded retention: keep only N most recent runs
            if len(existing_blocks) > retention_limit:
                existing_blocks = existing_blocks[-retention_limit:]

            # Write retained blocks back to file atomically
            tmp_path = log_file.with_suffix(".tmp")
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    f.write("\n\n".join(existing_blocks) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, log_file)
            except Exception:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
                raise

        return log_file

    def read_task_log(self, task_name: str) -> Optional[str]:
        """Read full content of the task's log file."""
        log_file = self.get_task_log_path(task_name)
        if not log_file.exists():
            return None
        with self._lock:
            try:
                with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                    return f.read()
            except OSError:
                return None

    def read_latest_run_content(self, task_name: str) -> Optional[str]:
        """Read only the most recent run output from the task log file."""
        raw = self.read_task_log(task_name)
        if not raw:
            return None
        blocks = self._split_runs(raw)
        return blocks[-1] if blocks else raw

    def list_task_runs(self, task_name: str, count: int = 10) -> List[Dict[str, Any]]:
        """List metadata for individual runs recorded in the task's log file."""
        raw = self.read_task_log(task_name)
        if not raw:
            return []
        blocks = self._split_runs(raw)
        runs: List[Dict[str, Any]] = []

        # Return runs in reverse chronological order (latest first)
        for i, block in enumerate(reversed(blocks[-count:]), start=1):
            # Extract timestamp and status from block lines if present
            timestamp = "Unknown"
            status = "Unknown"
            for line in block.splitlines()[:10]:
                if line.startswith("Timestamp:"):
                    timestamp = line.split(":", 1)[1].strip()
                elif line.startswith("Status:"):
                    status = line.split(":", 1)[1].strip()

            runs.append({
                "run_index": i,
                "timestamp": timestamp,
                "status": status,
                "size_bytes": len(block.encode("utf-8")),
            })
        return runs

    def list_all_task_logs(self) -> List[Dict[str, Any]]:
        """List all per-task log files present in logs/tasks/."""
        if not self.base_dir.exists():
            return []
        result = []
        with self._lock:
            for p in sorted(self.base_dir.glob("*.log"), key=lambda f: f.name.lower()):
                task_slug = p.stem
                try:
                    with open(p, "r", encoding="utf-8", errors="replace") as f:
                        raw = f.read()
                    runs_count = len(self._split_runs(raw))
                    mtime = datetime.fromtimestamp(p.stat().st_mtime).isoformat()
                    result.append({
                        "task_slug": task_slug,
                        "path": str(p),
                        "run_count": runs_count,
                        "size_bytes": p.stat().st_size,
                        "modified": mtime,
                    })
                except OSError:
                    pass
        return result

    def clear_task_logs(self, task_name: Optional[str] = None) -> None:
        """Clear log file for a specific task or truncate all task log files."""
        with self._lock:
            if task_name is not None:
                log_file = self.get_task_log_path(task_name)
                if log_file.exists():
                    try:
                        log_file.unlink()
                    except OSError:
                        pass
            else:
                if self.base_dir.exists():
                    for p in self.base_dir.glob("*.log"):
                        try:
                            p.unlink()
                        except OSError:
                            pass
