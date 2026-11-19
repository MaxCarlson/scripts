"""Reversible, dry-run-first hook configuration installer and rollback for Codex and AGY."""

from __future__ import annotations

import contextlib
import json
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import ContinuityError, ErrorCode
from .models import Provider

MANAGED_KEY = "agent_continuity"
DEFAULT_CODEX_SHIM_CMD = "agents hook-shim -p codex"
DEFAULT_AGY_SHIM_CMD = "agents hook-shim -p agy"


def default_provider_config_dir(provider: str, *, home_dir: Path | None = None) -> Path:
    """Return the default user-level directory containing hooks.json for a provider."""
    base = home_dir or Path.home()
    norm = provider.strip().lower()
    if norm == Provider.CODEX.value:
        return base / ".codex"
    if norm == Provider.AGY.value:
        return base / ".gemini" / "config"
    raise ContinuityError(ErrorCode.INVALID_INPUT, f"Unsupported provider {provider!r}.")


def _atomic_write_text(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".tmp.{os.getpid()}.{secrets.token_hex(4)}")
    try:
        tmp.write_text(content, encoding="utf-8", newline="\n")
        os.replace(tmp, target)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise ContinuityError(
            ErrorCode.METADATA_INACCESSIBLE,
            f"Failed to write hook configuration {target}: {exc}",
            {"path": str(target)},
        ) from exc


def _backup_file(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    bak = path.with_name(f"{path.name}.bak.{stamp}")
    if bak.exists():
        bak = path.with_name(f"{path.name}.bak.{stamp}.{secrets.token_hex(2)}")
    _atomic_write_text(bak, path.read_text(encoding="utf-8"))
    return bak


def _load_hooks_json(hooks_path: Path) -> dict[str, Any]:
    if not hooks_path.exists():
        return {}
    try:
        data = json.loads(hooks_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContinuityError(
            ErrorCode.METADATA_INACCESSIBLE,
            f"Failed to parse existing {hooks_path}: {exc}",
            {"path": str(hooks_path)},
        ) from exc
    if not isinstance(data, dict):
        raise ContinuityError(
            ErrorCode.HOOK_SCHEMA_MISMATCH,
            f"Expected JSON object in {hooks_path}, got {type(data).__name__}.",
        )
    return data


def _is_managed_codex_handler(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    if entry.get("_managed_by") == MANAGED_KEY:
        return True
    cmd = str(entry.get("command") or "")
    return "agent_continuity" in cmd or "hook-shim -p codex" in cmd


def _build_codex_hooks(existing: dict[str, Any], shim_command: str) -> dict[str, Any]:
    updated = dict(existing)
    handler = {
        "type": "command",
        "command": shim_command,
        "commandWindows": shim_command,
        "timeout": 10,
        "_managed_by": MANAGED_KEY,
    }
    for event_name in ("SessionStart", "UserPromptSubmit", "Stop", "SessionEnd"):
        current = updated.get(event_name)
        items = list(current) if isinstance(current, list) else []
        cleaned = [item for item in items if not _is_managed_codex_handler(item)]
        cleaned.append(dict(handler))
        updated[event_name] = cleaned
    return updated


def _remove_codex_hooks(existing: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    updated = dict(existing)
    changed = False
    for event_name in ("SessionStart", "UserPromptSubmit", "Stop", "SessionEnd"):
        current = updated.get(event_name)
        if not isinstance(current, list):
            continue
        kept = [item for item in current if not _is_managed_codex_handler(item)]
        if len(kept) != len(current):
            changed = True
            if kept:
                updated[event_name] = kept
            else:
                updated.pop(event_name, None)
    return updated, changed


def _build_agy_hooks(
    existing: dict[str, Any],
    shim_command: str,
    *,
    include_session_start: bool,
) -> dict[str, Any]:
    updated = dict(existing)
    events = ["PreInvocation", "PostInvocation", "Stop"]
    if include_session_start:
        events.insert(0, "SessionStart")
    block: dict[str, Any] = {"enabled": True}
    for ev in events:
        block[ev] = [
            {
                "type": "command",
                "command": shim_command,
                "timeout": 10,
            }
        ]
    updated[MANAGED_KEY] = block
    return updated


def _remove_agy_hooks(existing: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    updated = dict(existing)
    changed = MANAGED_KEY in updated
    updated.pop(MANAGED_KEY, None)
    return updated, changed


def inspect_hooks_status(
    provider: str,
    *,
    config_dir: Path | str | None = None,
    home_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Inspect hook installation status and backups without modifying any provider files."""
    norm = provider.strip().lower()
    cfg_dir = Path(config_dir).expanduser().resolve() if config_dir else default_provider_config_dir(
        norm, home_dir=Path(home_dir) if home_dir else None
    )
    hooks_path = cfg_dir / "hooks.json"
    backups = sorted(str(p) for p in cfg_dir.glob("hooks.json.bak.*")) if cfg_dir.exists() else []

    if not hooks_path.exists():
        installed = False
        unrelated_count = 0
        parse_error = None
    else:
        try:
            data = _load_hooks_json(hooks_path)
            parse_error = None
            if norm == Provider.CODEX.value:
                installed = any(
                    isinstance(data.get(ev), list) and any(_is_managed_codex_handler(x) for x in data[ev])
                    for ev in ("SessionStart", "UserPromptSubmit", "Stop", "SessionEnd")
                )
                unrelated_count = sum(
                    1
                    for k, v in data.items()
                    if isinstance(v, list) and any(not _is_managed_codex_handler(x) for x in v)
                )
            else:
                installed = MANAGED_KEY in data
                unrelated_count = len([k for k in data if k != MANAGED_KEY])
        except ContinuityError as exc:
            installed = False
            unrelated_count = 0
            parse_error = exc.message

    legacy_notify = False
    if norm == Provider.CODEX.value:
        cfg_toml = cfg_dir / "config.toml"
        if cfg_toml.exists():
            with contextlib.suppress(OSError):
                legacy_notify = "notify" in cfg_toml.read_text(encoding="utf-8", errors="ignore")

    return {
        "provider": norm,
        "config_dir": str(cfg_dir),
        "hooks_path": str(hooks_path),
        "hooks_file_exists": hooks_path.exists(),
        "installed": installed,
        "unrelated_hooks_present": unrelated_count,
        "legacy_notify_present": legacy_notify,
        "backups": backups,
        "parse_error": parse_error,
    }


def install_hooks(
    provider: str,
    *,
    config_dir: Path | str | None = None,
    shim_command: str | None = None,
    include_session_start: bool = True,
    apply: bool = False,
) -> dict[str, Any]:
    """Preview or install module-owned hooks into hooks.json with automatic backup."""
    norm = provider.strip().lower()
    cfg_dir = Path(config_dir).expanduser().resolve() if config_dir else default_provider_config_dir(norm)
    hooks_path = cfg_dir / "hooks.json"
    existing = _load_hooks_json(hooks_path)

    if norm == Provider.CODEX.value:
        cmd = shim_command or DEFAULT_CODEX_SHIM_CMD
        proposed = _build_codex_hooks(existing, cmd)
    elif norm == Provider.AGY.value:
        cmd = shim_command or DEFAULT_AGY_SHIM_CMD
        proposed = _build_agy_hooks(existing, cmd, include_session_start=include_session_start)
    else:
        raise ContinuityError(ErrorCode.INVALID_INPUT, f"Unsupported provider {provider!r}.")

    backup_path: Path | None = None
    if apply:
        backup_path = _backup_file(hooks_path)
        _atomic_write_text(hooks_path, json.dumps(proposed, indent=2, sort_keys=True) + "\n")

    return {
        "action": "hooks.install",
        "provider": norm,
        "applied": apply,
        "hooks_path": str(hooks_path),
        "backup_path": str(backup_path) if backup_path else None,
        "proposed": proposed,
        "summary": (
            f"Installed {norm} hooks at {hooks_path}"
            if apply
            else f"Dry-run: would install {norm} hooks at {hooks_path}"
        ),
    }


def uninstall_hooks(
    provider: str,
    *,
    config_dir: Path | str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Preview or remove only agent_continuity-managed hooks while preserving unrelated hooks."""
    norm = provider.strip().lower()
    cfg_dir = Path(config_dir).expanduser().resolve() if config_dir else default_provider_config_dir(norm)
    hooks_path = cfg_dir / "hooks.json"
    existing = _load_hooks_json(hooks_path)

    if norm == Provider.CODEX.value:
        proposed, changed = _remove_codex_hooks(existing)
    elif norm == Provider.AGY.value:
        proposed, changed = _remove_agy_hooks(existing)
    else:
        raise ContinuityError(ErrorCode.INVALID_INPUT, f"Unsupported provider {provider!r}.")

    backup_path: Path | None = None
    if apply and changed:
        backup_path = _backup_file(hooks_path)
        _atomic_write_text(hooks_path, json.dumps(proposed, indent=2, sort_keys=True) + "\n")

    return {
        "action": "hooks.uninstall",
        "provider": norm,
        "applied": apply,
        "changed": changed,
        "hooks_path": str(hooks_path),
        "backup_path": str(backup_path) if backup_path else None,
        "summary": (
            f"Removed agent_continuity {norm} hooks from {hooks_path}"
            if apply and changed
            else f"Dry-run: would remove agent_continuity {norm} hooks from {hooks_path}"
            if changed
            else f"No agent_continuity {norm} hooks installed at {hooks_path}"
        ),
    }


def rollback_hooks(
    provider: str,
    *,
    config_dir: Path | str | None = None,
    backup_path: Path | str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Restore hooks.json from the latest (or specified) backup file."""
    norm = provider.strip().lower()
    cfg_dir = Path(config_dir).expanduser().resolve() if config_dir else default_provider_config_dir(norm)
    hooks_path = cfg_dir / "hooks.json"

    if backup_path is not None:
        bak = Path(backup_path).expanduser().resolve()
    else:
        candidates = sorted(cfg_dir.glob("hooks.json.bak.*")) if cfg_dir.exists() else []
        if not candidates:
            raise ContinuityError(
                ErrorCode.METADATA_INACCESSIBLE,
                f"No hooks.json backup files found in {cfg_dir}.",
            )
        bak = candidates[-1]

    if not bak.exists():
        raise ContinuityError(ErrorCode.METADATA_INACCESSIBLE, f"Backup file not found: {bak}")

    content = bak.read_text(encoding="utf-8")
    # Validate JSON before restoring
    json.loads(content)
    if apply:
        _atomic_write_text(hooks_path, content)

    return {
        "action": "hooks.rollback",
        "provider": norm,
        "applied": apply,
        "hooks_path": str(hooks_path),
        "restored_from": str(bak),
        "summary": (
            f"Restored {hooks_path} from {bak}"
            if apply
            else f"Dry-run: would restore {hooks_path} from {bak}"
        ),
    }
