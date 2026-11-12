"""Shared Rich presentation and clean structured-output helpers for the CLI."""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, TextIO
from urllib.parse import urlsplit

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

_color_mode = "auto"
_SECRET_KEYS = {"token", "operator_token", "recovery_token", "secret", "password", "authorization", "api_key"}
_SUCCESS = {"ok", "ready", "running", "active", "healthy", "verified", "valid", "started", "enabled",
            "applied", "already-current", "complete", "completed"}
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
        return f"{len(value)} structured fields (see --json)" if value else "None"
    if isinstance(value, (list, tuple)):
        if not value:
            return "None"
        if any(isinstance(item, Mapping) for item in value):
            return f"{len(value)} structured items (see --json)"
        return ", ".join(_display_value(item) for item in value)
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
    table.add_column("Field", style="bold cyan", ratio=1, no_wrap=False)
    table.add_column("Value", ratio=3, overflow="fold")
    for key, value in safe_data.items():
        if key in {"status", "service_state", "state", "result"}:
            continue
        table.add_row(str(key).replace("_", " ").capitalize(), _display_value(value))
    if table.row_count:
        console.print(table)


def _human_time(value: Any) -> str:
    if value is None:
        return "Unavailable"
    try:
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            moment = parsed.astimezone()
        else:
            moment = datetime.fromtimestamp(float(value), tz=timezone.utc).astimezone()
        return moment.strftime("%b %d, %Y, %I:%M %p").replace(" 0", " ")
    except (OverflowError, OSError, TypeError, ValueError):
        return "Unavailable"


def _table(title: str, rows: list[tuple[str, Any]], *, console: Console) -> None:
    if not rows:
        return
    table = Table(title=title, box=box.SIMPLE, show_header=False, pad_edge=False, expand=True)
    table.add_column("Field", style="bold cyan", ratio=1, no_wrap=False)
    table.add_column("Value", ratio=3, overflow="fold")
    for key, value in rows:
        table.add_row(key, str(value))
    console.print(table)


def render_miner_status(
    data: Mapping[str, Any], *, as_json: bool = False, stream: Optional[TextIO] = None,
    color: Optional[str] = None, width: Optional[int] = None,
) -> None:
    if as_json:
        emit_json(data, stream=stream)
        return
    data = _redact(data)
    console = make_console(color=color, stream=stream, width=width)
    process = data.get("process") if isinstance(data.get("process"), Mapping) else data
    fallback_status = data.get("status")
    if fallback_status in {"ok", "success"}:
        fallback_status = None
    status = str(process.get("state") or fallback_status or "unknown").replace("_", " ")
    name = str(process.get("name") or data.get("name") or "miner")
    heading = Text(f"Miner — {name}")
    heading.append("  ")
    heading.append(status.upper(), style=_status_style(status))
    console.print(heading)

    pid = process.get("pid")
    running = status.casefold() in {"running", "external_running"}
    owner_name = str(process.get("lifecycle_owner") or "").casefold()
    owner = ("Coordinator" if process.get("is_coordinator_owned") else
             owner_name.title() if owner_name in {"external", "unmanaged"} else "Unverified")
    _table("Process", [
        ("PID", pid if pid is not None else ("Not running" if not running else "Unavailable")),
        ("Ownership", owner),
        ("Executable", process.get("executable") or "Unavailable" if running else "Not running"),
        ("Started", _human_time(process.get("create_time")) if running else "Not running"),
    ], console=console)

    manual = data.get("manual_override")
    deadline = data.get("manual_override_until")
    if manual is True:
        hold = f"Until {_human_time(deadline)}" if deadline is not None else "Active"
    elif manual is False:
        hold = "Inactive"
    else:
        hold = "Unavailable"
    condition = data.get("gpu_idle_condition")
    if isinstance(condition, Mapping) and condition:
        gpu_idle = f"Below {condition.get('threshold_pct', '?')}% for {condition.get('window_seconds', '?')}s"
    elif isinstance(condition, Mapping):
        gpu_idle = "Not configured"
    else:
        gpu_idle = "Unavailable"
    _table("Controls", [("Manual hold", hold), ("Timed resume", _human_time(deadline) if manual and deadline else "None"),
                         ("GPU-idle resume", gpu_idle)], console=console)
    reason = data.get("reason")
    if reason:
        console.print(Text(f"Reason  {reason}"))


def render_gaming_status(
    data: Mapping[str, Any], *, as_json: bool = False, stream: Optional[TextIO] = None,
    color: Optional[str] = None, width: Optional[int] = None,
) -> None:
    if as_json:
        emit_json(data, stream=stream)
        return
    data = _redact(data)
    console = make_console(color=color, stream=stream, width=width)
    state = str(data.get("state") or data.get("status") or "unknown").replace("_", " ")
    heading = Text("Gaming Mode")
    heading.append("  ")
    heading.append(state.upper(), style=_status_style(state))
    console.print(heading)
    rows = [("Mode", state.title())]
    if data.get("miner_state") is not None:
        rows.append(("Miner", str(data["miner_state"]).replace("_", " ").title()))
    models = data.get("models")
    if isinstance(models, list):
        rows.append(("Models to restore", ", ".join(str(item) for item in models) or "None"))
    elif isinstance(models, Mapping):
        rows.append(("Model state", f"{len(models)} saved model settings (see --json)"))
    _table("Session", rows, console=console)
    if data.get("reason"):
        console.print(Text(f"Reason  {data['reason']}"))


def render_upgrade_result(
    data: Mapping[str, Any], *, as_json: bool = False, stream: Optional[TextIO] = None,
    color: Optional[str] = None, width: Optional[int] = None,
) -> None:
    if as_json:
        emit_json(data, stream=stream)
        return
    data = _redact(data)
    console = make_console(color=color, stream=stream, width=width)
    status = str(data.get("status") or "unknown").replace("_", "-")
    phase = data.get("phase")
    heading = Text("Resource Coordinator Upgrade")
    heading.append("  ")
    heading.append(status.upper(), style=_status_style(status))
    console.print(heading)
    preflight = data.get("preflight") if isinstance(data.get("preflight"), Mapping) else data
    source = preflight.get("source") if isinstance(preflight.get("source"), Mapping) else {}
    runtime = preflight.get("runtime") if isinstance(preflight.get("runtime"), Mapping) else {}
    task = preflight.get("task") if isinstance(preflight.get("task"), Mapping) else {}
    listener = preflight.get("listener") if isinstance(preflight.get("listener"), Mapping) else {}
    _table("Upgrade", [
        ("Phase", phase or "Not started"),
        ("Installed source", source.get("version") or data.get("source_version") or "Unavailable"),
        ("Running runtime", "Legacy installation" if preflight.get("runtime_legacy") else
         runtime.get("version") or data.get("runtime_version") or "Unavailable"),
        ("Startup task", task.get("name") or data.get("startup_task") or "Unverified"),
        ("Listener", f"PID {listener['pid']}" if listener.get("pid") else "Unverified"),
        ("Elevation", "Required" if preflight.get("elevation_required") else "Not required"),
    ], console=console)
    blockers = data.get("blockers") or preflight.get("blockers") or []
    if data.get("blocker"):
        blockers = [*blockers, data["blocker"]]
    if blockers:
        console.print(Text("Blockers", style="bold red"))
        for blocker in blockers:
            console.print(Text(f"  • {blocker}", style="red"))
    elif status in {"planned", "already-current", "verified"}:
        console.print(Text("No blockers reported.", style="green"))
    if status == "blocked":
        console.print(Text("No changes made.", style="yellow"))
    if data.get("receipt"):
        console.print(Text(f"Recovery receipt  {data['receipt']}"))


def render_recovery_result(
    data: Mapping[str, Any], *, stream: Optional[TextIO] = None,
    color: Optional[str] = None, width: Optional[int] = None,
) -> None:
    """Render the actionable recovery summary without dumping nested evidence."""
    data = _redact(data)
    console = make_console(color=color, stream=stream, width=width)
    action = str(data.get("action") or "status")
    status = str(data.get("status") or "unknown").replace("_", "-")
    heading = Text(f"Resource Coordinator Recovery - {action.title()}")
    heading.append("  ")
    heading.append(status.upper(), style=_status_style(status))
    console.print(heading)

    task = data.get("task") if isinstance(data.get("task"), Mapping) else {}
    listener = data.get("listener") if isinstance(data.get("listener"), Mapping) else {}
    attribution = data.get("task_attribution") if isinstance(data.get("task_attribution"), Mapping) else {}
    miner_owned = data.get("miner_owned")
    ownership = "Coordinator" if miner_owned is True else "Unverified" if miner_owned is None else "External"
    _table("Current state", [
        ("Coordinator", data.get("service_state") or "Unavailable"),
        ("Listener", f"Verified — PID {listener['pid']}" if listener.get("pid") else
         "Absent" if data.get("listener_discovery") == "not-found" else "Unverified"),
        ("Startup task", task.get("name") or "Unverified"),
        ("Task attribution", "Verified" if attribution.get("verified") is True else
         "Unverified" if data.get("listener") else "Not evaluated"),
        ("Miner", str(data.get("miner_state") or "Unavailable").replace("_", " ").title()),
        ("Miner ownership", ownership),
        ("Gaming", str(data.get("gaming_state") or "Unavailable").replace("_", " ").title()),
        ("Upgrade receipt", data.get("phase") or data.get("receipt_phase") or
         ("None" if data.get("receipt_present") is False else "Unavailable")),
        ("Failed phase", data.get("failed_at") or "None"),
        ("Inference", f"{data.get('active_inferences', 'Unavailable')} active / "
         f"{data.get('pending_inferences', 'Unavailable')} pending"),
    ], console=console)

    error = data.get("error")
    if error:
        console.print(Text("Last failure", style="bold red"))
        console.print(Text(f"  {error}", style="red"))
    blockers = data.get("blockers") or []
    if blockers:
        console.print(Text("Blockers", style="bold red"))
        for blocker in blockers:
            console.print(Text(f"  - {blocker}", style="red"))
    changes = data.get("changes") or []
    if changes:
        console.print(Text("Planned actions" if status == "planned" else "Actions", style="bold cyan"))
        for change in changes:
            console.print(Text(f"  - {change}"))
    if status in {"planned", "blocked"}:
        console.print(Text("No changes made.", style="yellow"))
    if data.get("audit_record"):
        console.print(Text(f"Audit record  {data['audit_record']}"))

    next_command = None
    if action in {"restore", "resume", "reconcile"} and status == "planned":
        next_command = f"resource-coordinator system recovery {action} -a"
    elif action in {"status", "diagnose"} and data.get("receipt_phase") == "RESTORED_LEGACY":
        next_command = "resource-coordinator system recovery reconcile"
    elif status in {"blocked", "recovery-required"}:
        next_command = "resource-coordinator system recovery diagnose"
    if next_command:
        console.print(Text(f"Next  {next_command}", style="bold cyan"))


def render_health_result(
    data: Mapping[str, Any], *, as_json: bool = False, stream: Optional[TextIO] = None,
    color: Optional[str] = None, width: Optional[int] = None,
) -> None:
    if as_json:
        emit_json(data, stream=stream)
        return
    data = _redact(data)
    console = make_console(color=color, stream=stream, width=width)
    status = str(data.get("status") or "unknown")
    heading = Text("Resource Coordinator Health")
    heading.append("  ")
    heading.append(status.upper(), style=_status_style(status))
    console.print(heading)
    service = data.get("service") if isinstance(data.get("service"), Mapping) else {}
    credential = data.get("credential") if isinstance(data.get("credential"), Mapping) else {}
    gpu = data.get("gpu") if isinstance(data.get("gpu"), Mapping) else {}
    policy = data.get("gpu_policy_verification") if isinstance(data.get("gpu_policy_verification"), Mapping) else {}
    credential_checks = (credential.get("credential_valid"), credential.get("credential_file_readable"),
                         credential.get("acl_restricted"))
    credential_status = ("Verified" if data.get("credential_ready") is True or all(value is True for value in credential_checks)
                         else "Degraded" if any(value is False for value in credential_checks)
                         else "Unavailable")
    runtime = data.get("runtime") if isinstance(data.get("runtime"), Mapping) else service.get("runtime", {})
    runtime_complete = all(runtime.get(key) for key in ("revision", "version", "source_path"))
    runtime_status = ("Current" if data.get("runtime_current") is True else
                      "Mismatch" if runtime_complete else "Legacy / unverified"
                      if runtime or data.get("service_ready") or service.get("service_state") == "ready"
                      else "Unavailable")
    upstream_status = ("Connected" if data.get("upstream_ready") is True else
                       "Not responding" if data.get("upstream_ready") is False else "Not checked")
    _table("Checks", [
        ("Service", service.get("service_state") or ("Ready" if data.get("service_ready") else "Unavailable")),
        ("Credentials", credential_status),
        ("Startup task", "Verified" if data.get("task_ready") is True else
         "Degraded" if data.get("task_ready") is False else "Unavailable"),
        ("Runtime identity", runtime_status),
        ("LM Studio", upstream_status),
        ("GPU power limit", f"{gpu['power_limit_w']:g} W — {policy.get('power_limit_w', 'unverified')}"
         if isinstance(gpu.get("power_limit_w"), (float, int)) else "Unavailable"),
        ("GPU memory clock", f"{gpu['memory_clock_mhz']:g} MHz — {policy.get('memory_clock_mhz', 'unverified')}"
         if isinstance(gpu.get("memory_clock_mhz"), (float, int)) else "Unavailable"),
    ], console=console)
    warnings = data.get("warnings") or []
    blockers = data.get("blockers") or []
    if warnings or blockers:
        console.print(Text("Warnings and blockers", style="bold yellow" if warnings and not blockers else "bold red"))
        for item in [*warnings, *blockers]:
            console.print(Text(f"  • {item}", style="red" if item in blockers else "yellow"))
    if data.get("recommendation"):
        console.print(Text(f"Suggested action  {data['recommendation']}"))


def render_startup_status(
    data: Mapping[str, Any], *, as_json: bool = False, stream: Optional[TextIO] = None,
    color: Optional[str] = None, width: Optional[int] = None,
) -> None:
    if as_json:
        emit_json(data, stream=stream)
        return
    data = _redact(data)
    console = make_console(color=color, stream=stream, width=width)
    console.print(Text("Startup Tasks", style="bold"))
    tasks = data.get("tasks") or []
    if not tasks:
        console.print(Text("No Resource Coordinator startup tasks are registered."))
        return
    table = Table(box=box.SIMPLE, pad_edge=False, expand=True)
    table.add_column("Task", style="bold cyan", overflow="fold")
    table.add_column("Trigger")
    table.add_column("State")
    table.add_column("Privileges")
    for task in tasks:
        if not isinstance(task, Mapping):
            continue
        mode = {"boot": "System boot", "logon": "User logon", "viewer": "User logon"}.get(
            str(task.get("mode") or "").casefold(), str(task.get("mode") or "Unknown").title())
        task_state = str(task.get("state") or "unknown")
        enabled_state = "Enabled" if task.get("enabled") else "Disabled"
        table.add_row(str(task.get("name") or "Unknown"), mode,
                      Text(f"{enabled_state} / {task_state}", style=_status_style(task_state)),
                      str(task.get("run_level") or "Unknown"))
    console.print(table)
    if data.get("authoritative"):
        console.print(Text(f"Authoritative startup  {data['authoritative']}"))


def render_coordinator_status(
    data: Mapping[str, Any], *, as_json: bool = False, stream: Optional[TextIO] = None,
    color: Optional[str] = None, width: Optional[int] = None, gateway_url: Optional[str] = None,
) -> None:
    if as_json:
        emit_json(data, stream=stream)
        return
    data = _redact(data)
    console = make_console(color=color, stream=stream, width=width)
    ready = bool(data.get("is_ready"))
    state = str(data.get("service_state") or "unknown")
    heading = Text("Resource Coordinator")
    heading.append("  ")
    heading.append(state.upper(), style="green" if ready else "yellow")
    console.print(heading)
    gpu = data.get("gpu_inference") or {}
    raw_gateway = gateway_url or data.get("listen_url") or "http://127.0.0.1:1235"
    parsed_gateway = urlsplit(str(raw_gateway))
    listen_url = parsed_gateway.netloc or parsed_gateway.path or str(raw_gateway)
    cooldown = "Unavailable"
    if gpu.get("is_cooling_down"):
        remaining = gpu.get("cooldown_remaining")
        cooldown = f"Active ({remaining}s remaining)" if remaining is not None else "Active"
    elif gpu.get("is_cooling_down") is False:
        cooldown = "Inactive"
    inhibition = gpu.get("inhibition")
    safety = (inhibition.get("reason") or "Active") if isinstance(inhibition, Mapping) else (
        "None" if gpu.get("is_restart_inhibited") is False else "Unavailable")
    rows = [("Gateway", listen_url), ("LM Studio", data.get("upstream_url") or "Unavailable")]
    if gpu.get("active_count") is not None and gpu.get("pending_count") is not None:
        rows.append(("Inference", f"{gpu['active_count']} active / {gpu['pending_count']} pending"))
    else:
        rows.append(("Inference", "Unavailable"))
    rows.extend([("Cooldown", cooldown), ("Safety inhibition", safety)])
    gaming = data.get("gaming") if isinstance(data.get("gaming"), Mapping) else {}
    maintenance = data.get("maintenance") if isinstance(data.get("maintenance"), Mapping) else {}
    inference = data.get("inference") if isinstance(data.get("inference"), Mapping) else {}
    if gaming:
        rows.append(("Gaming", str(gaming.get("state") or "unavailable").replace("_", " ").title()))
    if maintenance:
        rows.append(("Maintenance", str(maintenance.get("state") or "unavailable").replace("_", " ").title()))
    if inference:
        rows.append(("Inference evidence", f"{inference.get('classification', 'unavailable')} / "
                     f"coverage {inference.get('coverage', 'unknown')}"))
    _table("Service", rows, console=console)

    processes = data.get("processes") or {}
    if processes:
        table = Table(title="Managed Processes", box=box.SIMPLE, pad_edge=False)
        table.add_column("Process", style="bold")
        table.add_column("State")
        table.add_column("PID", justify="right")
        table.add_column("Ownership", overflow="fold")
        for name, process in processes.items():
            owner_name = str(process.get("lifecycle_owner") or "").casefold()
            ownership = ("Coordinator" if process.get("is_coordinator_owned") else
                         owner_name.title() if owner_name in {"external", "unmanaged"} else "Unverified")
            process_state = str(process.get("state") or "unknown").replace("_", " ")
            if process_state.casefold() == "stopped" and process.get("was_stopped_by_coordinator"):
                process_state = "Stopped by coordinator"
            table.add_row(
                str(name), Text(process_state, style=_status_style(process_state)), str(process.get("pid") or "—"),
                ownership,
            )
        console.print(table)

    recovery = gpu.get("recovery") if isinstance(gpu.get("recovery"), Mapping) else {}
    hold = recovery.get("inhibition") if isinstance(recovery.get("inhibition"), Mapping) else {}
    details = hold.get("details") if isinstance(hold.get("details"), Mapping) else {}
    extra_holders = details.get("additional_uncertain_holders") or []
    if extra_holders:
        console.print(Text("Additional safety holders", style="bold yellow"))
        for item in extra_holders:
            if isinstance(item, Mapping):
                console.print(Text(f"  {item.get('holder_id', 'unknown')}: {item.get('reason', 'unknown reason')}"))
    unresolved = recovery.get("requests") or []
    if unresolved:
        table = Table(title="Unresolved Inference Requests", box=box.SIMPLE, pad_edge=False, expand=True)
        for name in ("Request", "Phase", "Model", "Elapsed", "Failure", "Recommendation"):
            table.add_column(name, overflow="fold")
        for item in unresolved:
            if not isinstance(item, Mapping):
                continue
            details = item.get("details") if isinstance(item.get("details"), Mapping) else {}
            table.add_row(str(item.get("request_id") or "—"), str(item.get("phase") or "unknown"),
                          str(item.get("model") or "—"), str(details.get("elapsed_seconds") or "—"),
                          str(details.get("failure_kind") or "—"),
                          str(details.get("recovery_recommendation") or "Verify upstream termination"))
        console.print(table)


def render_inference_status(data: Mapping[str, Any], *, as_json: bool = False,
                            stream: Optional[TextIO] = None, color: Optional[str] = None,
                            width: Optional[int] = None) -> None:
    if as_json:
        emit_json(data, stream=stream)
        return
    safe = _redact(data)
    console = make_console(color=color, stream=stream, width=width)
    classification = str(safe.get("classification", "unavailable"))
    heading = Text("Inference Activity  ")
    heading.append(classification.upper(), style=_status_style(classification))
    console.print(heading)
    _table("Coverage", [("Evidence", safe.get("coverage", "unknown")),
                         ("Managed active / pending", f"{safe.get('active_count', '—')} / {safe.get('pending_count', '—')}"),
                         ("Physical GPU idle proven", safe.get("physical_gpu_idle_proven", False)),
                         ("Reason codes", ", ".join(safe.get("reason_codes") or []) or "None")], console=console)
    requests = safe.get("unresolved_requests") or []
    if requests:
        table = Table(title="Unresolved Requests", box=box.SIMPLE, pad_edge=False, expand=True)
        for col in ("Request", "Phase", "Model", "Updated"):
            table.add_column(col, overflow="fold")
        for item in requests:
            table.add_row(str(item.get("request_id", "—")), str(item.get("phase", "unknown")),
                          str(item.get("model") or "—"), str(item.get("updated_at") or "—"))
        console.print(table)


def render_maintenance_status(data: Mapping[str, Any], *, as_json: bool = False,
                              stream: Optional[TextIO] = None, color: Optional[str] = None,
                              width: Optional[int] = None) -> None:
    if as_json:
        emit_json(data, stream=stream)
        return
    safe = _redact(data)
    console = make_console(color=color, stream=stream, width=width)
    state = str(safe.get("state", "unavailable"))
    heading = Text("GPU Maintenance  ")
    heading.append(state.replace("_", " ").upper(), style=_status_style(state))
    console.print(heading)
    _table("Session", [(key.replace("_", " ").title(), safe.get(key, "—")) for key in
                        ("owner", "operation_id", "session_id", "expires_at", "registered_process_count",
                         "recovery_required_reason") if key in safe], console=console)
    restoration = safe.get("restoration")
    if isinstance(restoration, Mapping):
        _table("Restoration Evidence", [(str(key).replace("_", " ").title(), value)
                                          for key, value in restoration.items()], console=console)
    if state == "recovery_required":
        console.print(Text('Verify external process termination and GPU restoration, then use '
                           '"rc maintenance reconcile -f -r \"reason\"".', style="bold yellow"))


def render_maintenance_reconcile_result(data: Mapping[str, Any], *, as_json: bool = False,
                                        stream: Optional[TextIO] = None, color: Optional[str] = None,
                                        width: Optional[int] = None) -> None:
    if as_json:
        emit_json(data, stream=stream)
        return
    safe = _redact(data)
    console = make_console(color=color, stream=stream, width=width)
    result = str(safe.get("status") or safe.get("classification") or "unknown")
    title = Text("Maintenance Reconciliation  ")
    title.append(result.upper(), style=_status_style(result))
    console.print(title)
    disposition = safe.get("disposition") if isinstance(safe.get("disposition"), Mapping) else {}
    rows = [(key.replace("_", " ").title(), value) for key, value in safe.items()
            if key in {"operation_id", "session_id", "reason", "exit_code", "miner_restart_eligible"}]
    rows.extend((key.replace("_", " ").title(), value) for key, value in disposition.items()
                if key in {"operation_id", "session_id", "miner_restart_eligible", "restart_not_before"})
    _table("Disposition", rows, console=console)


def render_recovery_assessment(data: Mapping[str, Any], *, as_json: bool = False,
                               stream: Optional[TextIO] = None, color: Optional[str] = None,
                               width: Optional[int] = None) -> None:
    if as_json:
        emit_json(data, stream=stream)
        return
    safe = _redact(data)
    console = make_console(color=color, stream=stream, width=width)
    classification = str(safe.get("classification", "blocked"))
    heading = Text("Recovery Assessment  ")
    heading.append(classification.upper(), style=_status_style(classification))
    console.print(heading)
    _table("Evidence", [("Mode", safe.get("assessment_mode", "unknown")),
                         ("Coordinator reachable", safe.get("service_reachable", False)),
                         ("Automatic recovery available", safe.get("automatic_recovery_available", False)),
                         ("Reason codes", ", ".join(safe.get("reason_codes") or []) or "None")], console=console)
    for action in safe.get("recommended_actions") or []:
        console.print(Text(f"Next  {action}", style="bold cyan"))
    inference = safe.get("inference")
    if isinstance(inference, Mapping):
        console.print(Text(f"Inference evidence: {inference.get('classification')} / coverage {inference.get('coverage')}"))


def render_telemetry_result(data: Mapping[str, Any], *, as_json: bool = False,
                            stream: Optional[TextIO] = None, color: Optional[str] = None,
                            width: Optional[int] = None) -> None:
    if as_json:
        emit_json(data, stream=stream)
        return
    safe = _redact(data)
    console = make_console(color=color, stream=stream, width=width)
    console.print(Text("Resource Telemetry", style="bold"))
    _table("System", [("CPU utilization", f"{safe.get('cpu_utilization_pct', 'Unavailable')}%"),
                       ("Gateway", "Online" if safe.get("gateway", {}).get("online") else "Offline")], console=console)
    gpus = safe.get("gpus") or []
    if gpus:
        table = Table(title="GPU", box=box.SIMPLE, pad_edge=False, expand=True)
        for column in ("Device", "Utilization %", "VRAM Used / Total MiB", "Power W"):
            table.add_column(column, overflow="fold")
        for gpu in gpus:
            table.add_row(str(gpu.get("device_id", "—")), str(gpu.get("utilization_pct", "—")),
                          f"{gpu.get('memory_used_mb', '—')} / {gpu.get('memory_total_mb', '—')}",
                          str(gpu.get("power_draw_w", "—")))
        console.print(table)
    miner = safe.get("managed_miner")
    if isinstance(miner, Mapping):
        _table("Managed Miner", [("State", miner.get("state", "unknown")),
                                  ("PID", miner.get("pid", "—")),
                                  ("Ownership", "Verified" if miner.get("ownership_verified") else
                                   miner.get("ownership_note", "Unverified"))], console=console)


def render_setup_result(data: Mapping[str, Any], *, as_json: bool = False,
                        stream: Optional[TextIO] = None, color: Optional[str] = None,
                        width: Optional[int] = None) -> None:
    if as_json:
        emit_json(data, stream=stream)
        return
    safe = _redact(data)
    console = make_console(color=color, stream=stream, width=width)
    status = str(safe.get("status") or "unknown")
    console.print(Text(f"Resource Coordinator Setup  {status.upper()}", style=_status_style(status)))
    _table("Result", [(str(key).replace("_", " ").title(), value)
                       for key, value in safe.items()
                       if key in {"mode", "startup_mode", "applied", "authoritative", "receipt"}], console=console)
    blockers = safe.get("blockers") or safe.get("errors") or []
    if blockers:
        console.print(Text("Blockers", style="bold red"))
        for blocker in blockers:
            console.print(Text(f"  {blocker}", style="red"))
    changes = safe.get("changes") or []
    if changes:
        console.print(Text("Changes", style="bold cyan"))
        for change in changes:
            console.print(Text(f"  {change}"))


def render_preflight_result(data: Mapping[str, Any], *, as_json: bool = False,
                            stream: Optional[TextIO] = None, color: Optional[str] = None,
                            width: Optional[int] = None) -> None:
    if as_json:
        emit_json(data, stream=stream)
        return
    safe = _redact(data)
    console = make_console(color=color, stream=stream, width=width)
    status = str(safe.get("status") or ("passed" if safe.get("passed") else "blocked"))
    console.print(Text(f"Preflight  {status.upper()}", style=_status_style(status)))
    for message in safe.get("errors", safe.get("messages", [])) or []:
        console.print(Text(f"  {message}", style="red" if str(message).startswith("ERROR") else "yellow"))


def render_acceptance_result(data: Mapping[str, Any], *, as_json: bool = False,
                             stream: Optional[TextIO] = None, color: Optional[str] = None,
                             width: Optional[int] = None) -> None:
    if as_json:
        emit_json(data, stream=stream)
        return
    safe = _redact(data)
    console = make_console(color=color, stream=stream, width=width)
    summary = safe.get("summary") if isinstance(safe.get("summary"), Mapping) else {}
    status = "passed" if summary.get("all_passed") else "failed"
    console.print(Text(f"Acceptance  {status.upper()}", style=_status_style(status)))
    _table("Trials", [("Passed", summary.get("passed", "—")), ("Failed", summary.get("failed", "—")),
                       ("Mode", safe.get("mode", "unknown"))], console=console)
