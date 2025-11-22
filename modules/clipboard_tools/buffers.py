#!/usr/bin/env python3
"""
Shared helpers for multi-buffer clipboard storage and metadata.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

BUFFER_MIN = 0
BUFFER_MAX = 99


def _state_root() -> Path:
    override = os.environ.get("CLIPBOARD_STATE_DIR")
    if override:
        root = Path(override).expanduser()
    elif os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "clipboard_tools"
    else:
        root = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))) / "clipboard_tools"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _meta_path() -> Path:
    return _state_root() / "buffers_meta.json"


def _buffer_path(buffer_id: int) -> Path:
    return _state_root() / f"buffer_{buffer_id}.txt"


def buffer_file_path(buffer_id: int) -> Path:
    return _buffer_path(validate_buffer_id(buffer_id))


def validate_buffer_id(buffer_id: int | None) -> int:
    if buffer_id is None:
        buffer_id = 0
    if buffer_id < BUFFER_MIN or buffer_id > BUFFER_MAX:
        raise ValueError(f"Buffer id must be between {BUFFER_MIN} and {BUFFER_MAX}. Got {buffer_id}.")
    return buffer_id


def _load_meta() -> Dict:
    meta_path = _meta_path()
    if not meta_path.exists():
        return {"buffers": {}, "active_buffer": 0}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {"buffers": {}, "active_buffer": 0}


def _save_meta(meta: Dict) -> None:
    _meta_path().write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _word_count(text: str) -> int:
    return len(text.split())


@dataclass
class BufferSnapshot:
    buffer_id: int
    text: Optional[str]
    meta: Dict


def save_buffer(buffer_id: int, text: str, *, set_active: bool = True) -> Dict:
    buffer_id = validate_buffer_id(buffer_id)
    meta = _load_meta()
    buffers = meta.setdefault("buffers", {})
    buffer_meta = {
        "last_filled_utc": _now_iso(),
        "chars": len(text),
        "lines": len(text.splitlines()),
        "words": _word_count(text),
        "read_count": buffers.get(str(buffer_id), {}).get("read_count", 0),
    }
    buffers[str(buffer_id)] = buffer_meta
    if set_active:
        meta["active_buffer"] = buffer_id

    _buffer_path(buffer_id).write_text(text, encoding="utf-8")
    _save_meta(meta)
    return buffer_meta


def load_buffer(buffer_id: int) -> BufferSnapshot:
    buffer_id = validate_buffer_id(buffer_id)
    meta = _load_meta()
    buffers = meta.get("buffers", {})
    buf_meta = buffers.get(str(buffer_id), {})
    text: Optional[str]
    path = _buffer_path(buffer_id)
    if path.exists():
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            text = None
    else:
        text = None
    return BufferSnapshot(buffer_id=buffer_id, text=text, meta=buf_meta)


def record_buffer_read(buffer_id: int) -> None:
    buffer_id = validate_buffer_id(buffer_id)
    meta = _load_meta()
    buffers = meta.setdefault("buffers", {})
    buf = buffers.setdefault(str(buffer_id), {"read_count": 0})
    buf["read_count"] = buf.get("read_count", 0) + 1
    buf["last_read_utc"] = _now_iso()
    buffers[str(buffer_id)] = buf
    _save_meta(meta)


def get_active_buffer_id() -> int:
    meta = _load_meta()
    active = meta.get("active_buffer", 0)
    try:
        return validate_buffer_id(int(active))
    except Exception:
        return 0


def list_buffer_summaries() -> List[Dict]:
    meta = _load_meta()
    buffers = meta.get("buffers", {})
    summaries: List[Dict] = []
    for buf_id_str, info in buffers.items():
        try:
            buf_id = int(buf_id_str)
        except Exception:
            continue
        path = _buffer_path(buf_id)
        exists = path.exists()
        summaries.append(
            {
                "buffer": buf_id,
                "chars": info.get("chars", 0),
                "lines": info.get("lines", 0),
                "words": info.get("words", 0),
                "last_filled_utc": info.get("last_filled_utc"),
                "last_read_utc": info.get("last_read_utc"),
                "read_count": info.get("read_count", 0),
                "path": str(path),
                "present": exists,
            }
        )
    return sorted(summaries, key=lambda x: x["buffer"])


def parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def format_age(ts: Optional[str]) -> str:
    dt = parse_iso(ts)
    if not dt:
        return "unknown"
    delta = datetime.now(timezone.utc) - dt
    total_seconds = int(delta.total_seconds())
    mins, secs = divmod(total_seconds, 60)
    hours, mins = divmod(mins, 60)
    days, hours = divmod(hours, 24)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if mins:
        parts.append(f"{mins}m")
    parts.append(f"{secs}s")
    return " ".join(parts)
