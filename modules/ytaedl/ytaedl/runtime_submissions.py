"""Durable queue primitives for URLs submitted to a running manager."""

from __future__ import annotations

import json
import os
import uuid
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Deque, Dict, List, Optional
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Submission:
    """One URL or one existing URL file awaiting manager scheduling."""

    submission_id: str
    kind: str
    value: str


def allocate_initial_submissions(
    items: List[Submission], requested_workers: int, available_slots: int
) -> tuple[List[Submission], List[Submission]]:
    """Choose up to N initial worker assignments and retain overflow in queue order."""
    count = min(max(0, int(requested_workers)), max(0, int(available_slots)), len(items))
    return items[:count], items[count:]


class SubmissionQueue:
    """Persisted, deduplicating queue for manual manager submissions.

    Claimed entries stay durable until their worker completes; startup restores
    claims to pending so an interrupted manager run cannot lose submitted work.
    """

    def __init__(self, state_path: Path, manual_dir: Path) -> None:
        self.state_path = Path(state_path)
        self.manual_dir = Path(manual_dir)
        self.manual_dir.mkdir(parents=True, exist_ok=True)
        self._pending: Deque[Submission] = deque()
        self._in_progress: Dict[str, Submission] = {}
        if self.state_path.exists():
            self._load()

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def in_progress_count(self) -> int:
        return len(self._in_progress)

    @property
    def pending(self) -> List[Submission]:
        return list(self._pending)

    @property
    def in_progress(self) -> List[Submission]:
        return list(self._in_progress.values())

    def _load(self) -> None:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            pending = [Submission(**row) for row in payload.get("pending", [])]
            claimed = [Submission(**row) for row in payload.get("in_progress", [])]
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise ValueError(f"Cannot read pending manual submissions at {self.state_path}: {exc}") from exc
        self._pending.extend(claimed + pending)

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "pending": [asdict(item) for item in self._pending],
            "in_progress": [asdict(item) for item in self._in_progress.values()],
        }
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.state_path)

    @staticmethod
    def _is_http_url(value: str) -> bool:
        try:
            parsed = urlsplit(value)
            return parsed.scheme in {"http", "https"} and bool(parsed.hostname)
        except ValueError:
            return False

    @staticmethod
    def _valid_url_file(path: Path) -> bool:
        try:
            return any(
                SubmissionQueue._is_http_url(line.strip())
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
            )
        except OSError:
            return False

    @staticmethod
    def _identity(item: Submission) -> tuple[str, str]:
        if item.kind == "file":
            return item.kind, str(Path(item.value).resolve())
        return item.kind, item.value

    @staticmethod
    def validate(text: str) -> List[tuple[str, str]]:
        """Parse all lines and reject the complete batch if any item is invalid."""
        parsed: List[tuple[str, str]] = []
        for raw in text.splitlines():
            value = raw.strip()
            if not value:
                continue
            if value.startswith(("http://", "https://")):
                if not SubmissionQueue._is_http_url(value):
                    raise ValueError(f"Malformed HTTP(S) URL: {value}")
                parsed.append(("url", value))
                continue
            path = Path(value).expanduser().resolve()
            if not path.exists():
                raise ValueError(f"Submission is neither an HTTP(S) URL nor an existing path: {value}")
            if not path.is_file():
                raise ValueError(f"URL-file path is not a regular file: {path}")
            if not SubmissionQueue._valid_url_file(path):
                raise ValueError(f"URL file contains no HTTP(S) URLs: {path}")
            parsed.append(("file", str(path)))
        if not parsed:
            raise ValueError("Enter at least one URL or existing URL-file path.")
        return parsed

    def submit(self, text: str) -> List[Submission]:
        """Validate and append newline-separated URLs/file paths atomically."""
        parsed = self.validate(text)

        known = {self._identity(item) for item in self._pending}
        known.update(self._identity(item) for item in self._in_progress.values())
        accepted: List[Submission] = []
        for kind, value in parsed:
            identity = (kind, value if kind == "url" else str(Path(value).resolve()))
            if identity in known:
                continue
            known.add(identity)
            submission_id = uuid.uuid4().hex
            if kind == "url":
                url_path = self.manual_dir / f"{submission_id}.txt"
                url_path.write_text(value + "\n", encoding="utf-8")
                value = str(url_path.resolve())
            accepted.append(Submission(submission_id, kind, value))

        self._pending.extend(accepted)
        self._save()
        return accepted

    def claim(self, submission_id: Optional[str] = None) -> Optional[Submission]:
        if not self._pending:
            return None
        if submission_id is None:
            item = self._pending.popleft()
        else:
            item = next((row for row in self._pending if row.submission_id == submission_id), None)
            if item is None:
                return self._in_progress.get(submission_id)
            self._pending.remove(item)
        self._in_progress[item.submission_id] = item
        self._save()
        return item

    def complete(self, item: Submission) -> None:
        self._in_progress.pop(item.submission_id, None)
        self._save()

    def restore(self, item: Submission) -> None:
        if self._in_progress.pop(item.submission_id, None):
            self._pending.appendleft(item)
            self._save()


@dataclass
class SubmissionDialog:
    """Small nonblocking TUI state machine; caller supplies one key at a time."""

    stage: str = "input"
    buffer: str = ""
    worker_count: str = ""
    error: str = ""
    completed: bool = False
    cancelled: bool = False
    choice: Optional[str] = None
    requested_workers: int = 0

    def display_lines(self, width: int = 100) -> List[str]:
        if self.stage == "input":
            buffer_lines = self.buffer.splitlines()[-3:]
            lines = ["SUBMIT WORK: one URL or existing URL-file path per line"]
            lines.extend(buffer_lines or [""])
            lines.append("Tab to continue · Enter for another line · Esc to cancel")
        elif self.stage == "schedule":
            lines = ["SCHEDULE SUBMISSIONS", "1 Queue all items", "2 Start additional workers", "Esc to cancel"]
        else:
            lines = ["ADDITIONAL WORKERS", f"Count: {self.worker_count}", "Enter to start · Esc to cancel"]
        if self.error:
            lines.append(f"Error: {self.error}")
        return [line[: max(1, width)] for line in lines]

    def feed(self, key: str) -> Optional[str]:
        """Consume one terminal key and return input, queue, workers, cancel or None."""
        if key == "\x1b":
            self.cancelled = True
            return "cancel"
        if self.stage == "input":
            if key == "\t":  # Tab avoids Ctrl+S terminal flow-control behavior.
                if not self.buffer.strip():
                    self.error = "Enter one or more URLs or existing URL-file paths."
                    return None
                self.stage = "schedule"
                self.error = ""
                return "input"
            if key in ("\r", "\n"):
                self.buffer += "\n"
            elif key in ("\b", "\x7f"):
                self.buffer = self.buffer[:-1]
            elif key.isprintable():
                self.buffer += key
            return None
        if self.stage == "schedule":
            if key == "1":
                self.choice = "queue"
                self.completed = True
                return "queue"
            if key == "2":
                self.stage = "workers"
                return None
            self.error = "Choose 1 (queue) or 2 (additional workers)."
            return None
        if self.stage == "workers":
            if key in ("\r", "\n"):
                try:
                    self.requested_workers = int(self.worker_count)
                except ValueError:
                    self.error = "Enter a positive whole number of workers."
                    return None
                if self.requested_workers < 1:
                    self.error = "Enter a positive whole number of workers."
                    return None
                self.choice = "workers"
                self.completed = True
                return "workers"
            if key in ("\b", "\x7f"):
                self.worker_count = self.worker_count[:-1]
            elif key.isdigit():
                self.worker_count += key
            return None
        return None
