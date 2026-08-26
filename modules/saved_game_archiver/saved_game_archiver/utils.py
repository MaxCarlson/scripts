from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return normalized or "game"


def stable_game_id(name: str, steam_app_id: int | None = None, install_dir: str | None = None) -> str:
    if steam_app_id is not None:
        return f"steam-{steam_app_id}"
    basis = f"{name}\0{install_dir or ''}".encode("utf-8", errors="replace")
    return f"game-{slugify(name)[:32]}-{hashlib.sha256(basis).hexdigest()[:10]}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def format_playtime(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:04d}h{minutes:02d}m{secs:02d}s"


def sanitize_filename(value: str) -> str:
    value = re.sub(r"[<>:\\/*?\"|]+", "_", value).strip(" .")
    return value or "game"
