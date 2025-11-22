#!/usr/bin/env python3
"""
tmux -> Windows clipboard bridge.

Reads the current tmux buffer, base64-encodes it, and ships it to a Windows
host over SSH to be set via PowerShell Set-Clipboard (stdin-based, avoids
command-line length limits). Also emits OSC52 locally for convenience.
"""

from __future__ import annotations

import argparse
import base64
import os
import subprocess
import sys
from typing import Optional


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


def tmux_to_windows_clipboard(target: str, *, verbose: bool = False) -> int:
    try:
        tmux_buf = subprocess.check_output(["tmux", "show-buffer", "-p"], text=True)
    except Exception as e:
        print(f"[ERROR] Unable to read tmux buffer: {e}", file=sys.stderr)
        return 1

    _osc52_emit(tmux_buf)

    payload_b64 = base64.b64encode(tmux_buf.encode("utf-8")).decode("ascii")
    ps_script = _powershell_set_clip_script()
    encoded = base64.b64encode(ps_script.encode("utf-16le")).decode("ascii")

    ssh_cmd = ["ssh", target, "pwsh", "-NoProfile", "-EncodedCommand", encoded]
    try:
        proc = subprocess.run(
            ssh_cmd,
            input=payload_b64,
            text=True,
            capture_output=not verbose,
        )
    except Exception as e:
        print(f"[ERROR] SSH/Pwsh failed: {e}", file=sys.stderr)
        return 1

    if proc.returncode != 0:
        if not verbose:
            print(proc.stdout, file=sys.stderr)
            print(proc.stderr, file=sys.stderr)
        print(f"[ERROR] Remote Set-Clipboard failed (rc={proc.returncode})", file=sys.stderr)
        return proc.returncode

    if verbose and (proc.stdout or proc.stderr):
        sys.stderr.write(proc.stdout or "")
        sys.stderr.write(proc.stderr or "")
    print("[SUCCESS] tmux buffer sent to remote Windows clipboard.")
    return 0


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
