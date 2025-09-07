#!/usr/bin/env python3
# pyscripts/set_clipboard_text.py
import sys
import argparse
from cross_platform.clipboard_utils import set_clipboard, get_clipboard
from rich.console import Console
from rich.table import Table

out = Console()
err = Console(stderr=True)

p = argparse.ArgumentParser(
    description="Set clipboard from a provided string or stdin. Can append.",
    formatter_class=argparse.RawTextHelpFormatter,
)
p.add_argument("-t", "--text", help="Text to copy. If omitted, read from stdin.")
p.add_argument("-a", "--append", action="store_true", help="Append to current clipboard.")
p.add_argument("--no-stats", action="store_true", help="Suppress stats table output.")
args = p.parse_args()

try:
    new_text = args.text
    if new_text is None:
        if sys.stdin.isatty():
            err.print("[bold red]No --text provided and stdin is a TTY. Nothing to copy.[/]")
            sys.exit(1)
        new_text = sys.stdin.read()

    if args.append:
        try:
            existing = get_clipboard() or ""
        except Exception:
            existing = ""
        payload = (existing.rstrip("\r\n ") + " " + new_text.lstrip("\r\n ")) if existing else new_text
    else:
        payload = new_text

    set_clipboard(payload)

    if not args.no_stats:
        tbl = Table(title="set_clipboard_text.py Statistics")
        tbl.add_column("Metric", style="cyan")
        tbl.add_column("Value", overflow="fold")
        tbl.add_row("Mode", "Append" if args.append else "Replace")
        tbl.add_row("Chars", str(len(payload)))
        tbl.add_row("Lines", str(len(payload.splitlines())))
        out.print(tbl)

    sys.exit(0)
except Exception as e:
    err.print(f"[bold red]Error:[/] {e}")
    sys.exit(1)
