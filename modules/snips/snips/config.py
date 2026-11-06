"""Versioned configuration and text-action helpers."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
CURSOR = "{{cursor}}"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MODIFIERS = {"ctrl": "^", "control": "^", "alt": "!", "shift": "+", "win": "#", "windows": "#"}
KEYS = {
    "space": "Space",
    "enter": "Enter",
    "tab": "Tab",
    "escape": "Escape",
    "esc": "Escape",
    "backspace": "Backspace",
    "delete": "Delete",
    "del": "Delete",
    "insert": "Insert",
    "home": "Home",
    "end": "End",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "pageup": "PgUp",
    "pgup": "PgUp",
    "pagedown": "PgDn",
    "pgdn": "PgDn",
    "capslock": "CapsLock",
}


class ConfigError(ValueError):
    """Invalid configuration or command input."""


def parse_hotkey(value: str) -> tuple[str, str]:
    """Return (canonical display, AutoHotkey v2 key string)."""
    parts = [part.strip() for part in value.split("+") if part.strip()]
    if len(parts) < 2:
        raise ConfigError(f"Invalid hotkey {value!r}: use a modifier and one key, such as Ctrl+Alt+B")
    modifiers = parts[:-1]
    key = parts[-1]
    codes: list[str] = []
    names: list[str] = []
    seen: set[str] = set()
    for modifier in modifiers:
        normalized = modifier.casefold()
        if normalized not in MODIFIERS:
            raise ConfigError(f"Unknown hotkey modifier {modifier!r}")
        code = MODIFIERS[normalized]
        if code in seen:
            raise ConfigError(f"Duplicate hotkey modifier {modifier!r}")
        seen.add(code)
        codes.append(code)
        names.append({"^": "Ctrl", "!": "Alt", "+": "Shift", "#": "Win"}[code])
    order = {"^": 0, "!": 1, "+": 2, "#": 3}
    codes.sort(key=order.__getitem__)
    names = [{"^": "Ctrl", "!": "Alt", "+": "Shift", "#": "Win"}[code] for code in codes]
    lower_key = key.casefold()
    if re.fullmatch(r"[a-z0-9]", lower_key):
        ahk_key = lower_key
        display_key = lower_key.upper()
    elif re.fullmatch(r"f(?:[1-9]|1[0-9]|2[0-4])", lower_key):
        ahk_key = lower_key
        display_key = lower_key.upper()
    elif lower_key in KEYS:
        ahk_key = KEYS[lower_key]
        display_key = ahk_key
    else:
        raise ConfigError(f"Unsupported hotkey key {key!r}")
    return "+".join([*names, display_key]), "".join(codes) + ahk_key


def validate_definition(definition: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(definition, dict):
        raise ConfigError("Each binding must be an object")
    required = {"id", "name", "kind", "hotkey", "enabled"}
    missing = required - definition.keys()
    if missing:
        raise ConfigError(f"Binding is missing fields: {', '.join(sorted(missing))}")
    binding_id = definition["id"]
    if not isinstance(binding_id, str) or not ID_RE.fullmatch(binding_id):
        raise ConfigError("Binding id must use lowercase letters, numbers, hyphens, or underscores (max 64 chars)")
    if not isinstance(definition["name"], str) or not definition["name"].strip():
        raise ConfigError(f"Binding {binding_id!r} needs a non-empty name")
    kind = definition["kind"]
    if kind not in {"template", "clipboard-fence", "selection-fence"}:
        raise ConfigError(f"Binding {binding_id!r} has unsupported kind {kind!r}")
    display, ahk = parse_hotkey(str(definition["hotkey"]))
    enabled = definition["enabled"]
    if not isinstance(enabled, bool):
        raise ConfigError(f"Binding {binding_id!r}: enabled must be true or false")
    output = {"id": binding_id, "name": definition["name"].strip(), "kind": kind, "hotkey": display, "enabled": enabled}
    if kind == "template":
        content = definition.get("content")
        if not isinstance(content, str):
            raise ConfigError(f"Template {binding_id!r} requires string content")
        if content.count(CURSOR) > 1:
            raise ConfigError(f"Template {binding_id!r} may contain at most one {CURSOR} marker")
        output["content"] = content
    if definition.get("description") is not None:
        if not isinstance(definition["description"], str):
            raise ConfigError(f"Binding {binding_id!r}: description must be text")
        output["description"] = definition["description"]
    output["_ahk_hotkey"] = ahk
    return output


def validate_config(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise ConfigError(f"Configuration schema_version must be {SCHEMA_VERSION}")
    settings = value.get("settings", {})
    bindings = value.get("bindings", [])
    if not isinstance(settings, dict) or not isinstance(bindings, list):
        raise ConfigError("Configuration settings must be an object and bindings must be a list")
    settings = dict(settings)
    delay = settings.get("clipboard_restore_delay_ms", 250)
    if isinstance(delay, bool) or not isinstance(delay, int) or not 50 <= delay <= 5000:
        raise ConfigError("settings.clipboard_restore_delay_ms must be an integer from 50 to 5000")
    settings["clipboard_restore_delay_ms"] = delay
    clean: list[dict[str, Any]] = []
    ids: set[str] = set()
    shortcuts: dict[str, str] = {}
    for raw in bindings:
        binding = validate_definition(raw)
        if binding["id"] in ids:
            raise ConfigError(f"Duplicate binding id {binding['id']!r}")
        ids.add(binding["id"])
        normalized_key = binding["_ahk_hotkey"].casefold()
        if normalized_key in shortcuts:
            raise ConfigError(
                f"Hotkey collision: {binding['hotkey']} is assigned to both {shortcuts[normalized_key]!r} and {binding['id']!r}"
            )
        shortcuts[normalized_key] = binding["id"]
        binding.pop("_ahk_hotkey")
        clean.append(binding)
    return {"schema_version": SCHEMA_VERSION, "settings": settings, "bindings": clean}


def default_config() -> dict[str, Any]:
    return validate_config(
        {
            "schema_version": SCHEMA_VERSION,
            "settings": {"clipboard_restore_delay_ms": 250},
            "bindings": [
                {
                    "id": "markdown-code-block",
                    "name": "Markdown code block",
                    "kind": "template",
                    "hotkey": "Ctrl+Alt+B",
                    "enabled": True,
                    "content": "```\n{{cursor}}\n```",
                },
                {
                    "id": "markdown-fence-clipboard",
                    "name": "Fence clipboard text",
                    "kind": "clipboard-fence",
                    "hotkey": "Ctrl+Alt+V",
                    "enabled": True,
                },
            ],
        }
    )


def load_config(path: Path, *, missing_ok: bool = False) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if missing_ok:
            return default_config()
        raise ConfigError(f"Configuration does not exist: {path}; run `snips install --apply` first") from None
    try:
        return validate_config(json.loads(text))
    except (json.JSONDecodeError, TypeError) as exc:
        raise ConfigError(f"Invalid JSON configuration at {path}: {exc}") from exc


def serialize_config(value: dict[str, Any]) -> str:
    return json.dumps(validate_config(value), ensure_ascii=False, indent=2) + "\n"


def atomic_write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "wb" if isinstance(content, bytes) else "w"
    kwargs = {} if mode == "wb" else {"encoding": "utf-8", "newline": ""}
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, mode, **kwargs) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def markdown_fence(text: str) -> str:
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{text}\n{fence}"


def template_payload(template: str) -> tuple[str, int]:
    marker_index = template.find(CURSOR)
    if marker_index < 0:
        return template, 0
    value = template.replace(CURSOR, "", 1)
    suffix_start = marker_index
    suffix = template[suffix_start + len(CURSOR) :]
    return value, len(suffix)


def config_default_path() -> Path:
    root = os.environ.get("APPDATA") or (Path.home() / ".config")
    return Path(root) / "snips" / "config.json"


def runtime_default_path() -> Path:
    root = os.environ.get("LOCALAPPDATA") or (Path.home() / ".local" / "state")
    return Path(root) / "snips" / "runtime"
