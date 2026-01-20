"""PATH management helpers with Windows registry support."""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from cross_platform.path_utils import expand_path
from cross_platform.system_utils import SystemUtils

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

SCOPE_USER = "User"
SCOPE_MACHINE = "Machine"
SCOPE_PROCESS = "Process"

DEFAULT_PATHEXT = [".com", ".exe", ".bat", ".cmd", ".ps1"]

if os.name == "nt":
    import ctypes
    import ctypes.wintypes as wt
    import winreg


@dataclass(frozen=True)
class CommandRecord:
    name: str
    paths: List[Path]


@dataclass(frozen=True)
class WriteResult:
    scope: str
    old_value: str
    new_value: str
    changed: bool
    backup_file: Optional[Path]
    added: List[str]
    removed: List[str]


def _path_separator(system: Optional[SystemUtils] = None) -> str:
    system = system or SystemUtils()
    if system.is_windows():
        return ";"
    return os.pathsep


def _segment_key(segment: str, system: Optional[SystemUtils] = None) -> str:
    system = system or SystemUtils()
    return segment.lower() if system.is_windows() else segment


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _ts() -> str:
    return datetime.now().isoformat(timespec="seconds")


def get_backup_dir() -> Path:
    raw = os.environ.get("PATHMGR_BACKUPS") or os.environ.get("PWSH_PATHMGR_BACKUPS")
    if raw:
        return Path(raw)
    return Path.home() / "PathBackups"


def ensure_backup_dir(backup_dir: Path) -> None:
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.warning("Failed to create backup dir %s: %s", backup_dir, exc)


def normalize_segments(segments: Iterable[str], system: Optional[SystemUtils] = None) -> List[str]:
    system = system or SystemUtils()
    out: List[str] = []
    seen = set()
    for segment in segments:
        if segment is None:
            continue
        cleaned = str(segment).replace("\r", "").replace("\n", "")
        cleaned = cleaned.strip().strip('"').strip()
        if not cleaned:
            continue
        key = _segment_key(cleaned, system)
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def split_path_string(path_str: str, *, system: Optional[SystemUtils] = None, dedupe: bool = True) -> List[str]:
    if not path_str:
        return []
    system = system or SystemUtils()
    sep = _path_separator(system)
    cleaned = path_str.replace("\r", "").replace("\n", "")
    cleaned = cleaned.replace(f"{sep}{sep}", sep)
    parts = [p for p in cleaned.split(sep) if p is not None]
    if dedupe:
        return normalize_segments(parts, system)
    return [str(p).strip().strip('"').strip() for p in parts]


def split_tokens_loose(path_str: str, *, system: Optional[SystemUtils] = None) -> List[str]:
    if path_str is None:
        return []
    system = system or SystemUtils()
    sep = _path_separator(system)
    cleaned = path_str.replace("\r", "").replace("\n", "")
    tokens = []
    for part in cleaned.split(sep):
        tokens.append(str(part).strip().strip('"').strip())
    return tokens


def join_segments(segments: Iterable[str], *, system: Optional[SystemUtils] = None) -> str:
    system = system or SystemUtils()
    sep = _path_separator(system)
    return sep.join(list(segments))


def build_new_string(
    base_str: str,
    *,
    add: Optional[Iterable[str]] = None,
    remove: Optional[Iterable[str]] = None,
    cleanup: bool = False,
    dedupe: bool = True,
    system: Optional[SystemUtils] = None,
) -> str:
    system = system or SystemUtils()
    segs = split_path_string(base_str, system=system, dedupe=cleanup or dedupe)
    if remove:
        to_remove: List[str] = []
        for raw in remove:
            if raw is None:
                continue
            item = str(raw).strip()
            if not item:
                continue
            item_key = _segment_key(item, system)
            if item_key.startswith("contains:"):
                needle = item_key.split(":", 1)[1].strip()
                to_remove.extend([s for s in segs if needle in _segment_key(s, system)])
            else:
                to_remove.extend([s for s in segs if _segment_key(s, system) == item_key])
        if to_remove:
            remove_keys = {_segment_key(s, system) for s in to_remove}
            segs = [s for s in segs if _segment_key(s, system) not in remove_keys]

    if add:
        existing = {_segment_key(s, system) for s in segs}
        for raw in add:
            if raw is None:
                continue
            item = str(raw).strip().strip('"')
            if not item:
                continue
            key = _segment_key(item, system)
            if key in existing:
                continue
            segs.append(item)
            existing.add(key)

    if dedupe:
        segs = normalize_segments(segs, system)

    return join_segments(segs, system=system)


def _read_windows_registry_path(scope: str) -> str:
    if scope == SCOPE_USER:
        root, subkey = winreg.HKEY_CURRENT_USER, r"Environment"
    elif scope == SCOPE_MACHINE:
        root, subkey = winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
    else:
        raise ValueError("Invalid scope for registry read")
    with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ) as key:
        try:
            value, _ = winreg.QueryValueEx(key, "Path")
            return value
        except FileNotFoundError:
            return ""


def _write_windows_registry_path(scope: str, path_str: str) -> None:
    if scope == SCOPE_USER:
        root, subkey = winreg.HKEY_CURRENT_USER, r"Environment"
    elif scope == SCOPE_MACHINE:
        root, subkey = winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
    else:
        raise ValueError("Invalid scope for registry write")
    with winreg.OpenKey(root, subkey, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, path_str)


def broadcast_env_change() -> None:
    if os.name != "nt":
        return
    try:
        hwnd_broadcast = 0xFFFF
        wm_settingchange = 0x001A
        smto_abortifhung = 0x0002
        send = ctypes.windll.user32.SendMessageTimeoutW
        send.argtypes = [
            wt.HWND,
            wt.UINT,
            wt.WPARAM,
            wt.LPARAM,
            wt.UINT,
            wt.UINT,
            ctypes.POINTER(wt.DWORD),
        ]
        result = wt.DWORD(0)
        send(hwnd_broadcast, wm_settingchange, 0, ctypes.c_wchar_p("Environment"), smto_abortifhung, 5000, ctypes.byref(result))
    except Exception as exc:
        logger.debug("Failed to broadcast env change: %s", exc)


def read_path(scope: str, *, system: Optional[SystemUtils] = None) -> str:
    system = system or SystemUtils()
    if scope == SCOPE_PROCESS:
        return os.environ.get("Path") or os.environ.get("PATH") or ""
    if not system.is_windows():
        raise SystemExit("User/Machine scopes are Windows-only.")
    return _read_windows_registry_path(scope)


def write_path(scope: str, value: str, *, system: Optional[SystemUtils] = None) -> None:
    system = system or SystemUtils()
    if scope == SCOPE_PROCESS:
        os.environ["Path"] = value
        return
    if not system.is_windows():
        raise SystemExit("Registry writes are Windows-only.")
    _write_windows_registry_path(scope, value)
    broadcast_env_change()


def compute_diff(old_value: str, new_value: str, *, system: Optional[SystemUtils] = None) -> Tuple[List[str], List[str]]:
    system = system or SystemUtils()
    old = split_path_string(old_value, system=system)
    new = split_path_string(new_value, system=system)
    old_map = {_segment_key(s, system): s for s in old}
    new_map = {_segment_key(s, system): s for s in new}
    added = [new_map[key] for key in new_map.keys() - old_map.keys()]
    removed = [old_map[key] for key in old_map.keys() - new_map.keys()]
    return added, removed


def get_invalid_segments(segments: Iterable[str], *, system: Optional[SystemUtils] = None) -> List[str]:
    system = system or SystemUtils()
    invalid: List[str] = []
    for segment in segments:
        expanded = expand_path(segment)
        if not Path(expanded).is_dir():
            invalid.append(segment)
    return invalid


def backup_all(*, system: Optional[SystemUtils] = None) -> Path:
    system = system or SystemUtils()
    backup_dir = get_backup_dir()
    ensure_backup_dir(backup_dir)
    scopes = [SCOPE_PROCESS]
    if system.is_windows():
        scopes = [SCOPE_USER, SCOPE_MACHINE, SCOPE_PROCESS]
    data = {
        "when": _ts(),
        "scopes": {},
    }
    for scope in scopes:
        value = read_path(scope, system=system)
        data["scopes"][scope] = {
            "path_string": value,
            "segments": split_path_string(value, system=system),
        }
    dest = backup_dir / f"PATH-ALL-{_now_stamp()}.json"
    dest.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return dest


def coerce_to_directory(value: str, *, system: Optional[SystemUtils] = None) -> Path:
    system = system or SystemUtils()
    candidate = expand_path(value.strip().strip('"'))
    path = Path(candidate)
    if path.is_file():
        return path.parent
    if system.is_windows():
        suffix = path.suffix.lower()
        if suffix and suffix in get_pathexts(system):
            return path.parent
    return path


def get_pathexts(system: Optional[SystemUtils] = None) -> List[str]:
    system = system or SystemUtils()
    if not system.is_windows():
        return []
    raw = os.environ.get("PATHEXT")
    if not raw:
        return list(DEFAULT_PATHEXT)
    return [item.strip().lower() for item in raw.split(";") if item.strip()]


def list_executables_in_dir(dir_path: Path, *, system: Optional[SystemUtils] = None) -> Dict[str, List[Path]]:
    system = system or SystemUtils()
    if not dir_path.is_dir():
        return {}
    results: Dict[str, List[Path]] = {}
    if system.is_windows():
        pathexts = get_pathexts(system)
        ext_order = {ext: idx for idx, ext in enumerate(pathexts)}
        for item in dir_path.iterdir():
            if not item.is_file():
                continue
            suffix = item.suffix.lower()
            if suffix not in ext_order:
                continue
            name_key = item.stem.lower()
            results.setdefault(name_key, []).append(item)
        for key, paths in results.items():
            paths.sort(key=lambda p: (ext_order.get(p.suffix.lower(), 999), p.name.lower()))
    else:
        for item in dir_path.iterdir():
            if not item.is_file():
                continue
            try:
                if not os.access(item, os.X_OK):
                    continue
            except Exception:
                continue
            name_key = item.name
            results.setdefault(name_key, []).append(item)
    return results


def build_command_index(path_segments: Iterable[str], *, system: Optional[SystemUtils] = None) -> Dict[str, CommandRecord]:
    system = system or SystemUtils()
    index: Dict[str, CommandRecord] = {}
    for raw in path_segments:
        expanded = expand_path(raw)
        dir_path = Path(expanded)
        exec_map = list_executables_in_dir(dir_path, system=system)
        for name_key, paths in exec_map.items():
            if name_key not in index:
                display = paths[0].stem if system.is_windows() else paths[0].name
                index[name_key] = CommandRecord(name=display, paths=list(paths))
            else:
                index[name_key].paths.extend(paths)
    return index


def build_resolution_map(path_segments: Iterable[str], *, system: Optional[SystemUtils] = None) -> Dict[str, Path]:
    system = system or SystemUtils()
    resolved: Dict[str, Path] = {}
    for raw in path_segments:
        expanded = expand_path(raw)
        dir_path = Path(expanded)
        exec_map = list_executables_in_dir(dir_path, system=system)
        for name_key, paths in exec_map.items():
            if name_key in resolved:
                continue
            resolved[name_key] = paths[0]
    return resolved


def get_combined_segments(*, system: Optional[SystemUtils] = None) -> List[str]:
    system = system or SystemUtils()
    if not system.is_windows():
        return split_path_string(read_path(SCOPE_PROCESS, system=system), system=system)
    machine = split_path_string(read_path(SCOPE_MACHINE, system=system), system=system)
    user = split_path_string(read_path(SCOPE_USER, system=system), system=system)
    return normalize_segments(machine + user, system)


def analyze_resolution_changes(
    old_segments: Iterable[str],
    new_segments: Iterable[str],
    *,
    system: Optional[SystemUtils] = None,
) -> Dict[str, Tuple[Path, Path]]:
    system = system or SystemUtils()
    before = build_resolution_map(old_segments, system=system)
    after = build_resolution_map(new_segments, system=system)
    changes: Dict[str, Tuple[Path, Path]] = {}
    for key, before_path in before.items():
        after_path = after.get(key)
        if after_path is None:
            continue
        if before_path != after_path:
            changes[key] = (before_path, after_path)
    return changes


def safe_write_path(
    scope: str,
    new_value: str,
    *,
    system: Optional[SystemUtils] = None,
    dry_run: bool = False,
    force: bool = False,
    confirm: bool = False,
    allow_shrink: bool = True,
) -> WriteResult:
    system = system or SystemUtils()
    old_value = read_path(scope, system=system)
    old_tokens = split_tokens_loose(old_value, system=system)
    new_tokens = split_tokens_loose(new_value, system=system)

    if not split_path_string(new_value, system=system):
        raise ValueError(f"Refusing to write empty PATH for {scope}.")

    if not allow_shrink and not force:
        old_count = sum(1 for t in old_tokens if t)
        new_count = sum(1 for t in new_tokens if t)
        if new_count < old_count:
            raise ValueError("Refusing to shrink PATH without --force.")

    added, removed = compute_diff(old_value, new_value, system=system)

    if dry_run:
        return WriteResult(scope=scope, old_value=old_value, new_value=new_value, changed=False, backup_file=None, added=added, removed=removed)

    if not confirm:
        if not bool(getattr(sys.stdin, "isatty", lambda: False)()):
            raise ValueError("Confirmation required in non-interactive mode. Use --confirm.")
        try:
            reply = input("Proceed? [y/N]: ")
        except EOFError as exc:
            raise ValueError("Confirmation required.") from exc
        if reply.strip().lower() not in ("y", "yes"):
            raise ValueError("Confirmation declined.")

    backup_file = backup_all(system=system)
    write_path(scope, new_value, system=system)
    return WriteResult(scope=scope, old_value=old_value, new_value=new_value, changed=True, backup_file=backup_file, added=added, removed=removed)


def resolve_scope(value: str) -> str:
    if not value:
        return SCOPE_USER
    v = value.strip().lower()
    if v in ("u", "user"):
        return SCOPE_USER
    if v in ("m", "machine", "system"):
        return SCOPE_MACHINE
    if v in ("p", "proc", "process"):
        return SCOPE_PROCESS
    if v in ("c", "combined"):
        return "Combined"
    raise ValueError(f"Invalid scope: {value}")


def load_backup(path: Path) -> Dict[str, Dict[str, object]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    scopes = data.get("scopes") or {}
    return scopes
