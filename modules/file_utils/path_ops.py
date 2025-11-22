from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import List, Tuple

from cross_platform.system_utils import SystemUtils


def _backup_dir() -> Path:
    root = Path(__file__).resolve().parent
    bdir = root / "path_backups"
    bdir.mkdir(parents=True, exist_ok=True)
    return bdir


def _now_ts() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _normalize_parts(parts: List[str], is_windows: bool) -> List[str]:
    normed = []
    seen = set()
    for p in parts:
        if not p:
            continue
        key = p.lower() if is_windows else p
        if key in seen:
            continue
        seen.add(key)
        normed.append(p)
    return normed


def _read_windows_path(scope: str) -> Tuple[str, List[str]]:
    try:
        import winreg  # type: ignore
    except Exception as e:  # pragma: no cover - non-Windows
        raise RuntimeError("winreg unavailable") from e

    hive = winreg.HKEY_CURRENT_USER if scope == "user" else winreg.HKEY_LOCAL_MACHINE
    path = r"Environment" if scope == "user" else r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
    with winreg.OpenKey(hive, path, 0, winreg.KEY_READ) as key:
        try:
            val, _ = winreg.QueryValueEx(key, "PATH")
        except FileNotFoundError:
            val = ""
    parts = val.split(os.pathsep) if val else []
    return val, _normalize_parts(parts, True)


def _write_windows_path(scope: str, parts: List[str]) -> None:
    try:
        import winreg  # type: ignore
    except Exception as e:  # pragma: no cover - non-Windows
        raise RuntimeError("winreg unavailable") from e

    hive = winreg.HKEY_CURRENT_USER if scope == "user" else winreg.HKEY_LOCAL_MACHINE
    path = r"Environment" if scope == "user" else r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
    with winreg.OpenKey(hive, path, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "PATH", 0, winreg.REG_EXPAND_SZ, os.pathsep.join(parts))


def _read_posix_path() -> Tuple[str, List[str]]:
    val = os.environ.get("PATH", "")
    parts = val.split(os.pathsep) if val else []
    return val, _normalize_parts(parts, False)


def _write_posix_path(parts: List[str], scope: str) -> None:
    """
    Persist a PATH export snippet under ~/.config/file_utils/path_<scope>.sh.
    Caller must source this file in their shell profile; we do NOT touch rc files automatically.
    """
    cfg_dir = Path.home() / ".config" / "file_utils"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    target = cfg_dir / f"path_{scope}.sh"
    content = f'export PATH="{os.pathsep.join(parts)}"\n'
    target.write_text(content, encoding="utf-8")
    # Update current process env so subsequent commands see it
    os.environ["PATH"] = os.pathsep.join(parts)


def load_path(scope: str) -> Tuple[str, List[str]]:
    sysu = SystemUtils()
    if scope not in ("user", "machine", "process"):
        raise ValueError("scope must be one of: user, machine, process")

    if sysu.is_windows():
        if scope == "process":
            raw, parts = os.environ.get("PATH", ""), os.environ.get("PATH", "").split(os.pathsep)
            return raw, _normalize_parts(parts, True)
        raw, parts = _read_windows_path(scope)
        return raw, parts

    # POSIX/Termux/WSL/darwin: process & user treated the same; machine unsupported
    if scope == "machine":
        raise RuntimeError("Machine scope PATH edits are not supported on this platform.")
    raw, parts = _read_posix_path()
    return raw, parts


def backup_path(scope: str, raw_value: str) -> Path:
    bdir = _backup_dir()
    target = bdir / f"{scope}_PATH_{_now_ts()}.txt"
    target.write_text(raw_value, encoding="utf-8")
    return target


def save_path(scope: str, parts: List[str]) -> Path:
    """
    Write PATH for given scope. Returns backup path created.
    """
    sysu = SystemUtils()
    raw, _ = load_path(scope)
    backup = backup_path(scope, raw)

    normed = _normalize_parts(parts, sysu.is_windows())
    if sysu.is_windows():
        if scope == "process":
            os.environ["PATH"] = os.pathsep.join(normed)
        else:
            _write_windows_path(scope, normed)
    else:
        _write_posix_path(normed, scope)
    return backup


def list_paths(scope: str) -> List[str]:
    _, parts = load_path(scope)
    return parts


def add_path(scope: str, value: str) -> Tuple[List[str], Path]:
    raw, parts = load_path(scope)
    is_win = SystemUtils().is_windows()
    key = value.lower() if is_win else value
    existing_keys = {p.lower() if is_win else p for p in parts}
    if key in existing_keys:
        return parts, backup_path(scope, raw)
    parts.append(value)
    backup = save_path(scope, parts)
    return parts, backup


def move_path(scope: str, from_idx: int, to_idx: int) -> Tuple[List[str], Path]:
    if from_idx < 1 or to_idx < 1:
        raise ValueError("Indices are 1-based and must be >=1.")
    raw, parts = load_path(scope)
    if from_idx > len(parts) or to_idx > len(parts):
        raise IndexError("Index out of range.")
    item = parts.pop(from_idx - 1)
    parts.insert(to_idx - 1, item)
    backup = save_path(scope, parts)
    return parts, backup
