# agt/sessions.py
from __future__ import annotations
import json, os
from pathlib import Path
from typing import List, Dict, Any

def cfg_dir() -> Path:
    base = os.environ.get("AGT_CONFIG_DIR")
    if base:
        return Path(base)
    home = Path.home()
    return home / (".config" if os.name != "nt" else "AppData/Roaming") / "agt"

def sessions_dir() -> Path:
    d = cfg_dir() / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d

def session_path(name: str) -> Path:
    safe = "".join(ch for ch in name if ch.isalnum() or ch in "-_.")
    return sessions_dir() / f"{safe}.jsonl"

def load_session(name: str) -> List[Dict[str, Any]]:
    p = session_path(name)
    if not p.exists(): return []
    msgs = []
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            msgs.append(json.loads(line))
        except Exception:
            continue
    return msgs

def append_session(name: str, message: Dict[str, Any]) -> None:
    p = session_path(name)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(message, ensure_ascii=False) + "\n")
