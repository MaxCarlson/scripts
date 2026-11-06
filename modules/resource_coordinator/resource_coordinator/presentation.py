"""Shared Rich presentation and clean structured-output helpers for the CLI."""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Mapping, Optional, TextIO

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

_color_mode = "auto"
_SECRET_KEYS = {"token", "operator_token", "recovery_token", "secret", "password", "authorization", "api_key"}
_SUCCESS = {"ok", "ready", "running", "healthy", "verified", "valid", "started", "enabled"}
_WARNING = {"degraded", "paused", "pending", "cooling", "planned"}
_FAILURE = {"failed", "blocked", "error", "unsafe", "recovery-required", "unavailable"}


def set_color_mode(mode: str) -> None:
    if mode not in {"auto", "always", "never"}:
        raise ValueError(f"Unsupported color mode: {mode}")
    global _color_mode
    _color_mode = mode


def make_console(
    *, color: Optional[str] = None, stream: Optional[TextIO] = None,
    environ: Optional[Mapping[str, str]] = None, width: Optional[int] = None,
) -> Console:
    selected = color or _color_mode
    env = os.environ if environ is None else environ
    target = sys.stdout if stream is None else stream
    has_terminal = bool(getattr(target, "isatty", lambda: False)())
    no_color = selected == "never" or (
        selected == "auto" and (bool(env.get("NO_COLOR")) or not has_terminal)
    )
    return Console(
        file=target,
        color_system=None if no_color else ("truecolor" if selected == "always" else "auto"),
        force_terminal=True if selected == "always" else False if selected == "never" else None,
        no_color=no_color,
        width=width,
        highlight=False,
        markup=False,
        soft_wrap=True,
    )


def _sensitive(key: Any) -> bool:
    name = re.sub(r"[^a-z0-9]+", "_", str(key).casefold()).strip("_")
    if name.endswith("_path") and "token" in name:
        return False
    return (
        name in _SECRET_KEYS
        or "token" in name
        or "password" in name
        or "secret" in name
        or "authorization" in name
        or name.endswith(("_api_key", "apikey", "_private_key"))
    )


def _redact(value: Any, key: Any = None) -> Any:
    if key is not None and _sensitive(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(item_key): _redact(item_value, item_key) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


def emit_json(value: Any, *, stream: Optional[TextIO] = None) -> None:
    target = sys.stdout if stream is None else stream
    target.write(json.dumps(_redact(value), indent=2, ensure_ascii=False, default=str))
    target.write("\n")


def emit_text(value: Any, *, style: Optional[str] = None, stream: Optional[TextIO] = None) -> None:
    console = make_console(stream=stream)
    console.print(Text(str(value), style=style))


def emit_error(value: Any, *, stream: Optional[TextIO] = None) -> None:
    console = make_console(stream=sys.stderr if stream is None else stream)
    console.print(Text(str(value), style="red"))


def _status_value(data: Mapping[str, Any]) -> Optional[str]:
    for key in ("status", "service_state", "state", "result"):
        value = data.get(key)
        if value is not None:
            return str(value)
    return None


def _status_style(status: Optional[str]) -> Optional[str]:
    if status is None:
        return None
    value = re.sub(r"[^a-z0-9]+", "-", status.casefold()).strip("-")
    if value in _FAILURE or any(
        part in value for part in ("failed", "failure", "blocked", "error", "unsafe", "unavailable", "unhealthy", "invalid")
    ):
        return "red"
    if value in _WARNING or value.startswith("not-") or any(
        part in value for part in ("pending", "paused", "cooling", "degraded")
    ):
        return "yellow"
    if value in _SUCCESS or any(part in value for part in ("ready", "running", "verified", "healthy", "valid")):
        return "green"
    return None


def _display_value(value: Any) -> str:
    if value is None:
        return "Unknown"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, Mapping):
        return "; ".join(f"{key}: {_display_value(item)}" for key, item in value.items()) or "None"
    if isinstance(value, (list, tuple)):
        return ", ".join(_display_value(item) for item in value) or "None"
    return str(value)


def render_result(
    title: str,
    data: Mapping[str, Any],
    *,
    stream: Optional[TextIO] = None,
    color: Optional[str] = None,
    width: Optional[int] = None,
) -> None:
    console = make_console(color=color, stream=stream, width=width)
    safe_data = _redact(data)
    status = _status_value(safe_data)
    heading = Text(title)
    if status:
        heading.append("  ")
        heading.append(status.upper(), style=_status_style(status))
    console.print(heading)

    table = Table(box=box.SIMPLE, show_header=False, pad_edge=False, expand=True)
    table.add_column("Field", style="bold cyan", ratio=1, no_wrap=True)
    table.add_column("Value", ratio=3, overflow="fold")
    for key, value in safe_data.items():
        if key in {"status", "service_state", "state", "result"}:
            continue
        table.add_row(str(key).replace("_", " ").capitalize(), _display_value(value))
    if status:
        table.add_row("Status", Text(status, style=_status_style(status)))
    if table.row_count:
        console.print(table)


def render_coordinator_status(data: Mapping[str, Any], *, as_json: bool = False) -> None:
    if as_json:
        emit_json(data)
        return
    console = make_console()
    ready = bool(data.get("is_ready"))
    state = str(data.get("service_state") or "unknown")
    console.print(Text("Resource Coordinator", style="bold"))
    console.print(Text(f"Service: {state.upper()}   Ready: {'Yes' if ready else 'No'}",
                       style="green" if ready else "yellow"))

    service = Table(title="Service", box=box.SIMPLE, show_header=False, pad_edge=False)
    service.add_column("Field", style="bold cyan")
    service.add_column("Value", overflow="fold")
    service.add_row("Upstream", str(data.get("upstream_url") or "Unknown"))
    gpu = data.get("gpu_inference") or {}
    service.add_row("Inference", f"{gpu.get('active_count', 'Unknown')} active / {gpu.get('pending_count', 'Unknown')} pending")
    cooldown = "Active"
    if gpu.get("is_cooling_down"):
        remaining = gpu.get("cooldown_remaining")
        cooldown = f"Active ({remaining}s remaining)" if remaining is not None else "Active"
    else:
        cooldown = "Inactive"
    service.add_row("Cooldown", cooldown)
    service.add_row("Restart inhibited", "Yes" if gpu.get("is_restart_inhibited") else "No")
    console.print(service)

    processes = data.get("processes") or {}
    if processes:
        table = Table(title="Managed Processes", box=box.SIMPLE, pad_edge=False)
        table.add_column("Process", style="bold")
        table.add_column("State")
        table.add_column("PID", justify="right")
        table.add_column("Ownership", overflow="fold")
        for name, process in processes.items():
            ownership = str(process.get("lifecycle_owner") or "unknown")
            if process.get("is_coordinator_owned"):
                ownership += "; Coordinator-owned"
            if process.get("was_stopped_by_coordinator"):
                ownership += "; Stopped by coordinator"
            table.add_row(
                str(name), str(process.get("state") or "unknown"), str(process.get("pid") or "—"),
                ownership,
            )
        console.print(table)
