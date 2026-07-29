"""Helpers for custom validation scripts to emit normalized result JSON."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from development_ledger.models import VALID_TEST_STATES


@dataclass(slots=True)
class ScriptCheck:
    """One custom check to be serialized in the generic script-result format."""

    id: str
    name: str
    status: str
    duration_seconds: float = 0.0
    message: str = ""
    item_ids: list[str] = field(default_factory=list)
    file: str = ""
    classname: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        if self.status not in VALID_TEST_STATES:
            raise ValueError(f"Invalid script-check status {self.status!r} for {self.id}.")
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "duration_seconds": self.duration_seconds,
            "message": self.message,
            "item_ids": self.item_ids,
            "file": self.file,
            "classname": self.classname,
            "metadata": self.metadata,
        }


def write_script_results(
    path: Path,
    *,
    source: str,
    suite: str,
    checks: list[ScriptCheck],
    metadata: dict[str, Any] | None = None,
) -> None:
    """Atomically write generic custom-check results for ledger ingestion."""

    if not source.strip() or not suite.strip():
        raise ValueError("source and suite must be non-empty strings.")
    payload = {
        "schema_version": 1,
        "source": source,
        "suite": suite,
        "tests": [check.to_dict() for check in checks],
        "metadata": metadata or {},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=4, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)
