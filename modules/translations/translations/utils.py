"""Utility helpers for translations module."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable, List, Sequence

from rich.console import Console

console = Console()


class CommandError(RuntimeError):
    """Raised when an external command fails."""


def ensure_binary(name: str) -> None:
    if shutil.which(name):
        return
    raise CommandError(f"Required binary '{name}' is not available in PATH")


def run_ffmpeg_extract_audio(source: Path, tmp_dir: Path, audio_fmt: str = "wav") -> Path:
    ensure_binary("ffmpeg")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out_path = tmp_dir / f"{source.stem}.audio.{audio_fmt}"
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(out_path),
    ]
    console.log(f"[cyan]ffmpeg[/cyan] extracting audio to {out_path}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise CommandError(result.stderr.strip() or "ffmpeg failed")
    return out_path


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def fingerprint_text(text: str, algo: str = "sha256") -> str:
    h = hashlib.new(algo)
    h.update(normalize_whitespace(text).encode("utf-8"))
    return h.hexdigest()


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def chunk_iterable(seq: Sequence, size: int) -> Iterable[Sequence]:
    for idx in range(0, len(seq), size):
        yield seq[idx : idx + size]


def safe_filename(text: str, max_len: int = 180) -> str:
    invalid = '<>:"/\\|?*'
    cleaned = "".join('_' if ch in invalid else ch for ch in text)
    cleaned = normalize_whitespace(cleaned)
    cleaned = cleaned.replace(' ', '_')
    return cleaned[:max_len]


def create_temp_dir(prefix: str = "translations_") -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))
