#!/usr/bin/env python3
"""
run_installers.py — Launch Inno Setup/NSIS-based installers remotely

Features:
- Detects setup.exe type (Inno/NSIS)
- Interactive & unattended CLI
- Streams installer log with rich formatting
- Periodically shows install directory size
- Auto-exits after "Run entry" appears + no folder change for N seconds

Requires: rich
"""

import argparse, subprocess, sys, shlex, time, os, re
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.table import Table
from rich.prompt import Confirm
from rich.text import Text

LOG_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2}) (?P<time>\d{2}:\d{2}:\d{2}\.?\d*)\s*(?P<msg>.*)")
FINAL_LOG_MARKER = "Run entry"

def print_colored(line: str, console: Console):
    m = LOG_RE.match(line)
    if m:
        ts = Text(m.group("ts"), style="grey50")
        tm = Text(m.group("time"), style="cyan")
        msg = Text(m.group("msg"), style="white")
        console.print(ts.append(" ").append(tm).append("  ").append(msg))
    else:
        console.print(line.strip(), style="white")

def detect_setup_type(path: str) -> Optional[str]:
    sigs = {'inno': b'Inno Setup', 'nsis': b'Nullsoft Install System'}
    try:
        data = Path(path).read_bytes()[:200_000]
        for t, sig in sigs.items():
            if sig in data:
                return t
    except:
        pass
    return None

def total_size(path: Optional[Path]) -> int:
    if not path or not path.exists(): return 0
    return sum((Path(root)/f).stat().st_size for root, _, files in os.walk(path) for f in files if (Path(root)/f).exists())

def file_count(path: Optional[Path]) -> int:
    return sum(len(files) for _, _, files in os.walk(path)) if path and path.exists() else 0

def main():
    console = Console()
    p = argparse.ArgumentParser(description="Remote installer helper for setup.exe")
    p.add_argument("-i","--installer",required=True, help="Path to setup.exe")
    p.add_argument("-l","--list-options",action="store_true", help="List supported flags and exit")
    p.add_argument("-t","--target", help="Install directory (required unless -l)")
    p.add_argument("-n","--non-interactive",action="store_true")
    p.add_argument("-u","--unattended",action="store_true")
    p.add_argument("-g","--gui",action="store_true")
    p.add_argument("-s","--silent",action="store_true")
    p.add_argument("-m","--no-msg",action="store_true",dest="no_msg")
    p.add_argument("-r","--no-restart",action="store_true",dest="no_restart")
    p.add_argument("-p","--skip-prompt",action="store_true",dest="skip_prompt")
    p.add_argument("-x","--extra", help="Additional installer flags (quoted)")
    p.add_argument("-d","--exit-delay",type=int,default=10, help="Seconds of no activity before exit")
    p.add_argument("-f","--force",action="store_true")
    args = p.parse_args()

    installer = Path(args.installer).resolve()
    if not installer.exists(): console.print(f"[red]Missing:[/red] {installer}"); sys.exit(1)

    stype = detect_setup_type(str(installer)) or "inno"

    if args.list_options:
        console.print(f"[bold]Detected installer:[/bold] {stype.upper()}")
        table = Table(title="Supported Flags")
        table.add_column("Key", style="cyan"); table.add_column("Flag", style="green")
        opts = {"silent": "/VERYSILENT or /S", "gui": "/SILENT", "no_msg": "/SUPPRESSMSGBOXES", 
                "no_restart": "/NORESTART", "skip_prompt": "/SP-", "dir": "/DIR or /D"}
        for k,v in opts.items(): table.add_row(k, v)
        console.print(table); sys.exit(0)

    if not args.target:
        console.print("[red]--target required unless using -l[/red]"); sys.exit(1)
    target = Path(args.target).resolve()

    base = installer.with_suffix("")
    for idx in range(1,100):
        log_path = base.with_name(f"{base.name}_{idx}.log") if idx > 1 else base.with_name(f"{base.name}.log")
        if not log_path.exists(): break

    if args.unattended:
        args.non_interactive = args.force = True
        args.silent = args.no_msg = args.no_restart = args.skip_prompt = True

    console.print(f"[bold]Installer:[/bold] {stype.upper()}")
    fd = {"silent": "/VERYSILENT" if stype == "inno" else "/S",
          "gui": "/SILENT" if stype == "inno" else "/S",
          "no_msg": "/SUPPRESSMSGBOXES", "no_restart": "/NORESTART",
          "skip_prompt": "/SP-", "dir": "/DIR" if stype == "inno" else "/D"}

    if not args.non_interactive:
        if not args.gui:
            args.silent = Confirm.ask("Silent install?", default=True)
        if args.silent:
            args.no_msg = Confirm.ask("Suppress popups?", default=True)
            args.no_restart = Confirm.ask("Prevent restart?", default=True)
            args.skip_prompt = Confirm.ask("Skip prompt?", default=True)

    cmd_flags = [f"/LOG={log_path}"]
    cmd_flags.append(fd["gui"] if args.gui else fd["silent"])
    if args.no_msg: cmd_flags.append(fd["no_msg"])
    if args.no_restart: cmd_flags.append(fd["no_restart"])
    if args.skip_prompt: cmd_flags.append(fd["skip_prompt"])
    cmd_flags.append(f'{fd["dir"]}={target}')
    if args.extra: cmd_flags.extend(shlex.split(args.extra))
    cmd = [str(installer)] + cmd_flags
    console.print(f"[magenta]Running:[/magenta] {' '.join(cmd)}\n")

    start_time = time.time()
    proc = subprocess.Popen(cmd, cwd=installer.parent)

    for _ in range(50):
        if log_path.exists(): break
        time.sleep(0.2)
    log_file = open(log_path, "r", errors="ignore") if log_path.exists() else None

    last_size = -1
    last_report_time = time.time()
    exit_watch_started = False
    exit_watch_time = 0
    final_log_seen = False

    while True:
        now = time.time()

        # Stream log
        if log_file:
            line = log_file.readline()
            while line:
                print_colored(line.rstrip(), console)
                if FINAL_LOG_MARKER in line:
                    final_log_seen = True
                    exit_watch_time = now
                    last_report_time = now  # reset delay start
                line = log_file.readline()

        size = total_size(target)
        if size != last_size:
            last_size = size
            exit_watch_time = now  # reset timer if dir changed

        if now - last_report_time > args.exit_delay:
            console.print(f"[cyan]Install dir size: {size/1e9:.2f} GB[/cyan]")
            last_report_time = now

        if final_log_seen and (now - exit_watch_time) > args.exit_delay:
            break

        time.sleep(0.2)

    if log_file:
        log_file.close()

    dur = time.time() - start_time
    final_gb = total_size(target) / 1e9
    count = file_count(target)
    console.print(f"\n[green]✔ Done in {dur:.1f}s — {final_gb:.2f} GB, {count} files[/green]")
    sys.exit(proc.returncode or 0)

if __name__ == "__main__":
    main()
