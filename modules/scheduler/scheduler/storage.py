"""
Persistent JSON storage manager for schedules, tasks, and configurations.
Stores all state persistently in a single JSON file within the scheduler module directory.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from uuid import uuid4
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import ConfigManager, SchedulerConfig
from .models import Schedule, Task

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_FILE = DEFAULT_DATA_DIR / "scheduler_data.json"


class StorageManager:
    """Thread-safe persistent storage manager backed by a single JSON file."""

    _lock = threading.RLock()

    def __init__(self, data_file: Optional[Path] = None) -> None:
        if data_file is not None:
            self.data_file = Path(data_file).resolve()
        else:
            env_override = os.environ.get("SCHEDULER_DATA_FILE")
            if env_override:
                self.data_file = Path(env_override).resolve()
            else:
                self.data_file = DEFAULT_DATA_FILE

        self.module_dir = self.data_file.parent
        self._ensure_initialized()

    def _ensure_initialized(self) -> None:
        """Initialize the JSON file with detected defaults if it doesn't exist."""
        with self._lock:
            self.module_dir.mkdir(parents=True, exist_ok=True)
            if not self.data_file.exists():
                default_config = ConfigManager.create_default_config()
                initial_data = {
                    "version": 1,
                    "config": default_config.to_dict(),
                    "schedules": {},
                    "tasks": {},
                }
                self._write_raw(initial_data)

    def _read_raw(self) -> Dict[str, Any]:
        """Read and parse raw JSON from disk."""
        with self._lock:
            if not self.data_file.exists():
                self._ensure_initialized()
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    data = {}
            except (json.JSONDecodeError, OSError):
                # Fallback to empty structure if corrupted
                data = {}

            if "config" not in data or not isinstance(data["config"], dict):
                data["config"] = ConfigManager.create_default_config().to_dict()
            if "schedules" not in data or not isinstance(data["schedules"], dict):
                data["schedules"] = {}
            if "tasks" not in data or not isinstance(data["tasks"], dict):
                data["tasks"] = {}
            changed = False
            for collection, id_field in (("schedules", "schedule_id"), ("tasks", "task_id")):
                for item in data[collection].values():
                    if isinstance(item, dict) and not item.get(id_field):
                        item[id_field] = uuid4().hex
                        changed = True
            for item in data["tasks"].values():
                if isinstance(item, dict) and item.get("schedule_name") and not item.get("attached_at"):
                    item["attached_at"] = datetime.now().astimezone().isoformat()
                    changed = True
            if changed:
                self._write_raw(data)
            return data

    def _write_raw(self, data: Dict[str, Any]) -> None:
        """Atomically write JSON data to disk via a temporary file."""
        with self._lock:
            self.module_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = self.data_file.with_suffix(".tmp")
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, self.data_file)
            except Exception:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
                raise

    # ── Config Management ──

    def get_config(self) -> SchedulerConfig:
        raw = self._read_raw()
        return SchedulerConfig.from_dict(raw.get("config", {}))

    def update_config(self, config: SchedulerConfig) -> None:
        with self._lock:
            raw = self._read_raw()
            raw["config"] = config.to_dict()
            self._write_raw(raw)

    # ── Schedule Management ──

    def list_schedules(self) -> List[Schedule]:
        raw = self._read_raw()
        schedules = []
        for name, sdata in raw.get("schedules", {}).items():
            if isinstance(sdata, dict):
                schedules.append(Schedule.from_dict(sdata))
        return sorted(schedules, key=lambda s: s.name.lower())

    def get_schedule(self, name: str) -> Optional[Schedule]:
        raw = self._read_raw()
        sdata = raw.get("schedules", {}).get(name)
        if isinstance(sdata, dict):
            return Schedule.from_dict(sdata)
        return None

    def save_schedule(self, schedule: Schedule) -> None:
        with self._lock:
            raw = self._read_raw()
            raw.setdefault("schedules", {})[schedule.name] = schedule.to_dict()
            self._write_raw(raw)

    def delete_schedule(self, name: str, orphan_tasks: bool = True) -> Tuple[bool, List[str]]:
        """
        Delete a schedule.
        Returns (success, attached_task_names).
        If orphan_tasks is True, attached tasks have their schedule_name set to None.
        """
        with self._lock:
            raw = self._read_raw()
            schedules = raw.get("schedules", {})
            if name not in schedules:
                return False, []

            # Find all tasks attached to this schedule
            attached_task_names = []
            tasks = raw.get("tasks", {})
            for t_name, t_data in tasks.items():
                if isinstance(t_data, dict) and t_data.get("schedule_name") == name:
                    attached_task_names.append(t_name)
                    if orphan_tasks:
                        t_data["schedule_name"] = None
                        t_data["schedule_order"] = None
                        t_data["attached_at"] = None

            del schedules[name]
            self._write_raw(raw)
            return True, attached_task_names

    # ── Task Management ──

    def list_tasks(self, schedule_name: Optional[str] = None) -> List[Task]:
        raw = self._read_raw()
        tasks = []
        for name, tdata in raw.get("tasks", {}).items():
            if isinstance(tdata, dict):
                t = Task.from_dict(tdata)
                if schedule_name is None or t.schedule_name == schedule_name:
                    tasks.append(t)
        return sorted(tasks, key=lambda t: t.name.lower())

    def get_task(self, name: str) -> Optional[Task]:
        raw = self._read_raw()
        tdata = raw.get("tasks", {}).get(name)
        if isinstance(tdata, dict):
            return Task.from_dict(tdata)
        return None

    def save_task(self, task: Task) -> None:
        with self._lock:
            raw = self._read_raw()
            self._ensure_schedule_orders(raw)
            tasks = raw.setdefault("tasks", {})
            existing = tasks.get(task.name)
            if not task.schedule_name:
                task.schedule_order = None
                task.attached_at = None
            elif isinstance(existing, dict) and existing.get("schedule_name") == task.schedule_name:
                task.schedule_order = existing.get("schedule_order")
                task.attached_at = existing.get("attached_at") or task.attached_at
            elif existing is None and task.attached_at and task.schedule_order is not None:
                # A rename retains the same task identity and schedule attachment.
                pass
            else:
                assigned = [
                    data.get("schedule_order", -1)
                    for data in tasks.values()
                    if isinstance(data, dict)
                    and data.get("schedule_name") == task.schedule_name
                    and isinstance(data.get("schedule_order"), int)
                ]
                task.schedule_order = max(assigned, default=-1) + 1
                task.attached_at = datetime.now().astimezone().isoformat()
            tasks[task.name] = task.to_dict()
            self._write_raw(raw)

    def delete_task(self, name: str) -> bool:
        with self._lock:
            raw = self._read_raw()
            tasks = raw.get("tasks", {})
            if name in tasks:
                del tasks[name]
                self._write_raw(raw)
                return True
            return False

    def get_attached_tasks(self, schedule_name: str) -> List[Task]:
        with self._lock:
            raw = self._read_raw()
            if self._ensure_schedule_orders(raw):
                self._write_raw(raw)
            tasks = [
                Task.from_dict(task_data)
                for task_data in raw.get("tasks", {}).values()
                if isinstance(task_data, dict) and task_data.get("schedule_name") == schedule_name
            ]
            return sorted(tasks, key=lambda task: task.schedule_order if task.schedule_order is not None else 0)

    @staticmethod
    def _ensure_schedule_orders(raw: Dict[str, Any]) -> bool:
        """Migrate legacy tasks in their existing JSON insertion order."""
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for task_data in raw.get("tasks", {}).values():
            if isinstance(task_data, dict) and task_data.get("schedule_name"):
                grouped.setdefault(str(task_data["schedule_name"]), []).append(task_data)

        changed = False
        for attached in grouped.values():
            missing = [task for task in attached if not isinstance(task.get("schedule_order"), int)]
            if not missing:
                continue
            assigned = [task["schedule_order"] for task in attached if isinstance(task.get("schedule_order"), int)]
            next_order = max(assigned, default=-1) + 1
            for index, task in enumerate(missing):
                task["schedule_order"] = index if not assigned else next_order + index
                changed = True
        return changed
