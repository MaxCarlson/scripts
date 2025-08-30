# File: pyprjs/clip_tools/pyprjs/clip_tools/cli.py
#!/usr/bin/env python3
"""
Unified CLI for clipboard utilities: append, diff, replace-block, copy-buffer,
copy-log, copy, paste, run.

All clipboard/history/tmux interactions are routed through modules/system_tools
via adapters defined in backends.py. No direct subprocess calls for clipboard.
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from rich.console import Console
from rich.table import Table
from rich.text import Text

# Centralized adapters
from .backends import (
    ClipboardAdapter,
    HistoryUtilsAdapter,
    SystemToolsAdapter,
    TmuxAdapter,
)

console_out = Console()
console_err = Console(stderr=True)

WHOLE_WRAP_HEADER_MARKER = "WHOLE_CLIPBOARD_CONTENT_BLOCK_V1"


# -------------------------------
# Utilities
# -------------------------------

def _stats_table(title: str, stats: dict[str, object]) -> Table:
    t = Table(title=title)
    t.add_column("Metric", style="cyan", overflow="fold")
    t.add_column("Value", overflow="fold")
    for k, v in stats.items():
        t.add_row(str(k), str(v))
    return t


def _print_stats_table(title: str, stats: dict[str, object], to_stderr: bool = False) -> None:
    table = _stats_table(title, stats)
    (console_err if to_stderr else console_out).print(table)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _append_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(text)


def _similarity_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(a=a, b=b).ratio()


def _unified_diff(a_lines: List[str], b_lines: List[str], fromfile: str, tofile: str, n: int) -> Iterable[str]:
    return difflib.unified_diff(a_lines, b_lines, fromfile=fromfile, tofile=tofile, n=n)


# -------------------------------
# Subcommand: append
# -------------------------------

def cmd_append(args: argparse.Namespace, sysapi: SystemToolsAdapter) -> int:
    stats: dict[str, object] = {}
    code = 0
    try:
        text = sysapi.get_clipboard().strip()
    except NotImplementedError:
        console_err.print("[bold red]Clipboard get operation is not implemented.[/]")
        stats["Error"] = "get_clipboard NotImplemented"
        code = 1
        if not args.no_stats:
            _print_stats_table("append stats", stats)
        return code
    except Exception as e:
        console_err.print(f"[bold red]Failed to access clipboard: {e}[/]")
        stats["Error"] = f"clipboard error: {e}"
        code = 1
        if not args.no_stats:
            _print_stats_table("append stats", stats)
        return code

    if not text:
        console_err.print("[bold yellow]Clipboard is empty. Aborting.[/]")
        stats["Outcome"] = "No-op (empty clipboard)"
        if not args.no_stats:
            _print_stats_table("append stats", stats)
        return 0

    target = Path(args.file)
    payload = ("\n" + text) if text and not text.startswith("\n") else text
    try:
        _append_text(target, payload)
        stats["File"] = str(target)
        stats["Chars Appended"] = len(payload)
        stats["Lines Appended"] = len(payload.splitlines())
        stats["Outcome"] = "Success"
    except Exception as e:
        code = 1
        stats["Error"] = f"write error: {e}"
        console_err.print(f"[bold red]Failed to write file: {e}[/]")

    if not args.no_stats:
        _print_stats_table("append stats", stats)
    return code


# -------------------------------
# Subcommand: diff
# -------------------------------

def cmd_diff(args: argparse.Namespace, sysapi: SystemToolsAdapter) -> int:
    stats: dict[str, object] = {}
    code = 0
    try:
        file_text = _read_text(Path(args.file))
        clip_text = sysapi.get_clipboard()
    except Exception as e:
        code = 1
        stats["Error"] = str(e)
        console_err.print(f"[bold red]Error: {e}[/]")

    if code == 0:
        file_lines = file_text.splitlines(keepends=False)
        clip_lines = clip_text.splitlines(keepends=False)
        diff = list(_unified_diff(file_lines, clip_lines, fromfile=args.file, tofile="clipboard", n=args.context))
        if diff:
            for line in diff:
                style = None
                if line.startswith("+") and not line.startswith("+++"):
                    style = "green"
                elif line.startswith("-") and not line.startswith("---"):
                    style = "red"
                elif line.startswith("@@"):
                    style = "cyan"
                console_out.print(Text(line.rstrip("\n"), style=style))
        else:
            console_out.print("[green]No differences.[/]")

        file_loc = len(file_lines)
        clip_loc = len(clip_lines)
        stats["File LOC"] = file_loc
        stats["Clipboard LOC"] = clip_loc
        stats["LOC Δ"] = abs(file_loc - clip_loc)
        ratio = _similarity_ratio(file_text, clip_text)
        stats["Similarity"] = f"{ratio:.2%}"

        if abs(file_loc - clip_loc) >= args.warn_loc_delta:
            console_err.print(f"[yellow]Warning: Large LOC delta (≥{args.warn_loc_delta}).[/]")
        if ratio < args.warn_similarity:
            console_err.print(f"[yellow]Warning: Low similarity (<{args.warn_similarity:.2%}).[/]")

    if not args.no_stats:
        _print_stats_table("diff stats", stats)
    return code


# -------------------------------
# Subcommand: replace-block
# -------------------------------

@dataclass
class BlockMatch:
    start: int
    end: int


def _extract_def_or_class_name(py_src: str) -> Optional[str]:
    # Find first 'def name(' or 'class Name(' in clipboard code
    m = re.search(r'^\s*(?:def|class)\s+([A-Za-z_]\w*)\b', py_src, flags=re.MULTILINE)
    return m.group(1) if m else None


def _find_block_in_file(target_src: str, name: str) -> Optional[BlockMatch]:
    """
    Find the block (including decorators) for def/class {name}.

    We capture preceding decorators and then the block up to the next def/class
    at column 0 or EOF.
    """
    pattern = rf'(?ms)^(?:\s*@.*\n)*\s*(?:(?:def|class)\s+{re.escape(name)}\b[\s\S]*?)(?=\n(?:def|class)\s+\w+\b|$)'
    m = re.search(pattern, target_src)
    if not m:
        return None
    return BlockMatch(start=m.start(), end=m.end())


def cmd_replace_block(args: argparse.Namespace, sysapi: SystemToolsAdapter) -> int:
    stats: dict[str, object] = {}
    code = 0
    try:
        clip = sysapi.get_clipboard()
    except Exception as e:
        stats["Error"] = f"clipboard error: {e}"
        console_err.print(f"[bold red]{stats['Error']}[/]")
        code = 1
        if not args.no_stats:
            _print_stats_table("replace-block stats", stats)
        return code

    name = _extract_def_or_class_name(clip)
    if not name:
        stats["Error"] = "Could not determine function/class name from clipboard."
        console_err.print("[bold red]Clipboard does not contain a recognizable def/class header.[/]")
        if not args.no_stats:
            _print_stats_table("replace-block stats", stats)
        return 1

    path = Path(args.file)
    try:
        src = _read_text(path)
    except Exception as e:
        stats["Error"] = f"read error: {e}"
        console_err.print(f"[bold red]Failed to read {path}: {e}[/]")
        if not args.no_stats:
            _print_stats_table("replace-block stats", stats)
        return 1

    matches = list(re.finditer(rf'(?m)^\s*(?:def|class)\s+{re.escape(name)}\b', src))
    if len(matches) == 0:
        stats["Error"] = f"No def/class named {name} found."
        console_err.print(f"[bold red]No def/class named {name} found in {path}.[/]")
        if not args.no_stats:
            _print_stats_table("replace-block stats", stats)
        return 1
    if len(matches) > 1:
        stats["Error"] = f"Multiple def/class named {name} found."
        console_err.print(f"[bold red]Multiple def/class named {name} found in {path}. Aborting.[/]")
        if not args.no_stats:
            _print_stats_table("replace-block stats", stats)
        return 1

    block = _find_block_in_file(src, name)
    if not block:
        stats["Error"] = "Failed to isolate target block."
        console_err.print("[bold red]Failed to isolate target block (decorators + body).[/]")
        if not args.no_stats:
            _print_stats_table("replace-block stats", stats)
        return 1

    new_src = src[:block.start] + clip.rstrip() + "\n" + src[block.end:]
    try:
        _write_text(path, new_src)
    except Exception as e:
        stats["Error"] = f"write error: {e}"
        console_err.print(f"[bold red]Failed to write {path}: {e}[/]")
        if not args.no_stats:
            _print_stats_table("replace-block stats", stats)
        return 1

    stats["File"] = str(path)
    stats["Replaced"] = name
    stats["Outcome"] = "Success"
    if not args.no_stats:
        _print_stats_table("replace-block stats", stats)
    return code


# -------------------------------
# Subcommand: copy-buffer
# -------------------------------

def _strip_since_last_clear(buf: str) -> str:
    """
    Strip text prior to the last clear-like marker. Recognizes a few common sequences:
      - ESC[H ESC[2J (cursor home + clear screen)
      - ESC[3J (clear scrollback)
      - ^L (form feed)
    """
    markers = [
        "\x1b[H\x1b[2J",
        "\x1b[3J",
        "\x0c",  # ^L
    ]
    last = -1
    for m in markers:
        idx = buf.rfind(m)
        if idx > last:
            last = idx
    return buf[last + 1 :] if last >= 0 else buf


def cmd_copy_buffer(args: argparse.Namespace, sysapi: SystemToolsAdapter) -> int:
    stats: dict[str, object] = {}
    code = 0
    try:
        if not sysapi.is_tmux():
            stats["Error"] = "Not running inside tmux."
            console_err.print("[bold red]Not running inside tmux.[/]")
            return 1

        raw = sysapi.tmux_capture_pane()
        stats["Raw Buffer Chars"] = len(raw)
        text = raw if args.full else _strip_since_last_clear(raw)
        stats["Capture Mode"] = "full" if args.full else "since-last-clear"

        final_text = text.strip()
        stats["Final Text Chars"] = len(final_text)
        stats["Final Text Lines"] = len(final_text.splitlines())

        if not final_text:
            console_err.print("[yellow]No content to copy after processing.[/]")
            stats["Clipboard Action"] = "Skipped (no content)"
            code = 0
        else:
            sysapi.set_clipboard(final_text)
            console_out.print(f"Copied {stats['Final Text Lines']} lines "
                              f"({stats['Final Text Chars']} chars) to clipboard.")
            stats["Clipboard Action"] = "Success"
            code = 0
    except NotImplementedError as nie:
        stats["Error"] = f"Not implemented: {nie}"
        console_err.print(f"[bold red]{stats['Error']}[/]")
        code = 1
    except Exception as e:
        stats["Error"] = f"Unexpected error: {e}"
        console_err.print(f"[bold red]{stats['Error']}[/]")
        code = 1
    finally:
        if not args.no_stats:
            _print_stats_table("copy-buffer stats", stats)
    return code


# -------------------------------
# Subcommand: copy-log
# -------------------------------

def _log_file_for_shlvl() -> Path:
    shlvl = os.environ.get("SHLVL", "1")
    return Path(os.path.expanduser(f"~/.term_log.session_shlvl_{shlvl}"))


def cmd_copy_log(args: argparse.Namespace, sysapi: SystemToolsAdapter) -> int:
    stats: dict[str, object] = {}
    code = 0
    try:
        shlvl = os.environ.get("SHLVL", "N/A")
        stats["SHLVL"] = shlvl
        path = _log_file_for_shlvl()
        stats["Log File Path"] = str(path)

        if not path.exists():
            msg = f"Log file '{path}' not found for this session (SHLVL={shlvl})."
            stats["Error"] = msg
            console_err.print(f"[bold red][ERROR] {msg} Make sure logging is set up.[/]")
            return 1

        lines = _read_text(path).splitlines()
        tail = lines[-args.lines :] if args.lines < len(lines) else lines
        text = "\n".join(tail).strip()

        if not text:
            console_out.print(f"Log file '{path}' yielded no content for the last {args.lines} lines.")
            stats["Content Status"] = "No content"
            stats["Lines Copied"] = 0
            stats["Characters Copied"] = 0
            code = 0
        else:
            sysapi.set_clipboard(text)
            console_out.print(f"Last {len(tail)} lines from SHLVL={shlvl} log copied to clipboard.")
            stats["Lines Copied"] = len(tail)
            stats["Characters Copied"] = len(text)
            stats["Content Status"] = "Copied successfully"
            code = 0
    except NotImplementedError:
        stats["Error"] = "Clipboard set not implemented."
        console_err.print("[bold red][ERROR] Clipboard set not implemented.[/]")
        code = 1
    except Exception as e:
        stats["Error"] = f"Unexpected error: {e}"
        console_err.print(f"[bold red][ERROR] {stats['Error']}[/]")
        code = 1
    finally:
        if not args.no_stats:
            _print_stats_table("copy-log stats", stats)
    return code


# -------------------------------
# Subcommand: copy
# -------------------------------

def _read_many(files: List[Path]) -> List[Tuple[Path, str]]:
    out: List[Tuple[Path, str]] = []
    for f in files:
        out.append((f, _read_text(f)))
    return out


def _wrap_individual(files_and_texts: List[Tuple[Path, str]], show_full_path: bool) -> str:
    parts: List[str] = []
    for f, t in files_and_texts:
        path_str = str(f.resolve()) if show_full_path else os.path.relpath(f, start=os.getcwd())
        parts.append(f"# {path_str}\n```\n{t.rstrip()}\n```")
    return "\n\n".join(parts)


def _wrap_whole(files_and_texts: List[Tuple[Path, str]], show_full_path: bool) -> str:
    inner_lines: List[str] = []
    for f, t in files_and_texts:
        if show_full_path:
            inner_lines.append(str(f.resolve()))
        inner_lines.append(os.path.relpath(f, start=os.getcwd()))
        inner_lines.append(t.rstrip())
    return f"{WHOLE_WRAP_HEADER_MARKER}\n```\n" + "\n".join(inner_lines) + "\n```"


def _smart_append(existing: str, new_payload: str) -> str:
    # If existing already contains a WHOLE_WRAP header at top, append inside same block
    if existing.startswith(WHOLE_WRAP_HEADER_MARKER):
        # Insert before final ```
        idx = existing.rfind("\n```")
        if idx != -1:
            return existing[:idx] + "\n" + new_payload + existing[idx:]
    # otherwise, plain append with a separator
    sep = "\n\n" if (existing and not existing.endswith("\n")) else "\n"
    return existing + sep + new_payload


def cmd_copy(args: argparse.Namespace, sysapi: SystemToolsAdapter) -> int:
    stats: dict[str, object] = {}
    code = 0
    files = [Path(p) for p in args.files]
    try:
        ft = _read_many(files)
        raw = args.raw_copy
        wrap_individual = args.wrap or (len(files) > 1 and not args.whole_wrap and not raw)
        whole = args.whole_wrap

        if raw and (wrap_individual or whole):
            console_err.print("[bold red]Choose exactly one of: --raw, --wrap, --whole-wrap.[/]")
            return 1

        if whole:
            payload = _wrap_whole(ft, args.show_full_path)
        elif wrap_individual:
            payload = _wrap_individual(ft, args.show_full_path)
        else:
            payload = "\n".join(t for _, t in ft)

        if args.append:
            try:
                existing = sysapi.get_clipboard()
            except NotImplementedError:
                existing = ""
            except Exception:
                existing = ""
            if args.override_append_wrapping:
                # simple concat append
                sep = "\n\n" if (existing and not existing.endswith("\n")) else "\n"
                final = existing + sep + payload
                note = "Simple append (override enabled)."
            else:
                final = _smart_append(existing, payload)
                note = "Smart append."
        else:
            final = payload
            note = "Overwrite clipboard."

        sysapi.set_clipboard(final)

        # NEW: verify if possible (copy_to_clipboard behavior)
        verification = "Skipped"
        try:
            got = sysapi.get_clipboard()
            verification = "OK" if got == final else "Mismatch"
            if verification == "Mismatch":
                console_err.print("[yellow]Warning: Clipboard verification mismatch.[/]")
        except NotImplementedError:
            verification = "NotImplemented"
        except Exception as e:
            verification = f"Error: {e}"

        stats.update(
            {
                "Files": len(files),
                "Mode": ("raw" if raw else "whole-wrap" if whole else "wrap" if wrap_individual else "raw"),
                "Append": bool(args.append),
                "Append Note": note,
                "Payload Lines": len(final.splitlines()),
                "Payload Chars": len(final),
                "Verification": verification,
                "Outcome": "Success" if verification in ("OK", "Skipped", "NotImplemented") else "Warning",
            }
        )
    except Exception as e:
        code = 1
        stats["Error"] = f"Unexpected error: {e}"
        console_err.print(f"[bold red]{stats['Error']}[/]")
    finally:
        if not args.no_stats:
            _print_stats_table("copy stats", stats)
    return code


# -------------------------------
# Subcommand: paste (replace-with-clipboard)
# -------------------------------

def cmd_paste(args: argparse.Namespace, sysapi: SystemToolsAdapter) -> int:
    stats: dict[str, object] = {}
    code = 0
    try:
        text = sysapi.get_clipboard()
        if args.file:
            p = Path(args.file)
            to_write = text if text.endswith("\n") else text + "\n"
            _write_text(p, to_write)
            console_out.print(f"Wrote clipboard to {p}")
            stats["File"] = str(p)
            stats["Chars Written"] = len(to_write)
            stats["Lines Written"] = len(to_write.splitlines())
            if not args.no_stats:
                _print_stats_table("paste stats", stats)
        else:
            console_out.print(text)
            stats["Output Chars"] = len(text)
            stats["Output Lines"] = len(text.splitlines())
            if not args.no_stats:
                _print_stats_table("paste stats", stats, to_stderr=True)
    except Exception as e:
        code = 1
        stats["Error"] = f"clipboard/file error: {e}"
        console_err.print(f"[bold red]{stats['Error']}[/]")
        if not args.no_stats:
            _print_stats_table("paste stats", stats, to_stderr=not args.file)
    return code


# -------------------------------
# Subcommand: run (output-to-clipboard)
# -------------------------------

def _join_command(parts: List[str]) -> str:
    # join using shell-ish quoting for clarity
    return " ".join(shlex.quote(p) for p in parts)


def cmd_run(args: argparse.Namespace, sysapi: SystemToolsAdapter) -> int:
    """
    Execute a command or replay a command from history and copy stdout+stderr to clipboard.
    Stats table is printed to stderr (matches original behavior).
    """
    stats: dict[str, object] = {}
    code = 0

    try:
        command_str = ""
        # Determine mode / command
        if args.command_and_args and not (len(args.command_and_args) == 1 and args.command_and_args[0] == "--"):
            # Explicit command provided
            command_str = _join_command(args.command_and_args)
            stats["Mode"] = "Direct Command"
            stats["Provided Command"] = command_str
            if args.replay_history is not None:
                console_err.print("[INFO] Both command and --replay-history specified. Executing provided command.")
        else:
            # No explicit command. NEW: default to replay last command if not provided (parity with legacy).
            replay_n = args.replay_history if args.replay_history is not None else 1  # ← default N=1
            stats["Mode"] = f"Replay History (N={replay_n})"

            if replay_n <= 0:
                msg = "Value for --replay-history (-r) must be positive."
                stats["Error"] = msg
                console_err.print(f"[bold red][ERROR] {msg}[/]")
                return 1

            console_err.print(f"[INFO] Attempting to replay history entry N={replay_n}...")
            hist = HistoryUtilsAdapter()
            last_cmd = hist.get_nth_recent_command(replay_n)
            stats["History Fetch Attempted For N"] = replay_n
            if not last_cmd:
                msg = f"Failed to retrieve the {replay_n}{'st' if replay_n==1 else 'nd' if replay_n==2 else 'rd' if replay_n==3 else 'th'} command from history."
                stats["Error"] = msg
                stats["History Command Found"] = "No"
                console_err.print(f"[bold red][ERROR] {msg}[/]")
                return 1
            stats["History Command Found"] = last_cmd
            console_err.print(f"[INFO] Found history command: '{last_cmd}'")

            # Loop prevention: do not execute ourselves
            script_name = Path(sys.argv[0]).name
            script_stem = Path(sys.argv[0]).stem
            parts0 = shlex.split(last_cmd)
            if parts0:
                first = parts0[0]
                if first in (script_name, script_stem, f"./{script_name}", f"./{script_stem}", "python", "bash"):
                    # basic detection – if it looks like calling this tool
                    norm = " ".join(parts0)
                    console_err.print(f"[bold red]Loop detected: '{norm}' is this script. Aborting.[/]")
                    stats["Error"] = "Replay loop prevention triggered."
                    return 1

            # Ask for confirmation
            resp = console_err.input("[INFO] Re-run this command? [y/N]: ")
            if resp.lower() != "y":
                console_err.print("[INFO] User cancelled re-run.")
                stats["User Confirmation"] = "No"
                return 0
            console_err.print(f"[INFO] User approved. Re-running: {last_cmd}")
            stats["User Confirmation"] = "Yes"
            command_str = last_cmd

        if not command_str:
            stats["Error"] = "No command provided and no replay triggered."
            console_err.print("[bold red][ERROR] Internal Error: No command to execute.[/]")
            return 1

        # Execute
        import subprocess

        result = subprocess.run(command_str, shell=True, capture_output=True, text=True, check=False)
        stats["Command Executed"] = command_str
        stats["Command Exit Status"] = result.returncode
        stats["Stdout Length (raw)"] = len(result.stdout)
        stats["Stderr Length (raw)"] = len(result.stderr)

        combined = (result.stdout or "") + (result.stderr or "")
        output_to_copy = combined.strip()
        if not output_to_copy:
            console_out.print(f"Command '{command_str}' produced no output to copy.")
            stats["Output Status"] = "Empty"
            stats["Lines Copied"] = 0
            stats["Characters Copied"] = 0
        else:
            if args.wrap:
                header = f"$ {command_str}"
                output_to_copy = f"{header}\n```\n{output_to_copy}\n```"
                stats["Wrapping Mode"] = "Wrapped (command + code block)"
            else:
                stats["Wrapping Mode"] = "Raw"

            sysapi.set_clipboard(output_to_copy)
            console_out.print("Copied command output to clipboard.")
            stats["Output Status"] = "Copied"
            stats["Lines Copied"] = len(output_to_copy.splitlines())
            stats["Characters Copied"] = len(output_to_copy)

        if result.returncode != 0:
            warn = f"Command '{command_str}' exited with status {result.returncode}"
            console_err.print(f"[yellow][WARNING] {warn}[/]")
            stats["Command Warning"] = warn

    except Exception as e:
        code = 1
        stats.setdefault("Error", f"Unexpected error: {e}")
        console_err.print(f"[bold red]{stats['Error']}[/]")
    finally:
        if not args.no_stats:
            _print_stats_table("run stats", stats, to_stderr=True)
    return code


# -------------------------------
# CLI wiring
# -------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="clip_tools", description="Unified clipboard utilities")
    sub = p.add_subparsers(dest="cmd", required=True)

    # append
    ap = sub.add_parser("append", help="Append clipboard text to a file")
    ap.add_argument("file")
    ap.add_argument("--no-stats", action="store_true")
    ap.set_defaults(func=cmd_append)

    # diff
    dp = sub.add_parser("diff", help="Diff clipboard vs file (unified)")
    dp.add_argument("file")
    dp.add_argument("-c", "--context", type=int, default=3)
    dp.add_argument("--warn-loc-delta", type=int, default=50)
    dp.add_argument("--warn-similarity", type=float, default=0.75)
    dp.add_argument("--no-stats", action="store_true")
    dp.set_defaults(func=cmd_diff)

    # replace-block
    rb = sub.add_parser("replace-block", help="Replace def/class in file with clipboard")
    rb.add_argument("file")
    rb.add_argument("--no-stats", action="store_true")
    rb.set_defaults(func=cmd_replace_block)

    # copy-buffer
    cb = sub.add_parser("copy-buffer", help="Copy tmux pane buffer to clipboard")
    cb.add_argument("-f", "--full", action="store_true", help="Copy full buffer (default: since last clear)")
    cb.add_argument("--no-stats", action="store_true")
    cb.set_defaults(func=cmd_copy_buffer)

    # copy-log
    cl = sub.add_parser("copy-log", help="Copy last N lines from SHLVL session log")
    cl.add_argument("-n", "--lines", type=int, default=10)
    cl.add_argument("--no-stats", action="store_true")
    cl.set_defaults(func=cmd_copy_log)

    # copy (copy_to_clipboard)
    cp = sub.add_parser("copy", help="Copy files to clipboard")
    cp.add_argument("files", nargs="+")
    cp.add_argument("-r", "--raw-copy", action="store_true", help="Raw concatenation")
    cp.add_argument("-w", "--wrap", action="store_true", help="Individually wrap each file")
    cp.add_argument("-W", "--whole-wrap", action="store_true", help="Wrap combined content in a single marked block")
    cp.add_argument("-f", "--show-full-path", action="store_true", help="Include absolute paths in headers")
    cp.add_argument("-a", "--append", action="store_true", help="Append into existing clipboard")
    cp.add_argument("-o", "--override-append-wrapping", action="store_true",
                    help="Do a simple textual append instead of smart append")
    cp.add_argument("--no-stats", action="store_true")
    cp.set_defaults(func=cmd_copy)

    # paste (replace_with_clipboard)
    ps = sub.add_parser("paste", help="Replace file with clipboard or print clipboard")
    ps.add_argument("file", nargs="?")
    ps.add_argument("--no-stats", action="store_true")
    ps.set_defaults(func=cmd_paste)

    # run (output_to_clipboard)
    rn = sub.add_parser("run", help="Run a command (or replay history) and copy output")
    rn.add_argument("-r", "--replay-history", type=int, dest="replay_history",
                    help="Re-run Nth most recent command; if no command is provided, defaults to 1.")
    rn.add_argument("-w", "--wrap", action="store_true", help="Wrap command output in a code block with header")
    rn.add_argument("--no-stats", action="store_true")
    rn.add_argument("command_and_args", nargs=argparse.REMAINDER,
                    help="Command to execute. If starts with '-', prefix with '--'.")
    rn.set_defaults(func=cmd_run)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    sysapi = SystemToolsAdapter(ClipboardAdapter(), HistoryUtilsAdapter(), TmuxAdapter())
    return args.func(args, sysapi)


if __name__ == "__main__":
    sys.exit(main())
