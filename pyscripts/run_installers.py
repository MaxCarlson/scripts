#!/usr/bin/env python3
"""
run_installers.py

Detects Inno Setup vs NSIS installers, writes a fresh log file each run,
streams all log lines with colorized output, prints install-dir size every
EXIT_DELAY seconds, and auto-exits when both the installer process has ended
and no new log or filesystem activity has occurred for a configurable delay.

Requires: rich (for styling output)
"""
import argparse
import subprocess
import sys
import shlex
import time
import os
import re
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.prompt import Confirm
from rich.text import Text

LOG_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.?\d*)\s*(?P<msg>.*)"
)

def print_colored(line: str, console: Console):
    m = LOG_RE.match(line)
    if m:
        t = Text()
        t.append(m.group("ts"), style="dim")
        t.append("  ")
        t.append(m.group("msg"), style="white")
        console.print(t)
    else:
        console.print(line, style="white")

def detect_setup_type(path: str) -> Optional[str]:
    sigs = {
        "inno": b"Inno Setup",
        "nsis": b"Nullsoft Install System",
    }
    try:
        data = Path(path).read_bytes()[:200_000]
        for t, sig in sigs.items():
            if sig in data:
                return t
    except:
        pass
    return None

def total_size(path: Optional[Path]) -> int:
    if not path or not path.exists():
        return 0
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except:
                pass
    return total

def main():
    console = Console()
    parser = argparse.ArgumentParser(description="Auto-installer for EXE setups")
    parser.add_argument("-i", "--installer", required=True, help="Path to setup.exe")
    parser.add_argument("-l", "--list-options", action="store_true",
                        help="List supported installer flags and exit")
    parser.add_argument("-t", "--target",
                        help="Installation directory (not required with -l)")
    parser.add_argument("-n", "--non-interactive", action="store_true",
                        help="Run without prompts")
    parser.add_argument("-u", "--unattended", action="store_true",
                        help="Silent, no popups, no restart, skip prompt")
    parser.add_argument("-g", "--gui", action="store_true",
                        help="Use GUI-progress (/SILENT) instead of fully silent")
    parser.add_argument("-s", "--silent", action="store_true",
                        help="Silent install (/VERYSILENT or /S)")
    parser.add_argument("-m", "--no-msg", action="store_true", dest="no_msg",
                        help="Suppress pop-ups (/SUPPRESSMSGBOXES)")
    parser.add_argument("-r", "--no-restart", action="store_true", dest="no_restart",
                        help="Prevent auto-restart (/NORESTART)")
    parser.add_argument("-p", "--skip-prompt", action="store_true", dest="skip_prompt",
                        help="Skip initial prompt (/SP-)")
    parser.add_argument("-x", "--extra",
                        help="Additional custom installer flags (space-separated)")
    parser.add_argument("-d", "--exit-delay", type=int, default=10,
                        help="Seconds of inactivity before auto-exit")
    parser.add_argument("-f", "--force", action="store_true",
                        help="Skip confirmation in interactive mode")
    args = parser.parse_args()

    installer = Path(args.installer).resolve()
    if not installer.exists():
        console.print(f"[red]Error:[/red] Installer not found: {installer}")
        sys.exit(1)

    stype = detect_setup_type(str(installer)) or "inno"

    # List flags and exit
    if args.list_options:
        console.print(f"Detected installer type: [bold]{stype.upper()}[/bold]\n")
        if stype == "inno":
            opts = {
                "silent": "/VERYSILENT", "gui": "/SILENT",
                "no_msg": "/SUPPRESSMSGBOXES", "no_restart": "/NORESTART",
                "skip_prompt": "/SP-", "dir": "/DIR",
            }
        else:
            opts = {"silent": "/S", "gui": "/S", "dir": "/D"}
        table = Table(title="Available Installer Options")
        table.add_column("Key", style="cyan")
        table.add_column("Flag", style="green")
        table.add_column("Description")
        descs = {
            "silent": "No UI at all",
            "gui": "Show progress UI",
            "no_msg": "Hide pop-ups",
            "no_restart": "Prevent auto-restart",
            "skip_prompt": "Skip initial prompt",
            "dir": "Install folder (syntax: DIR=path)",
        }
        for k, v in opts.items():
            table.add_row(k, v, descs.get(k, ""))
        console.print(table)
        sys.exit(0)

    # Require target
    if not args.target:
        console.print("[red]Error:[/red] --target required unless listing flags")
        sys.exit(1)
    target = Path(args.target).resolve()

    # Fresh log filename
    base = installer.with_suffix("")
    idx = 1
    while True:
        suffix = "" if idx == 1 else f"_{idx}"
        cand = base.with_name(base.name + suffix + ".log")
        if not cand.exists():
            log_path = cand
            break
        idx += 1

    # Unattended presets
    if args.unattended:
        args.non_interactive = True
        args.force = True
        args.silent = True
        args.no_msg = True
        args.no_restart = True
        args.skip_prompt = True

    console.print(f"Detected installer type: [bold]{stype.upper()}[/bold]")

    # Flag definitions
    if stype == "inno":
        fd = {
            "silent": "/VERYSILENT", "gui": "/SILENT",
            "no_msg": "/SUPPRESSMSGBOXES", "no_restart": "/NORESTART",
            "skip_prompt": "/SP-", "dir": "/DIR",
        }
    else:
        fd = {"silent": "/S", "gui": "/S", "dir": "/D"}

    # Interactive confirmations
    if not args.non_interactive:
        if not args.gui:
            args.silent = Confirm.ask("Enable silent install?", default=True)
        if stype == "inno" and args.silent:
            args.no_msg = Confirm.ask("Hide pop-ups?", default=True)
            args.no_restart = Confirm.ask("Prevent auto-restart?", default=True)
            args.skip_prompt = Confirm.ask("Skip initial prompt?", default=True)

    # Build command
    cmd_flags = [f"/LOG={log_path}"]
    cmd_flags.append(fd["gui"] if args.gui else fd["silent"])
    if stype == "inno":
        if args.no_msg:      cmd_flags.append(fd["no_msg"])
        if args.no_restart:  cmd_flags.append(fd["no_restart"])
        if args.skip_prompt: cmd_flags.append(fd["skip_prompt"])
    cmd_flags.append(f"{fd['dir']}={target}")
    if args.extra:
        cmd_flags.extend(shlex.split(args.extra))

    cmd = [str(installer)] + cmd_flags
    console.print(f"\n[bold magenta]Running:[/bold magenta] [magenta]{' '.join(cmd)}[/magenta]\n")

    proc = subprocess.Popen(cmd, cwd=installer.parent)

    # Wait for log
    start = time.time()
    log_file = None
    while time.time() - start < 5:
        if log_path.exists():
            log_file = open(log_path, "r", errors="ignore")
            break
        time.sleep(0.2)

    last_log = time.time()
    last_fs = time.time()
    last_report = time.time()
    delay = args.exit_delay

    # Tail & monitor
    while True:
        now = time.time()

        # Stream log lines
        if log_file:
            line = log_file.readline()
            while line:
                last_log = now
                print_colored(line.rstrip(), console)
                line = log_file.readline()

        # Detect FS activity
        size = total_size(target)
        if size and size != getattr(main, "_last_size", None):
            main._last_size = size
            last_fs = now

        # Periodic dir-size report
        if now - last_report >= delay:
            console.print(f"[cyan]Install dir size: {size/1e9:.2f} GB[/cyan]")
            last_report = now

        # Exit when installer ended and idle
        if proc.poll() is not None and now - last_log >= delay and now - last_fs >= delay:
            break

        time.sleep(0.2)

    # Final flush
    if log_file:
        rem = log_file.read()
        if rem:
            print(rem.rstrip())
        log_file.close()

    ret = proc.wait()
    if ret == 0:
        console.print("[green]✓ Installation completed successfully[/green]")
    else:
        console.print(f"[red]✗ Installation failed (exit code {ret})[/red]")

if __name__ == "__main__":
    main()
