"""Generate and deploy the small AutoHotkey dispatcher."""

from __future__ import annotations

import hashlib
import subprocess
import time
from pathlib import Path
from typing import Any

from snips.config import atomic_write, parse_hotkey, template_payload, validate_config


def ahk_string(value: str) -> str:
    """Quote trusted paths for AHK; snippet bodies are always external UTF-8 files."""
    return '"' + value.replace("`", "``").replace('"', '`"').replace("\r", "`r").replace("\n", "`n") + '"'


def generate_script(config: dict[str, Any], data_dir: Path, status_path: Path) -> tuple[str, str, dict[str, str]]:
    config = validate_config(config)
    build_hash = hashlib.sha256(repr(config).encode("utf-8")).hexdigest()[:16]
    rows: list[str] = []
    for item in config["bindings"]:
        if not item["enabled"]:
            continue
        _, hotkey = parse_hotkey(item["hotkey"])
        if item["kind"] == "template":
            _, cursor_chars = template_payload(item["content"])
            rows.append(
                f"Hotkey({ahk_string(hotkey)}, (*) => InsertTemplate({ahk_string(item['id'])}, {cursor_chars}))"
            )
        elif item["kind"] == "clipboard-fence":
            rows.append(f"Hotkey({ahk_string(hotkey)}, ClipboardFence)")
        elif item["kind"] == "selection-fence":
            rows.append(f"Hotkey({ahk_string(hotkey)}, SelectionFence)")
    registrations = "\n".join(rows)
    source = f"""#Requires AutoHotkey v2.0
#SingleInstance Force
 Persistent()

global DATA_DIR := {ahk_string(str(data_dir))}
global STATUS_PATH := {ahk_string(str(status_path))}
global BUILD_ID := {ahk_string(build_hash)}
global PROCESS_ID := DllCall("GetCurrentProcessId", "UInt")
global RESTORE_DELAY := {int(config["settings"].get("clipboard_restore_delay_ms", 250))}
global VALIDATE_ONLY := A_Args.Length > 0 && A_Args[1] = "/validate"

try {{
{registrations}
    WriteStatus("running")
    if VALIDATE_ONLY
        ExitApp(0)
}} catch Error as err {{
    WriteStatus("error", err.Message)
    ExitApp(2)
}}

OnExit((*) => WriteStatus("stopped"))
A_TrayMenu.Add("Reload snippets", (*) => Reload())
A_TrayMenu.Add("Exit snippets", (*) => ExitApp())

InsertTemplate(bindingId, cursorChars) {{
    global DATA_DIR
    try {{
        body := FileRead(DATA_DIR "\\" bindingId ".txt", "UTF-8")
        PasteText(body)
        if cursorChars > 0
            Send "{{Left " cursorChars "}}"
    }} catch Error as err {{
        ToolTip("snips: template insertion failed")
        SetTimer(() => ToolTip(), -1200)
    }}
}}

ClipboardFence(*) {{
    try {{
        saved := ClipboardAll()
        text := A_Clipboard
        if text = "" {{
            ToolTip("snips: clipboard has no text")
            SetTimer(() => ToolTip(), -1200)
            return
        }}
        PasteWithSavedClipboard(MarkdownFence(text))
    }} catch Error as err {{
        ToolTip("snips: clipboard unavailable")
        SetTimer(() => ToolTip(), -1200)
    }} finally {{
        if IsSet(saved) && !RestoreClipboard(saved)
            ToolTip("snips: could not restore clipboard")
    }}
}}

SelectionFence(*) {{
    try {{
        saved := ClipboardAll()
        sequence := DllCall("GetClipboardSequenceNumber", "UInt")
        Send "^c"
        if !ClipWait(0.8) || DllCall("GetClipboardSequenceNumber", "UInt") = sequence {{
            ToolTip("snips: could not copy selected text")
            SetTimer(() => ToolTip(), -1200)
            return
        }}
        text := A_Clipboard
        PasteWithSavedClipboard(MarkdownFence(text))
    }} catch Error as err {{
        ToolTip("snips: selection copy failed")
        SetTimer(() => ToolTip(), -1200)
    }} finally {{
        if IsSet(saved) && !RestoreClipboard(saved)
            ToolTip("snips: could not restore clipboard")
    }}
}}

PasteText(text) {{
    saved := ClipboardAll()
    try {{
        PasteWithSavedClipboard(text)
    }} finally {{
        if !RestoreClipboard(saved)
            ToolTip("snips: could not restore clipboard")
    }}
}}

PasteWithSavedClipboard(text) {{
    global RESTORE_DELAY
    A_Clipboard := text
    if !ClipWait(1)
        throw Error("clipboard write timed out")
    Send "^v"
    Sleep(RESTORE_DELAY)
}}

RestoreClipboard(saved) {{
    try {{
        A_Clipboard := saved
        return true
    }} catch Error {{
        return false
    }}
}}

MarkdownFence(text) {{
    longest := 0
    for match in RegExMatchAll(text, Chr(96) "+", &matches) {{
        if StrLen(match[0]) > longest
            longest := StrLen(match[0])
    }}
    fence := StrRepeat(Chr(96), Max(3, longest + 1))
    return fence "`n" text "`n" fence
}}

RegExMatchAll(text, pattern, &matches) {{
    matches := []
    pos := 1
    while pos := RegExMatch(text, pattern, &match, pos) {{
        matches.Push(match)
        pos += StrLen(match[0])
    }}
    return matches
}}

StrRepeat(value, count) {{
    output := ""
    Loop count
        output .= value
    return output
}}

WriteStatus(state, detail := "") {{
    global STATUS_PATH, BUILD_ID, PROCESS_ID
    try {{
        if FileExist(STATUS_PATH)
            FileDelete(STATUS_PATH)
        detail := StrReplace(detail, "|", "/")
        line := state "|" PROCESS_ID "|" BUILD_ID
        if detail != ""
            line .= "|" detail
        FileAppend(line, STATUS_PATH, "UTF-8-RAW")
    }}
}}
"""
    data: dict[str, str] = {}
    for item in config["bindings"]:
        if item["kind"] == "template":
            data[f"{item['id']}.txt"] = item["content"].replace("{{cursor}}", "")
    return source, build_hash, data


def deploy(config: dict[str, Any], runtime_dir: Path) -> tuple[Path, str]:
    data_dir = runtime_dir / "data"
    status_path = runtime_dir / "status.txt"
    source, build_hash, data = generate_script(config, data_dir, status_path)
    data_dir.mkdir(parents=True, exist_ok=True)
    desired = {data_dir / name: body for name, body in data.items()}
    desired[runtime_dir / "snips.ahk"] = source
    for path, content in desired.items():
        atomic_write(path, content)
    for old in data_dir.glob("*.txt"):
        if old not in desired:
            old.unlink()
    return runtime_dir / "snips.ahk", build_hash


def runtime_status(runtime_dir: Path) -> dict[str, Any]:
    status_path = runtime_dir / "status.txt"
    try:
        value = status_path.read_text(encoding="utf-8").strip().split("|", 3)
    except OSError:
        return {"running": False, "state": "stopped", "pid": None, "build_id": None}
    state = value[0] if value else "unknown"
    pid: int | None = None
    if len(value) > 1:
        try:
            pid = int(value[1])
        except ValueError:
            pass
    running = False
    if state == "running" and pid:
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=4
            )
            running = result.returncode == 0 and str(pid) in result.stdout
        except (OSError, subprocess.TimeoutExpired):
            pass
    return {
        "running": running,
        "state": state,
        "pid": pid,
        "build_id": value[2] if len(value) > 2 else None,
        "detail": value[3] if len(value) > 3 else None,
    }


def start_runtime(
    executable: Path, script: Path, runtime_dir: Path, expected_build: str, timeout: float = 5.0
) -> tuple[bool, str]:
    try:
        process = subprocess.Popen(
            [str(executable), str(script)], cwd=str(runtime_dir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except OSError as exc:
        return False, f"Could not start AutoHotkey: {exc}"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = runtime_status(runtime_dir)
        if status["build_id"] == expected_build and status["state"] == "error":
            return False, f"AutoHotkey failed during startup: {status['detail'] or 'hotkey registration error'}"
        if status["running"] and status["build_id"] == expected_build:
            return True, f"AutoHotkey is running (PID {status['pid']})"
        code = process.poll()
        if code is not None:
            return False, f"AutoHotkey exited during startup with code {code}"
        time.sleep(0.1)
    return False, "AutoHotkey did not confirm startup before the timeout"
