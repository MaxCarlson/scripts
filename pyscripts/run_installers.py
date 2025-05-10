#!/usr/bin/env python3
"""
run_installers.py

Detects Inno Setup vs NSIS installers, always logs and streams installation
progress in real time, prints install-directory size every EXIT_DELAY seconds,
and supports unattended SSH-friendly installs with fresh log files each run.

Requires: rich (for interactive prompts), otherwise standard library.
"""
import argparse
import subprocess
import sys
import shlex
import time
import os
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt, Confirm

def detect_setup_type(path: str) -> Optional[str]:
    signatures = {
        'inno': b'Inno Setup',
        'nsis': b'Nullsoft Install System',
    }
    try:
        data = Path(path).read_bytes()[:200_000]
        for t, sig in signatures.items():
            if sig in data:
                return t
    except Exception:
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
            except Exception:
                pass
    return total

def main():
    console = Console()
    parser = argparse.ArgumentParser(
        description="Auto-installer for EXE setups (FitGirl, Inno, NSIS)"
    )
    parser.add_argument('-i','--installer', required=True,
                        help='Path to your setup.exe')
    parser.add_argument('-l','--list-options', action='store_true',
                        help='List supported installer flags and exit')
    parser.add_argument('-t','--target',
                        help='Installation directory (not required with -l)')
    parser.add_argument('-n','--non-interactive', action='store_true',
                        help='Run without prompts')
    parser.add_argument('-u','--unattended', action='store_true',
                        help='Shortcut: silent, no popups, no restart, skip prompt, non-interactive, force')
    parser.add_argument('-g','--gui', action='store_true',
                        help='Use GUI-progress (/SILENT) instead of fully silent')
    parser.add_argument('-s','--silent', action='store_true',
                        help='Silent install')
    parser.add_argument('-m','--no-msg', action='store_true', dest='no_msg',
                        help='Suppress pop-ups (/SUPPRESSMSGBOXES)')
    parser.add_argument('-r','--no-restart', action='store_true', dest='no_restart',
                        help='Prevent auto-restart (/NORESTART)')
    parser.add_argument('-p','--skip-prompt', action='store_true', dest='skip_prompt',
                        help='Skip initial prompt (/SP-)')
    parser.add_argument('-x','--extra',
                        help='Additional custom installer flags (space-separated)')
    parser.add_argument('-d','--exit-delay', type=int, default=10,
                        help='Seconds between printing install-dir size updates')
    parser.add_argument('-f','--force', action='store_true',
                        help='Skip confirmation in interactive mode')
    args = parser.parse_args()

    installer = Path(args.installer).resolve()
    if not installer.exists():
        console.print(f"[red]Error:[/red] Installer not found: {installer}")
        sys.exit(1)

    # Define installer flags for detection/listing
    stype = detect_setup_type(str(installer)) or 'inno'
    if args.list_options:
        console.print(f"Detected installer type: [bold]{stype.upper()}[/bold]\n")
        if stype == 'inno':
            flags = {
                'silent':      '/VERYSILENT',
                'gui':         '/SILENT',
                'no_msg':      '/SUPPRESSMSGBOXES',
                'no_restart':  '/NORESTART',
                'skip_prompt': '/SP-',
                'dir':         '/DIR',
            }
        else:
            flags = {
                'silent': '/S',
                'gui':    '/S',
                'dir':    '/D',
            }
        table = Table(title="Available Installer Options")
        table.add_column("Key", style="cyan")
        table.add_column("Flag", style="green")
        table.add_column("Description")
        descs = {
            'silent':      "No UI at all",
            'gui':         "Show progress UI",
            'no_msg':      "Hide pop-ups",
            'no_restart':  "Prevent auto-restart",
            'skip_prompt': "Skip initial prompt",
            'dir':         "Install folder (syntax: DIR=path)",
        }
        for k, v in flags.items():
            table.add_row(k, v, descs.get(k, ""))
        console.print(table)
        sys.exit(0)

    # From here on, -l was not passed, so target is required
    if not args.target:
        console.print("[red]Error:[/red] --target is required unless using -l/--list-options")
        sys.exit(1)

    # Pick fresh log filename next to installer
    base = installer.with_suffix('')
    i = 1
    while True:
        suffix = '' if i == 1 else f'_{i}'
        candidate = base.with_name(base.name + suffix + '.log')
        if not candidate.exists():
            log_path = candidate
            break
        i += 1

    target_dir = Path(args.target).resolve()
    if args.unattended:
        args.non_interactive = True
        args.force         = True
        args.silent        = True
        args.no_msg        = True
        args.no_restart    = True
        args.skip_prompt   = True

    console.print(f"Detected installer type: [bold]{stype.upper()}[/bold]")

    # Set up flags
    if stype == 'inno':
        fd = {
            'silent':      '/VERYSILENT',
            'gui':         '/SILENT',
            'no_msg':      '/SUPPRESSMSGBOXES',
            'no_restart':  '/NORESTART',
            'skip_prompt': '/SP-',
            'dir':         '/DIR',
        }
    else:
        fd = {
            'silent': '/S',
            'gui':    '/S',
            'dir':    '/D',
        }

    flags_list = [f'/LOG={log_path}']
    if args.gui:
        flags_list.append(fd['gui'])
    elif args.silent:
        flags_list.append(fd['silent'])
    if stype == 'inno':
        if args.no_msg:      flags_list.append(fd['no_msg'])
        if args.no_restart:  flags_list.append(fd['no_restart'])
        if args.skip_prompt: flags_list.append(fd['skip_prompt'])
    flags_list.append(f'{fd["dir"]}={target_dir}')
    if args.extra:
        flags_list.extend(shlex.split(args.extra))

    cmd = [str(installer)] + flags_list
    console.print(f"\n[bold]Running:[/bold] {' '.join(cmd)}\n")

    proc = subprocess.Popen(cmd, cwd=installer.parent)

    # wait a bit for log to appear
    start = time.time()
    log_file = None
    while time.time() - start < 5:
        if log_path.exists():
            log_file = open(log_path, 'r', errors='ignore')
            break
        time.sleep(0.2)

    last_report = time.time()
    while proc.poll() is None:
        # stream new lines
        if log_file:
            for line in log_file:
                print(line.rstrip())
        # periodic size report
        now = time.time()
        if now - last_report >= args.exit_delay:
            size_gb = total_size(target_dir) / 1e9
            console.print(f"[cyan]Install dir size:[/cyan] {size_gb:.2f} GB")
            last_report = now
        time.sleep(0.2)

    # final flush
    if log_file:
        remaining = log_file.read()
        if remaining:
            print(remaining.rstrip())
        log_file.close()

    ret = proc.wait()
    if ret == 0:
        console.print("[green]✓ Installation completed successfully[/green]")
    else:
        console.print(f"[red]✗ Installation failed (exit code {ret})[/red]")

if __name__ == "__main__":
    main()
