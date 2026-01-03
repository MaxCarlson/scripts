#!/usr/bin/env python3
"""
tmux clipboard bridge with environment auto-detection.

Reads the current tmux buffer and fan-outs the data to every clipboard path
we can reach:
  • Local environment clipboard via cross_platform.clipboard_utils (Termux,
    Windows/PowerShell, WSL → Windows, Linux, macOS, etc.)
  • OSC52 escape sequence so upstream terminals (Termux, macOS Terminal, etc.)
    capture the data over SSH/tmux sessions.
  • Optional remote Windows bridge via SSH + PowerShell (`--target` or
    CLIPBOARD_WIN_SSH).

The CLI is exposed as `tmuxcp` (with `tmux2winclip` kept as a legacy alias).
"""

from __future__ import annotations

import argparse
import base64
import os
import subprocess
import sys
from typing import Optional, Sequence

try:
    from cross_platform.clipboard_utils import set_clipboard as _set_clipboard
except Exception:  # pragma: no cover - optional dependency
    _set_clipboard = None  # type: ignore[assignment]


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


def _read_tmux_buffer() -> str:
    return subprocess.check_output(["tmux", "show-buffer", "-p"], text=True)


def _copy_to_local_clipboard(text: str, *, dry_run: bool) -> bool:
    if dry_run:
        print("[DRY-RUN] Skipping local clipboard write (tmux buffer captured).")
        return True

    if _set_clipboard is None:
        _osc52_emit(text)
        print(
            "[WARNING] cross_platform.clipboard_utils is not installed; emitted OSC52 only.",
            file=sys.stderr,
        )
        return False

    try:
        _set_clipboard(text)
        return True
    except Exception as exc:  # pragma: no cover - extremely platform specific
        print(f"[ERROR] Local clipboard update failed: {exc}", file=sys.stderr)
        _osc52_emit(text)
        return False


def _send_to_remote_windows_clipboard(text: str, target: str, verbose: bool, dry_run: bool) -> int:
    if dry_run:
        print(f"[DRY-RUN] Skipping remote clipboard push to {target}.")
        return 0

    payload_b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    ps_script = _powershell_set_clip_script()
    encoded = base64.b64encode(ps_script.encode("utf-16le")).decode("ascii")
    ssh_cmd = ["ssh", target, "pwsh", "-NoProfile", "-EncodedCommand", encoded]
    return _run_pwsh_command(ssh_cmd, payload_b64, verbose)


def tmux_to_windows_clipboard(
    target: Optional[str],
    *,
    verbose: bool = False,
    dry_run: bool = False,
    skip_remote: bool = False,
) -> int:
    """
    Legacy public function kept for backwards compatibility. The new behavior
    mirrors tmuxcp: always attempt a local clipboard update (Termux/Windows/WSL)
    and optionally mirror the buffer to a remote Windows host over SSH.
    """

    try:
        tmux_buf = _read_tmux_buffer()
    except Exception as exc:
        print(f"[ERROR] Unable to read tmux buffer: {exc}", file=sys.stderr)
        return 1

    local_ok = _copy_to_local_clipboard(tmux_buf, dry_run=dry_run)
    if local_ok:
        print("[SUCCESS] tmux buffer copied to local clipboard.")

    remote_rc: Optional[int] = None
    if target and not skip_remote:
        remote_rc = _send_to_remote_windows_clipboard(tmux_buf, target, verbose, dry_run)
        if remote_rc == 0:
            print(f"[SUCCESS] Remote Windows clipboard updated via {target}.")
        else:
            print(
                f"[ERROR] Remote Windows clipboard update failed (rc={remote_rc}).",
                file=sys.stderr,
            )

    # Successful if at least one path worked
    if local_ok or (remote_rc == 0):
        return 0

    print(
        "[ERROR] tmux buffer was not copied to any clipboard target.",
        file=sys.stderr,
    )
    return 1


def cli_main():
    parser = argparse.ArgumentParser(
        description=(
            "Copy the current tmux buffer to every detected clipboard (Termux, Windows, macOS, Linux, OSC52) "
            "and optionally mirror it to a remote Windows host over SSH."
        ),
    )
    parser.add_argument(
        "-t",
        "--target",
        default=os.environ.get("CLIPBOARD_WIN_SSH"),
        help="Optional SSH target for a remote Windows host (user@host). Defaults to CLIPBOARD_WIN_SSH.",
    )
    parser.add_argument(
        "-l",
        "--local-only",
        action="store_true",
        help="Skip remote SSH clipboard updates even if --target / CLIPBOARD_WIN_SSH is provided.",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show detected actions without writing to any clipboard.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show SSH command output for remote clipboard pushes.",
    )
    args = parser.parse_args()
    sys.exit(
        tmux_to_windows_clipboard(
            args.target,
            verbose=args.verbose,
            dry_run=args.dry_run,
            skip_remote=args.local_only,
        )
    )
