"""File-backed one-shot requests for task runs through the scheduler daemon."""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional


@dataclass(frozen=True)
class RunRequest:
    request_id: str
    task_name: str
    run_at: datetime
    expires_at: datetime
    request_path: Path
    visible_window: bool = False


class RunRequestQueue:
    """Persist requests separately from scheduler configuration to avoid config races."""

    def __init__(self, module_dir: Path) -> None:
        self.directory = Path(module_dir) / "run_requests"

    def enqueue(
        self,
        task_name: str,
        delay_seconds: int = 10,
        *,
        now: Optional[datetime] = None,
        visible_window: bool = False,
        expires_after: timedelta = timedelta(minutes=5),
    ) -> RunRequest:
        if delay_seconds < 0:
            raise ValueError("A run request cannot be scheduled in the past.")
        created = now or datetime.now()
        request_id = uuid.uuid4().hex
        run_at = created + timedelta(seconds=delay_seconds)
        expires_at = run_at + expires_after
        self.directory.mkdir(parents=True, exist_ok=True)
        request_path = self.directory / f"{request_id}.json"
        temp_path = self.directory / f"{request_id}.tmp"
        payload = {
            "request_id": request_id,
            "task_name": task_name,
            "run_at": run_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "visible_window": visible_window,
        }
        try:
            with temp_path.open("w", encoding="utf-8") as stream:
                json.dump(payload, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, request_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
        return RunRequest(request_id, task_name, run_at, expires_at, request_path, visible_window)

    def claim_due(self, *, now: Optional[datetime] = None) -> List[RunRequest]:
        current = now or datetime.now()
        self.directory.mkdir(parents=True, exist_ok=True)
        claimed: List[RunRequest] = []
        for request_path in sorted(self.directory.glob("*.json")):
            try:
                payload = json.loads(request_path.read_text(encoding="utf-8"))
                run_at = datetime.fromisoformat(payload["run_at"])
                expires_at = datetime.fromisoformat(payload["expires_at"])
                task_name = str(payload["task_name"])
                request_id = str(payload["request_id"])
                visible_window = bool(payload.get("visible_window", False))
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                failed_path = request_path.with_suffix(".invalid")
                try:
                    os.replace(request_path, failed_path)
                except OSError:
                    pass
                continue

            if run_at > current:
                continue

            if expires_at <= current:
                try:
                    os.replace(request_path, request_path.with_suffix(".expired"))
                except OSError:
                    pass
                continue

            claimed_path = request_path.with_suffix(".running")
            try:
                os.replace(request_path, claimed_path)
            except OSError:
                continue
            claimed.append(RunRequest(request_id, task_name, run_at, expires_at, claimed_path, visible_window))
        return claimed

    def write_result(self, request: RunRequest, result: dict) -> None:
        """Atomically publish a worker result for the limited-privilege daemon."""
        self.directory.mkdir(parents=True, exist_ok=True)
        result_path = self.directory / f"{request.request_id}.result.json"
        temp_path = result_path.with_suffix(".tmp")
        try:
            payload = dict(result)
            payload["_visible_window"] = request.visible_window
            with temp_path.open("w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, result_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def read_result(self, request_id: str) -> Optional[dict]:
        result_path = self.directory / f"{request_id}.result.json"
        try:
            value = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def remove_result(self, request_id: str) -> None:
        try:
            (self.directory / f"{request_id}.result.json").unlink(missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def complete(request: RunRequest) -> None:
        try:
            request.request_path.unlink(missing_ok=True)
        except OSError:
            pass
