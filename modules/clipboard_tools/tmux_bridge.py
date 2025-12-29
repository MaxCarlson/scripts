#!/usr/bin/env python3
"""
tmux -> Windows clipboard bridge.

Reads the current tmux buffer, base64-encodes it, and ships it to a Windows
clipboard. When running on WSL/Windows it calls local PowerShell/clip.exe;
otherwise it uses SSH to reach a Windows host and drive Set-Clipboard.
Also emits OSC52 locally for convenience.
"""

from __future__ import annotations

import argparse
import base64
import os
import shutil
import subprocess
import sys
from typing import Optional, Sequence


def _osc52_emit(text: str) -> None:
    if not sys.stdout.isatty():
        return
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    osc = f"\033]52;c;{encoded}\a"
    if os.environ.get("TMUX"):
        wrapped = f"\033Ptmux;{osc}\033\\"
        try:
            sys.stdout.write(wrapped)
            sys.stdout.flush()
        except Exception:
            pass
    else:
        try:
            sys.stdout.write(osc)
            sys.stdout.flush()
        except Exception:
            pass


def _powershell_set_clip_script() -> str:
    return (
        "$b=[Console]::In.ReadToEnd();"
        "$bytes=[Convert]::FromBase64String($b);"
        "$str=[Text.Encoding]::UTF8.GetString($bytes);"
        "Set-Clipboard -Value $str"
    )


def _is_windows_host() -> bool:
    return os.name == "nt"


def _is_wsl_host() -> bool:
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        with open("/proc/sys/kernel/osrelease", "r", encoding="utf-8") as fh:
            return "microsoft" in fh.read().lower()
    except OSError:
        return False


def _resolve_windows_command(candidates: Sequence[str]) -> Optional[str]:
    for candidate in candidates:
        if os.path.sep in candidate:
            if os.path.exists(candidate):
                return candidate
            continue
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def _run_pwsh_command(command: Sequence[str], payload_b64: str, verbose: bool) -> int:
    try:
        proc = subprocess.run(
            list(command),
            input=payload_b64,
            text=True,
            capture_output=not verbose,
        )
    except Exception as exc:
        print(f"[ERROR] PowerShell command failed: {exc}", file=sys.stderr)
        return 1

    if proc.returncode != 0:
        if not verbose:
            if proc.stdout:
                print(proc.stdout, file=sys.stderr)
            if proc.stderr:
                print(proc.stderr, file=sys.stderr)
        print(f"[ERROR] Set-Clipboard failed (rc={proc.returncode})", file=sys.stderr)
        return proc.returncode

    if verbose:
        if proc.stdout:
            sys.stderr.write(proc.stdout)
        if proc.stderr:
            sys.stderr.write(proc.stderr)
    print("[SUCCESS] tmux buffer sent to Windows clipboard.")
    return 0


def _copy_via_clip_exe(clip_cmd: str, text: str, verbose: bool) -> int:
    try:
        proc = subprocess.run(
            [clip_cmd],
            input=text,
            text=True,
            capture_output=not verbose,
        )
    except Exception as exc:
        print(f"[ERROR] clip.exe invocation failed: {exc}", file=sys.stderr)
        return 1

    if proc.returncode != 0:
        if not verbose:
            if proc.stdout:
                print(proc.stdout, file=sys.stderr)
            if proc.stderr:
                print(proc.stderr, file=sys.stderr)
        print(f"[ERROR] clip.exe failed (rc={proc.returncode})", file=sys.stderr)
        return proc.returncode

    if verbose:
        if proc.stdout:
            sys.stderr.write(proc.stdout)
        if proc.stderr:
            sys.stderr.write(proc.stderr)
    print("[SUCCESS] tmux buffer sent via clip.exe.")
    return 0


def tmux_to_windows_clipboard(target: Optional[str], *, verbose: bool = False) -> int:
    try:
        tmux_buf = subprocess.check_output(["tmux", "show-buffer", "-p"], text=True)
    except Exception as e:
        print(f"[ERROR] Unable to read tmux buffer: {e}", file=sys.stderr)
        return 1

    _osc52_emit(tmux_buf)

    payload_b64 = base64.b64encode(tmux_buf.encode("utf-8")).decode("ascii")
    ps_script = _powershell_set_clip_script()
    encoded = base64.b64encode(ps_script.encode("utf-16le")).decode("ascii")

    if target:
        ssh_cmd = ["ssh", target, "pwsh", "-NoProfile", "-EncodedCommand", encoded]
        return _run_pwsh_command(ssh_cmd, payload_b64, verbose)

    if _is_windows_host() or _is_wsl_host():
        pwsh_path = _resolve_windows_command(
            [
                "pwsh.exe",
                "powershell.exe",
                "/mnt/c/Program Files/PowerShell/7/pwsh.exe",
                "/mnt/c/Program Files/PowerShell/7-preview/pwsh.exe",
                "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
            ]
        )
        if pwsh_path:
            local_cmd = [pwsh_path, "-NoProfile", "-EncodedCommand", encoded]
            return _run_pwsh_command(local_cmd, payload_b64, verbose)

        clip_path = _resolve_windows_command(
            [
                "clip.exe",
                "/mnt/c/Windows/System32/clip.exe",
                r"C:\Windows\System32\clip.exe",
            ]
        )
        if clip_path:
            return _copy_via_clip_exe(clip_path, tmux_buf, verbose)

    print(
        "[ERROR] Windows clipboard target is required. "
        "Set CLIPBOARD_WIN_SSH, pass --target, or run inside WSL/Windows with clip.exe available.",
        file=sys.stderr,
    )
    return 1


def cli_main():
    parser = argparse.ArgumentParser(
        description="Send current tmux buffer to a remote Windows clipboard via SSH + PowerShell.",
    )
    parser.add_argument(
        "-t",
        "--target",
        default=os.environ.get("CLIPBOARD_WIN_SSH"),
        help="SSH target for Windows host (user@host). Defaults to CLIPBOARD_WIN_SSH.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show SSH command output.",
    )
    args = parser.parse_args()
    if not args.target:
        print("[ERROR] Windows SSH target is required (set CLIPBOARD_WIN_SSH or pass -t).", file=sys.stderr)
        sys.exit(1)
    sys.exit(tmux_to_windows_clipboard(args.target, verbose=args.verbose))
