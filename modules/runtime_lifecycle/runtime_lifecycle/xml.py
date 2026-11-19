"""Canonical Task Scheduler XML serialization and semantic inspection."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import BootTrigger, CalendarTrigger, LogonTrigger, RepeatingIntervalTrigger, TaskSpec, resolve_account_sid


TASK_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
NS = {"t": TASK_NS}
ET.register_namespace("", TASK_NS)
XML_DECL_ENCODING_RE = re.compile(r'^(<\?xml\b[^>]*?)\s+encoding=["\'][^"\']+["\']([^>]*\?>)', re.IGNORECASE)
SETTING_DEFAULTS = {
    "MultipleInstancesPolicy": "IgnoreNew",
    "DisallowStartIfOnBatteries": "true",
    "StopIfGoingOnBatteries": "true",
    "AllowHardTerminate": "true",
    "StartWhenAvailable": "false",
    "WakeToRun": "false",
    "Hidden": "false",
    "ExecutionTimeLimit": "PT72H",
}
MARKER_RE = re.compile(
    r"managed-by=runtime_lifecycle;\s*owner=([^;]+);\s*name=([^;]+);\s*schema=(\d+);\s*spec_hash=([0-9a-f]{64})",
    re.IGNORECASE,
)
WEEKDAY_TAGS = {
    "Sunday": "Sunday",
    "Monday": "Monday",
    "Tuesday": "Tuesday",
    "Wednesday": "Wednesday",
    "Thursday": "Thursday",
    "Friday": "Friday",
    "Saturday": "Saturday",
}
MONTH_TAGS = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December",
}


def _tag(name: str) -> str:
    return f"{{{TASK_NS}}}{name}"


def _add(parent: ET.Element, name: str, text: object | None = None, **attributes: str) -> ET.Element:
    child = ET.SubElement(parent, _tag(name), attributes)
    if text is not None:
        child.text = str(text)
    return child


def spec_hash(spec: TaskSpec) -> str:
    """Hash normalized desired state, excluding human description text."""
    payload = json.dumps(spec.canonical_data(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _task_description(spec: TaskSpec) -> str:
    marker = (
        f"managed-by=runtime_lifecycle; owner={spec.owner}; name={spec.name}; schema=1; spec_hash={spec_hash(spec)}"
    )
    return f"{marker}; {spec.description}" if spec.description else marker


def _local_path(path: Path) -> str:
    return str(path).replace("/", "\\")


def _start_boundary(day: str, start_time: str) -> str:
    normalized = start_time if len(start_time.split(":")) == 3 else f"{start_time}:00"
    return f"{day}T{normalized}"


def _render_trigger(triggers: ET.Element, trigger: object, principal_sid: str) -> None:
    if isinstance(trigger, LogonTrigger):
        node = _add(triggers, "LogonTrigger")
        _add(node, "Enabled", "true")
        if trigger.user_id or principal_sid:
            _add(node, "UserId", trigger.user_id or principal_sid)
        if trigger.delay:
            _add(node, "Delay", trigger.delay)
        return

    if isinstance(trigger, BootTrigger):
        node = _add(triggers, "BootTrigger")
        _add(node, "Enabled", "true")
        if trigger.delay:
            _add(node, "Delay", trigger.delay)
        return

    if isinstance(trigger, RepeatingIntervalTrigger):
        node = _add(triggers, "TimeTrigger")
        _add(node, "Enabled", "true")
        _add(node, "StartBoundary", trigger.start_boundary)
        repetition = _add(node, "Repetition")
        _add(repetition, "Interval", trigger.interval)
        if trigger.duration:
            _add(repetition, "Duration", trigger.duration)
        _add(repetition, "StopAtDurationEnd", "false")
        return

    if isinstance(trigger, CalendarTrigger):
        boundary = _start_boundary(trigger.start_date, trigger.start_time)
        if trigger.schedule == "once":
            node = _add(triggers, "TimeTrigger")
            _add(node, "Enabled", "true")
            _add(node, "StartBoundary", boundary)
            return
        node = _add(triggers, "CalendarTrigger")
        _add(node, "Enabled", "true")
        _add(node, "StartBoundary", boundary)
        if trigger.schedule == "daily":
            schedule = _add(node, "ScheduleByDay")
            _add(schedule, "DaysInterval", trigger.interval)
        elif trigger.schedule == "weekly":
            schedule = _add(node, "ScheduleByWeek")
            _add(schedule, "WeeksInterval", trigger.interval)
            weekdays = _add(schedule, "DaysOfWeek")
            for day in trigger.days_of_week:
                _add(weekdays, WEEKDAY_TAGS[day])
        else:
            schedule = _add(node, "ScheduleByMonth")
            days = _add(schedule, "DaysOfMonth")
            for day in trigger.days_of_month:
                _add(days, "Day", day)
            months = _add(schedule, "Months")
            selected_months = trigger.months or tuple(MONTH_TAGS)
            for month in selected_months:
                _add(months, MONTH_TAGS[month])
        return

    raise TypeError(f"Unsupported trigger type: {type(trigger).__name__}")


def render_task_xml(spec: TaskSpec) -> bytes:
    """Render a Task Scheduler definition as UTF-16LE XML with BOM."""
    root = ET.Element(_tag("Task"), {"version": "1.3"})
    registration = _add(root, "RegistrationInfo")
    _add(registration, "Description", _task_description(spec))

    principals = _add(root, "Principals")
    principal = _add(principals, "Principal", id="Author")
    _add(principal, "UserId", spec.principal_sid)
    _add(principal, "LogonType", spec.principal.task_logon_type)
    _add(principal, "RunLevel", spec.principal.task_run_level)

    triggers = _add(root, "Triggers")
    for trigger in spec.triggers:
        _render_trigger(triggers, trigger, spec.principal_sid)

    settings = _add(root, "Settings")
    _add(settings, "MultipleInstancesPolicy", spec.multiple_instances)
    _add(settings, "DisallowStartIfOnBatteries", "false" if spec.allow_on_battery else "true")
    _add(settings, "StopIfGoingOnBatteries", "false" if spec.allow_on_battery else "true")
    _add(settings, "AllowHardTerminate", "true")
    _add(settings, "StartWhenAvailable", str(spec.start_when_available).lower())
    _add(settings, "WakeToRun", str(spec.wake_to_run).lower())
    _add(settings, "Enabled", "true")
    _add(settings, "Hidden", str(spec.hidden).lower())
    _add(settings, "ExecutionTimeLimit", spec.execution_time_limit)
    if spec.restart_count:
        restart = _add(settings, "RestartOnFailure")
        _add(restart, "Interval", spec.restart_interval)
        _add(restart, "Count", spec.restart_count)

    actions = _add(root, "Actions", Context="Author")
    action = _add(actions, "Exec")
    _add(action, "Command", _local_path(spec.executable))
    if spec.args:
        _add(action, "Arguments", subprocess.list2cmdline(list(spec.args)))
    _add(action, "WorkingDirectory", _local_path(spec.working_dir))

    body = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    document = f'<?xml version="1.0" encoding="UTF-16"?>\n{body}'
    return b"\xff\xfe" + document.encode("utf-16-le")


def _text(root: ET.Element, path: str, default: str | None = None) -> str | None:
    value = root.findtext(path, namespaces=NS)
    return value if value is not None else default


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().casefold() in {"true", "1"}


def _trigger_semantics(node: ET.Element) -> dict[str, Any]:
    kind = node.tag.rsplit("}", 1)[-1]
    data: dict[str, Any] = {"type": kind}
    for name in ("StartBoundary", "EndBoundary", "Delay", "UserId"):
        value = _text(node, f"t:{name}")
        if value is not None:
            data[name[0].lower() + name[1:]] = value
    repetition = node.find("t:Repetition", NS)
    if repetition is not None:
        rep_data = {
            key: _text(repetition, f"t:{key}")
            for key in ("Interval", "Duration", "StopAtDurationEnd")
            if _text(repetition, f"t:{key}") is not None
        }
        rep_data.setdefault("StopAtDurationEnd", "false")
        data["repetition"] = rep_data
    schedule_node = next((child for child in node if child.tag.rsplit("}", 1)[-1].startswith("ScheduleBy")), None)
    if schedule_node is not None:
        data["schedule"] = ET.tostring(schedule_node, encoding="unicode")
    return data


@dataclass(frozen=True, slots=True)
class ParsedTask:
    """Normalized semantic fields extracted from Task Scheduler XML."""

    owner: str | None
    name: str | None
    schema: int | None
    spec_hash: str | None
    description: str | None
    principal_sid: str | None
    logon_type: str | None
    run_level: str | None
    executable: str | None
    arguments: str | None
    working_dir: str | None
    triggers: tuple[dict[str, Any], ...]
    settings: dict[str, Any]
    enabled: bool
    logged_off_capable: bool

    def semantic_data(self) -> dict[str, Any]:
        return {
            "principal_sid": self.principal_sid,
            "logon_type": self.logon_type,
            "run_level": self.run_level,
            "executable": self.executable,
            "arguments": self.arguments,
            "working_dir": self.working_dir,
            "triggers": list(self.triggers),
            "settings": self.settings,
            "enabled": self.enabled,
        }


def _decode_xml_text(xml_data: str | bytes) -> str:
    if isinstance(xml_data, bytes):
        if xml_data.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = xml_data.decode("utf-16")
        else:
            try:
                text = xml_data.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = xml_data.decode("mbcs" if os.name == "nt" else "utf-8", errors="replace")
    else:
        text = xml_data
    text = text.lstrip("\ufeff")
    # schtasks /Query /XML emits UTF-8/MBCS bytes while keeping encoding="UTF-16" in the declaration.
    return XML_DECL_ENCODING_RE.sub(r"\1\2", text, count=1)


def parse_task_xml(xml_data: str | bytes) -> ParsedTask:
    """Parse Task Scheduler XML exported as UTF-8 or UTF-16."""
    root = ET.fromstring(_decode_xml_text(xml_data))
    description = _text(root, "t:RegistrationInfo/t:Description")
    marker = MARKER_RE.search(description or "")
    command = _text(root, "t:Actions/t:Exec/t:Command")
    arguments = _text(root, "t:Actions/t:Exec/t:Arguments", "")
    working_dir = _text(root, "t:Actions/t:Exec/t:WorkingDirectory")
    settings_node = root.find("t:Settings", NS)
    setting_names = tuple(SETTING_DEFAULTS)
    settings: dict[str, Any] = {}
    if settings_node is not None:
        for name in setting_names:
            value = _text(settings_node, f"t:{name}")
            settings[name] = value if value is not None else SETTING_DEFAULTS[name]
        restart = settings_node.find("t:RestartOnFailure", NS)
        if restart is not None:
            settings["RestartOnFailure"] = {key: _text(restart, f"t:{key}") for key in ("Interval", "Count")}
    principal_node = root.find("t:Principals/t:Principal", NS)
    principal_sid = _text(principal_node, "t:UserId") if principal_node is not None else None
    logon_type = _text(principal_node, "t:LogonType", "InteractiveToken") if principal_node is not None else None
    run_level = _text(principal_node, "t:RunLevel", "LeastPrivilege") if principal_node is not None else None
    triggers_node = root.find("t:Triggers", NS)
    triggers = tuple(_trigger_semantics(child) for child in triggers_node) if triggers_node is not None else ()
    return ParsedTask(
        owner=marker.group(1) if marker else None,
        name=marker.group(2) if marker else None,
        schema=int(marker.group(3)) if marker else None,
        spec_hash=marker.group(4).lower() if marker else None,
        description=description,
        principal_sid=principal_sid,
        logon_type=logon_type,
        run_level=run_level,
        executable=command.replace("/", "\\") if command else None,
        arguments=arguments,
        working_dir=working_dir.replace("/", "\\") if working_dir else None,
        triggers=triggers,
        settings=settings,
        enabled=_bool(_text(root, "t:Settings/t:Enabled"), True),
        logged_off_capable=logon_type != "InteractiveToken",
    )


def _normalize_trigger(trigger: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(trigger)
    user_id = normalized.get("userId")
    if isinstance(user_id, str):
        resolved = resolve_account_sid(user_id)
        if resolved is not None:
            normalized["userId"] = resolved
    return normalized


def semantic_diff(spec: TaskSpec, parsed: ParsedTask) -> dict[str, dict[str, Any]]:
    """Return field-level desired/live differences independent of XML formatting."""
    desired = {
        "principal_sid": spec.principal_sid,
        "logon_type": spec.principal.task_logon_type,
        "run_level": spec.principal.task_run_level,
        "executable": _local_path(spec.executable),
        "arguments": subprocess.list2cmdline(list(spec.args)) if spec.args else "",
        "working_dir": _local_path(spec.working_dir),
        "triggers": [_trigger_expected(trigger, spec.principal_sid) for trigger in spec.triggers],
        "settings": {
            "MultipleInstancesPolicy": spec.multiple_instances,
            "DisallowStartIfOnBatteries": str(not spec.allow_on_battery).lower(),
            "StopIfGoingOnBatteries": str(not spec.allow_on_battery).lower(),
            "AllowHardTerminate": "true",
            "StartWhenAvailable": str(spec.start_when_available).lower(),
            "WakeToRun": str(spec.wake_to_run).lower(),
            "Hidden": str(spec.hidden).lower(),
            "ExecutionTimeLimit": spec.execution_time_limit,
        },
        "enabled": True,
    }
    if spec.restart_count:
        desired["settings"]["RestartOnFailure"] = {
            "Interval": spec.restart_interval,
            "Count": str(spec.restart_count),
        }
    actual = parsed.semantic_data()
    differences: dict[str, dict[str, Any]] = {}
    for key, wanted in desired.items():
        found = actual.get(key)
        if key == "triggers":
            wanted = sorted(
                (_normalize_trigger(item) for item in wanted), key=lambda item: json.dumps(item, sort_keys=True)
            )
            found = sorted(
                (_normalize_trigger(item) for item in (found or [])), key=lambda item: json.dumps(item, sort_keys=True)
            )
        if wanted != found:
            differences[key] = {"desired": wanted, "actual": found}
    return differences


def _trigger_expected(trigger: object, principal_sid: str) -> dict[str, Any]:
    """Build a semantic trigger dictionary matching parser output."""
    if isinstance(trigger, LogonTrigger):
        result: dict[str, Any] = {"type": "LogonTrigger", "userId": trigger.user_id or principal_sid}
        if trigger.delay:
            result["delay"] = trigger.delay
        return result
    if isinstance(trigger, BootTrigger):
        result = {"type": "BootTrigger"}
        if trigger.delay:
            result["delay"] = trigger.delay
        return result
    if isinstance(trigger, RepeatingIntervalTrigger):
        repetition = {"Interval": trigger.interval, "StopAtDurationEnd": "false"}
        if trigger.duration:
            repetition["Duration"] = trigger.duration
        return {"type": "TimeTrigger", "startBoundary": trigger.start_boundary, "repetition": repetition}
    if isinstance(trigger, CalendarTrigger):
        boundary = _start_boundary(trigger.start_date, trigger.start_time)
        if trigger.schedule == "once":
            return {"type": "TimeTrigger", "startBoundary": boundary}
        return {
            "type": "CalendarTrigger",
            "startBoundary": boundary,
            "schedule": _calendar_schedule_xml(trigger),
        }
    raise TypeError(f"Unsupported trigger type: {type(trigger).__name__}")


def _calendar_schedule_xml(trigger: CalendarTrigger) -> str:
    parent = ET.Element(_tag("Schedule"))
    _render_trigger(parent, trigger, "")
    schedule_node = next(child for child in parent[0] if child.tag.rsplit("}", 1)[-1].startswith("ScheduleBy"))
    return ET.tostring(schedule_node, encoding="unicode")
