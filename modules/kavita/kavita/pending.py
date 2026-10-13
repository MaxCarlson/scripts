from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass(slots=True)
class Assignment:
    source_url: str
    expected_path: str
    collections: list[str]
    kavita_url: str = ""
    status: str = "pending"
    series_id: int | None = None
    series_name: str = ""
    reason: str = "awaiting Kavita scan"
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PendingAssignmentStore:
    """Atomic JSON store for MangaDL URL-to-Kavita collection intent."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> list[Assignment]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read Kavita assignment store {self.path}: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != 1 or not isinstance(payload.get("assignments"), list):
            raise ValueError(f"unsupported Kavita assignment store format: {self.path}")
        return [Assignment(**row) for row in payload["assignments"] if isinstance(row, dict)]

    def save(self, assignments: list[Assignment]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": 1, "assignments": [asdict(row) for row in assignments]}
        fd, temporary = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def enqueue(
        self,
        source_url: str,
        expected_path: str | Path,
        collections: list[str],
        *,
        kavita_url: str = "",
    ) -> list[Assignment]:
        url = source_url.strip()
        path = str(expected_path).strip()
        names = list(dict.fromkeys(name.strip() for name in collections if name.strip()))
        if not url or not path or not names:
            raise ValueError("a pending assignment needs a source URL, expected path, and collection name")
        rows = self.load()
        key = (url, path, kavita_url.rstrip("/"))
        found = next(
            (item for item in rows if (item.source_url, item.expected_path, item.kavita_url.rstrip("/")) == key), None
        )
        if found:
            found.collections = list(dict.fromkeys(found.collections + names))
            found.status = "pending"
            found.reason = "awaiting Kavita scan"
            found.updated_at = datetime.now(timezone.utc).isoformat()
        else:
            rows.append(Assignment(source_url=url, expected_path=path, collections=names, kavita_url=key[2]))
        self.save(rows)
        return rows

    def update(self, assignments: list[Assignment]) -> None:
        self.save(assignments)
