# File: pyprjs/clip_tools/cli.py
#!/usr/bin/env python3
"""
clip_tools: unified CLI for clipboard workflows.

Subcommands (mapped from your existing scripts):
- append         (append_clipboard.py)          -> apc
- diff           (clipboard_diff.py)            -> cld
- replace-block  (clipboard_replace.py)         -> crx
- copy-buffer    (copy_buffer_to_clipboard.py)  -> cb2c / cb2cf (-f)
- copy-log       (copy_log_to_clipboard.py)
- copy           (copy_to_clipboard.py)         -> c2c/c2cd/c2cr/c2ca
- paste          (replace_with_clipboard.py)    -> rwc
- run            (output_to_clipboard.py)       -> otc/otcw (-w)

Notes:
- All clipboard/tmux/history access is via clip_tools.backends adapters.
- Stats output mirrors the original scripts and can be disabled with --no-stats.
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from rich.console import Console
from rich.table import Table
from rich.text import Text

from .backends import (
    get_clipboard,
    set_clipboard,
    SystemUtilsAdapter,
    TmuxManagerAdapter,
    HistoryUtilsAdapter,
)

console_out = Console()
console_err = Console(stderr=True)

WHOLE_WRAP_HEADER_MARKER = "WHOLE_CLIPBOARD_CONTENT_BLOCK_V1"


class RealSysAPI:
    """
    Real system adapter that uses the project's backends.
    This provides a consistent interface for both the application and tests.
    """
    def __init__(self):
        self._system_utils = None
        self._tmux_manager = None

    def get_clipboard(self) -> str:
        return get_clipboard()

    def set_clipboard(self, text: str) -> None:
        set_clipboard(text)

    def is_tmux(self) -> bool:
        # Lazy load
        if self._system_utils is None:
            self._system_utils = SystemUtilsAdapter()
        return self._system_utils.is_tmux()

    def tmux_capture_pane(self, start_line: str = "-10000") -> Optional[str]:
        # Lazy load
        if self._tmux_manager is None:
            self._tmux_manager = TmuxManagerAdapter()
        return self._tmux_manager.capture_pane(start_line=start_line)


# =====================================================================================
# Helpers reused by subcommands
# =====================================================================================

def _print_stats_table(title: str, stats: dict, to_stderr: bool = False) -> None:
    con = console_err if to_stderr else console_out
    table = Table(title=title)
    table.add_column("Metric", style="cyan", overflow="fold")
    table.add_column("Value", overflow="fold")
    for k, v in stats.items():
        table.add_row(str(k), str(v))
    con.print(table)


def _generate_file_header(file_path: Path, show_full_path: bool, current_dir: Path) -> str:
    abs_path = str(file_path.resolve())
    rel_path = os.path.relpath(file_path, current_dir)
    header_lines = [abs_path] if show_full_path else []
    header_lines.append(rel_path)
    return "\n".join(header_lines)


def _is_whole_wrapped_block(text: str) -> bool:
    return text.startswith(WHOLE_WRAP_HEADER_MARKER + "\n```") and text.rstrip().endswith("\n```")


def _extract_content_from_whole_wrapped_block(text: str) -> Optional[str]:
    if _is_whole_wrapped_block(text):
        m = re.search(re.escape(WHOLE_WRAP_HEADER_MARKER) + r"\n```\n", text)
        if not m:
            return None
        start = m.end()
        end = text.rfind("\n```")
        if end > start:
            return text[start:end]
    return None


def _extract_payload_from_single_script_generated_block(block_text: str) -> str:
    if block_text.startswith(WHOLE_WRAP_HEADER_MARKER + "\n```"):
        inner = _extract_content_from_whole_wrapped_block(block_text)
        return inner if inner is not None else block_text

    m = re.match(r"^(.*?)\n```\n(.*?)\n```$", block_text.rstrip(), re.DOTALL)
    if m:
        header = m.group(1)
        inner = m.group(2)
        return f"{header}\n{inner}"
    return block_text


# =====================================================================================
# Subcommand implementations
# =====================================================================================

def cmd_append(args, sys_api) -> int:
    stats = {}
    code = 0
    try:
        path = Path(args.file)
        stats["File Path"] = str(path.resolve())

        try:
            clip = sys_api.get_clipboard()
        except NotImplementedError:
            stats["Error"] = "Clipboard get not implemented"
            console_err.print("[bold red][ERROR] Clipboard functionality not implemented.[/]")
            return 1
        except Exception as e:
            stats["Error"] = f"Failed to get clipboard: {e}"
            console_err.print(f"[bold red][ERROR] {stats['Error']}[/]")
            return 1

        if not clip or clip.strip() == "":
            stats["Clipboard Status"] = "Empty"
            console_err.print("Clipboard is empty. Aborting.")
            code = 0
        else:
            txt = "\n" + clip
            try:
                existed = path.exists()
                if not existed:
                    console_err.print(f"Note: File '{path}' did not exist, it will be created.")
                    stats["File Action"] = "Created new file (as it was appended to)"
                else:
                    stats["File Action"] = "Appended to existing file"

                with path.open("a", encoding="utf-8") as f:
                    chars = f.write(txt)

                console_out.print(f"Appended clipboard contents to '{path}'.")
                stats["Chars Appended"] = chars
                stats["Lines Appended (from clipboard)"] = len(clip.splitlines())
                stats["Total Lines Written to file"] = len(txt.splitlines())
                stats["Outcome"] = "Successfully appended."
                code = 0
            except Exception as e:
                stats["Error"] = f"Error writing to file '{path}': {e}"
                console_err.print(f"[bold red][ERROR] {stats['Error']}[/]")
                code = 1
    finally:
        if not args.no_stats:
            _print_stats_table("append (clip_tools) Statistics", stats)
    return code


def cmd_diff(args, sys_api) -> int:
    stats = {}
    code = 0
    try:
        path = Path(args.file)
        stats["File Path"] = str(path.resolve())

        try:
            file_lines = path.read_text(encoding="utf-8").splitlines()
            stats["File Read"] = "Successful"
            stats["File LOC"] = len(file_lines)
        except Exception as e:
            stats["File Read"] = f"Error: {e}"
            console_err.print(f"[bold red][ERROR] Could not read file '{path}': {e}[/]")
            return 1

        try:
            clip = sys_api.get_clipboard()
        except NotImplementedError:
            stats["Error"] = "Clipboard get not implemented"
            console_err.print("[bold red][ERROR] Clipboard functionality not implemented.[/]")
            return 1
        except Exception as e:
            stats["Error"] = f"Failed to get clipboard: {e}"
            console_err.print(f"[bold red][ERROR] {stats['Error']}[/]")
            return 1

        if not clip or clip.isspace():
            stats["Clipboard Status"] = "Empty or whitespace"
            console_err.print("[bold red][CRITICAL WARNING] Clipboard is empty or contains only whitespace![/]")
            return 1

        clip_lines = clip.splitlines()
        stats["Clipboard LOC"] = len(clip_lines)

        diff_gen = difflib.unified_diff(
            file_lines, clip_lines,
            fromfile=f"file: {path}",
            tofile="clipboard",
            lineterm="",
            n=args.context_lines
        )

        has_diff = False
        n_lines = 0
        for line in diff_gen:
            has_diff = True
            n_lines += 1
            if line.startswith('---') or line.startswith('+++'):
                console_out.print(line)
            elif line.startswith('@@'):
                console_out.print(Text(line, style="cyan"))
            elif line.startswith('-'):
                console_out.print(Text(line, style="red"))
            elif line.startswith('+'):
                console_out.print(Text(line, style="green"))
            else:
                console_out.print(line)
        stats["Diff Lines Generated"] = n_lines
        stats["Differences Found"] = "Yes" if has_diff or n_lines else "No"
        code = 0

        loc_difference = abs(len(file_lines) - len(clip_lines))
        stats["LOC Difference"] = loc_difference
        if loc_difference > args.loc_diff_warn:
            msg = f"Warning: Large LOC delta detected ({loc_difference} lines)."
            console_err.print(f"[orange3]{msg}[/]")
            stats["LOC Difference Warning"] = "Issued"

        ratio = difflib.SequenceMatcher(None, "\n".join(file_lines), "\n".join(clip_lines)).ratio()
        stats["Similarity Ratio"] = f"{ratio:.2f}"
        if ratio < args.similarity_threshold:
            console_err.print(f"[yellow]Warning: Low similarity (ratio {ratio:.2f}).[/]")
            stats["Dissimilarity Note"] = "Issued"
    finally:
        if not args.no_stats:
            _print_stats_table("diff (clip_tools) Statistics", stats)
    return code


def _extract_py_symbol_from_code(code: str) -> str:
    m = re.search(r"^\s*(?:@[^\n]+\n)*\s*(def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", code, re.MULTILINE)
    if not m:
        console_err.print("Clipboard content does not appear to be a Python def/class. Aborting.", style="bold red")
        raise SystemExit(1)
    return m.group(2)


def _replace_python_block(lines: List[str], name: str, new_block: str) -> Tuple[List[str], dict]:
    stats = {"original_lines_in_block": 0, "new_lines_in_block": 0}
    start_idx, block_indent, block_start = None, None, -1

    for i, line in enumerate(lines):
        if re.match(rf"^\s*(def|class)\s+{name}\b", line):
            block_start = i
            block_indent = len(line) - len(line.lstrip())
            start_idx = i
            for j in range(i - 1, -1, -1):
                if re.match(r"^\s*@", lines[j]):
                    if (len(lines[j]) - len(lines[j].lstrip())) <= block_indent:
                        start_idx = j
                    else:
                        break
                elif lines[j].strip() == "":
                    continue
                else:
                    break
            break

    if start_idx is None or block_start == -1:
        console_err.print(f"Function/class '{name}' not found. Aborting.", style="bold red")
        raise SystemExit(1)

    for i in range(block_start + 1, len(lines)):
        if re.match(rf"^\s*(def|class)\s+{name}\b", lines[i]):
            console_err.print(f"Error: Multiple definitions of '{name}' found. Aborting.", style="bold red")
            raise SystemExit(1)

    end = block_start + 1
    while end < len(lines):
        lc = lines[end]
        if lc.strip():
            if (len(lc) - len(lc.lstrip())) <= block_indent:
                break
        end += 1

    stats["original_lines_in_block"] = (end - start_idx)
    new_lines = [ln + "\n" for ln in new_block.rstrip("\n").split("\n")]
    stats["new_lines_in_block"] = len(new_lines)
    updated = lines[:start_idx] + new_lines + lines[end:]
    return updated, stats


def cmd_replace_block(args, sys_api) -> int:
    stats = {}
    code = 0
    try:
        path = Path(args.file)
        stats["File Path"] = str(path.resolve())
        try:
            clip = sys_api.get_clipboard()
        except NotImplementedError:
            stats["Error"] = "Clipboard get not implemented."
            console_err.print(f"[bold red][ERROR] {stats['Error']}[/]")
            return 1
        except Exception as e:
            stats["Error"] = f"Failed to get clipboard: {e}"
            console_err.print(f"[bold red][ERROR] {stats['Error']}[/]")
            return 1

        if not clip:
            stats["Clipboard Status"] = "Empty"
            console_err.print("Clipboard is empty. Aborting.", style="bold red")
            return 1

        name = _extract_py_symbol_from_code(clip)
        stats["Target Name (from clipboard)"] = name

        if not path.exists():
            stats["File Status"] = "Not found"
            console_err.print(f"Error: File '{path}' not found. Aborting.", style="bold red")
            return 1

        original = path.read_text(encoding="utf-8").splitlines(keepends=True)
        updated, blk = _replace_python_block(original, name, clip)
        stats.update(blk)

        try:
            with path.open("w", encoding="utf-8") as f:
                f.writelines(updated)
            console_out.print(f"Replaced '{name}' successfully in '{path}'.")
            stats["Outcome"] = "Success"
            stats["Lines in Original File"] = len(original)
            stats["Lines in Updated File"] = len(updated)
            code = 0
        except Exception as e:
            stats["Error"] = f"Error writing to file '{path}': {e}"
            console_err.print(f"[bold red][ERROR] {stats['Error']}[/]")
            code = 1
    except SystemExit as e:
        return e.code
    finally:
        if not args.no_stats:
            _print_stats_table("replace-block (clip_tools) Statistics", stats)
    return code


def cmd_copy_buffer(args, sys_api) -> int:
    stats = {}
    code = 0
    try:
        if not sys_api.is_tmux():
            stats["Environment"] = "Not a tmux session"
            msg = "This command is designed to run inside a tmux session."
            stats["Error"] = msg
            console_err.print(f"[bold red][ERROR] {msg}[/]")
            return 1

        stats["Environment"] = "tmux session detected"
        buf = sys_api.tmux_capture_pane(start_line='-10000')
        if buf is None:
            stats["Buffer Capture"] = "Failed"
            console_err.print("[bold red][ERROR] Failed to capture tmux pane buffer.[/]")
            return 1

        stats["Buffer Capture"] = "Success"
        stats["Raw Buffer Chars"] = len(buf)
        stats["Raw Buffer Lines"] = len(buf.splitlines())

        if args.full:
            stats["Mode"] = "Full Buffer"
            text = buf
        else:
            stats["Mode"] = "Since Last Clear (Smart)"
            clear_sequence = "\x1b[H\x1b[2J"
            pos = buf.rfind(clear_sequence)
            if pos != -1:
                text = buf[pos + len(clear_sequence):]
                stats["Clear Sequence Found"] = f"Yes (at index {pos})"
            else:
                text = buf
                stats["Clear Sequence Found"] = "No"
                console_err.print("[yellow][WARNING] Could not find 'clear' sequence. Copying entire buffer.[/yellow]")

        final = text.strip()
        stats["Final Text Chars"] = len(final)
        stats["Final Text Lines"] = len(final.splitlines())

        if not final:
            console_err.print("[INFO] No content to copy after processing.")
            stats["Clipboard Action"] = "Skipped (no content)"
        else:
            sys_api.set_clipboard(final)
            console_err.print(f"[INFO] Copied {stats['Final Text Lines']} lines ({stats['Final Text Chars']} chars) to clipboard.")
            stats["Clipboard Action"] = "Success"
        code = 0
    except Exception as e:
        stats["Error"] = f"Unexpected error: {e}"
        console_err.print(f"[bold red][ERROR] {stats['Error']}[/]")
        code = 1
    finally:
        if not args.no_stats:
            _print_stats_table("copy-buffer (clip_tools) Statistics", stats)
    return code


def cmd_copy_log(args, sys_api) -> int:
    stats = {"Lines Requested": args.lines}
    code = 0
    try:
        shlvl = os.environ.get("SHLVL", "N/A")
        stats["SHLVL"] = shlvl
        log_file = Path(os.path.expanduser(f"~/.term_log.session_shlvl_{os.environ.get('SHLVL','1')}"))
        stats["Log File Path"] = str(log_file)

        if not log_file.exists():
            msg = f"Log file '{log_file}' not found for this session (SHLVL={shlvl})."
            stats["Error"] = msg
            console_err.print(f"[bold red][ERROR] {msg}[/]")
            return 1

        all_lines = log_file.read_text(encoding="utf-8").splitlines()
        out_lines = all_lines if args.lines >= len(all_lines) else all_lines[-args.lines:]
        text = "\n".join(out_lines).strip()

        if not text:
            console_out.print(f"Log file '{log_file}' yielded no content for the last {args.lines} lines.")
            stats["Content Status"] = "None"
            return 0

        sys_api.set_clipboard(text)
        console_out.print(f"Last {len(out_lines)} lines from SHLVL={shlvl} log copied to clipboard.")
        stats["Lines Copied"] = len(out_lines)
        stats["Characters Copied"] = len(text)
        stats["Content Status"] = "Copied successfully"
        code = 0
    except Exception as e:
        stats["Error"] = f"Unexpected error: {e}"
        console_err.print(f"[bold red][ERROR] {stats['Error']}[/]")
        code = 1
    finally:
        if not args.no_stats:
            _print_stats_table("copy-log (clip_tools) Statistics", stats)
    return code


def cmd_copy(args, sys_api) -> int:
    stats = {}
    code = 0
    try:
        if args.override_append_wrapping and not args.append:
            console_err.print("[bold red][ERROR] --override-append-wrapping (-o) can only be used with --append (-a).[/]")
            return 1

        file_paths = [Path(p) for p in args.files]
        current_dir = Path.cwd()

        # Determine mode (replicates original behavior)
        if args.raw_copy:
            mode = "raw_explicit"
        elif args.wrap:
            mode = "individual_wrap"
        elif args.whole_wrap:
            mode = "whole_wrap"
        elif len(file_paths) > 1:
            mode = "individual_wrap_multi_default"
        else:
            mode = "raw_single_default"
        stats["Effective New Content Mode"] = mode
        stats["Append Mode"] = "Enabled" if args.append else "Disabled"
        stats["Override Append Wrapping"] = "Enabled" if args.override_append_wrapping else "Disabled"

        parts = []
        success_count = 0
        for p in file_paths:
            try:
                parts.append((p, p.read_text(encoding="utf-8")))
                success_count += 1
                console_err.print(f"[INFO] Successfully read '{p}'.")
            except FileNotFoundError:
                console_err.print(f"[WARNING] File not found: '{p}'. Skipping.")
            except Exception as e:
                console_err.print(f"[WARNING] Could not read file '{p}': {e}. Skipping.")

        stats["Input Files Specified"] = len(file_paths)
        stats["Files Successfully Processed"] = success_count
        stats["Files Failed/Skipped"] = len(file_paths) - success_count

        if not success_count:
            console_err.print("[bold red][ERROR] No files successfully processed. Nothing to copy.[/]")
            return 1

        if mode in ["raw_explicit", "raw_single_default"]:
            new_text = "".join([c for _, c in parts])
            stats["Mode Description"] = "Raw content" + (" (due to --raw-copy)" if mode == "raw_explicit" else " (single file default)")
        elif mode in ["individual_wrap", "individual_wrap_multi_default"]:
            blocks = []
            for path_obj, content in parts:
                header = _generate_file_header(path_obj, args.show_full_path, current_dir)
                blocks.append(f"{header}\n```\n{content}\n```")
            new_text = "\n\n".join(blocks)
            stats["Mode Description"] = "Individually wrapped files" + (" (multiple files default)" if mode.endswith("multi_default") else " (due to --wrap)")
        else:  # whole_wrap
            inner = []
            for path_obj, content in parts:
                header = _generate_file_header(path_obj, args.show_full_path, current_dir)
                inner.append(f"{header}\n{content}")
            payload = "\n\n---\n\n".join(inner)
            new_text = f"{WHOLE_WRAP_HEADER_MARKER}\n```\n{payload}\n```"
            stats["Mode Description"] = "All content in a single marked wrapper block (due to --whole-wrap)"

        final_text = new_text
        original = None

        if args.append:
            try:
                original = sys_api.get_clipboard()
                stats["Original Clipboard Read For Append"] = "Success"
            except Exception as e:
                stats["Original Clipboard Read For Append"] = f"Failed ({type(e).__name__})"

            if not original:
                stats["Append Action"] = "Normal copy (original clipboard was empty)"
            else:
                payload = new_text
                if args.override_append_wrapping:
                    final_text = original.rstrip('\n') + '\n\n' + payload
                    stats["Append Action"] = "General append after original (override active)"
                else:
                    # Smart append within WHOLE_WRAP if present
                    if _is_whole_wrapped_block(original):
                        inner_orig = _extract_content_from_whole_wrapped_block(original) or ""
                        if mode in ["individual_wrap", "individual_wrap_multi_default"]:
                            inserted = []
                            for piece in payload.split("\n\n"):
                                inserted.append(_extract_payload_from_single_script_generated_block(piece))
                            addition = "\n\n---\n\n".join(inserted)
                        elif mode == "whole_wrap":
                            addition = _extract_content_from_whole_wrapped_block(payload) or payload
                        else:
                            addition = payload

                        sep = "" if not inner_orig.strip() else "\n\n---\n\n"
                        new_inner = inner_orig.rstrip() + sep + addition
                        final_text = f"{WHOLE_WRAP_HEADER_MARKER}\n```\n{new_inner}\n```"

                        # Preserve trailing whitespace if present on original
                        stripped = original.rstrip()
                        if len(original) > len(stripped):
                            final_text += original[len(stripped):]
                        stats["Append Action"] = f"Appended into existing '{WHOLE_WRAP_HEADER_MARKER}' block (smart)"
                    else:
                        final_text = original.rstrip('\n') + '\n\n' + payload
                        stats["Append Action"] = "General append after original (smart / non-whole-wrap original)"

        # Copy
        lines = len(final_text.splitlines()) if final_text else 0
        chars = len(final_text) if final_text else 0
        stats["Lines in Clipboard Payload"] = lines
        stats["Characters in Clipboard Payload"] = chars

        sys_api.set_clipboard(final_text)
        console_err.print(f"[INFO] Attempting to copy to clipboard ({lines} lines, {chars} chars).")
        stats["Clipboard Action Status"] = "Set Succeeded"
        code = 0
    except Exception as e:
        stats["Error"] = f"Unexpected error: {e}"
        console_err.print(f"[bold red][ERROR] {stats['Error']}[/]")
        code = 1
    finally:
        if not args.no_stats:
            _print_stats_table("copy (clip_tools) Statistics", stats)
    return code


def cmd_paste(args, sys_api) -> int:
    stats = {}
    code = 0
    try:
        try:
            clip = sys_api.get_clipboard()
        except NotImplementedError:
            stats["Error"] = "Clipboard get not implemented."
            console_err.print(f"[bold red][ERROR] {stats['Error']}[/]")
            return 1
        except Exception as e:
            stats["Error"] = f"Failed to get clipboard content: {e}"
            console_err.print(f"[bold red][ERROR] {stats['Error']}[/]")
            return 1

        if not clip:
            stats["Status"] = "Clipboard is empty. Aborting."
            console_err.print(stats["Status"], style="bold red")
            return 1

        stats["Clipboard Content"] = f"{len(clip)} chars, {len(clip.splitlines())} lines"

        if args.file is None:
            stats["Operation Mode"] = "Print to stdout"
            sys.stdout.write(clip)
            sys.stdout.flush()
            stats["Chars Printed"] = len(clip)
            stats["Lines Printed"] = len(clip.splitlines())
            code = 0
        else:
            stats["Operation Mode"] = "Replace file content"
            path = Path(args.file)
            stats["File Path"] = str(path.resolve())
            created_new = False
            if not path.exists():
                console_out.print(f"File '{path}' does not exist. Creating new file.")
                stats["File Action"] = "Created new file"
                created_new = True
            else:
                try:
                    original_text = path.read_text(encoding="utf-8")
                    stats["Original Content (approx)"] = f"{len(original_text)} chars, {len(original_text.splitlines())} lines"
                    stats["File Action"] = "Overwritten existing file"
                except Exception as e:
                    stats["Original Content (approx)"] = f"Could not read original for stats: {e}"

            content = clip.rstrip("\n") + "\n"
            with path.open("w", encoding="utf-8") as f:
                written = f.write(content)

            console_out.print(f"Replaced contents of '{path}' with clipboard data.")
            stats["Chars Written"] = written
            stats["Lines Written"] = len(content.splitlines())
            if created_new:
                stats["Note"] = "File was newly created."
            code = 0
    except Exception as e:
        stats["Error"] = f"Unexpected error: {e}"
        console_err.print(f"[bold red][ERROR] {stats['Error']}[/]")
        code = 1
    finally:
        if not args.no_stats:
            # If printing to stdout, direct stats to stderr (to match old behavior).
            _print_stats_table("paste (clip_tools) Statistics", stats, to_stderr=(args.file is None))
    return code


def cmd_run(args, sys_api) -> int:
    stats = {}
    code = 0
    try:
        cmd_str = None
        if args.command_and_args and not (len(args.command_and_args) == 1 and args.command_and_args[0] == "--"):
            stats["Mode"] = "Direct Command Execution"
            cmd_str = " ".join(args.command_and_args)
            stats["Provided Command"] = cmd_str
        elif args.replay_n is not None:
            stats["Mode"] = f"Replay History (N={args.replay_n})"
            if args.replay_n <= 0:
                stats["Error"] = "Value for --replay-history (-r) must be positive."
                console_err.print(f"[bold red][ERROR] {stats['Error']}[/]")
                return 1

            console_err.print(f"[INFO] Attempting to replay history entry N={args.replay_n}...")
            hist = HistoryUtilsAdapter()
            last_cmd = hist.get_nth_recent_command(args.replay_n)
            stats["History Fetch Attempted For N"] = args.replay_n

            if not last_cmd:
                stats["Error"] = f"Failed to retrieve the {args.replay_n}th command from history."
                stats["History Command Found"] = "No"
                console_err.print(f"[bold red][ERROR] {stats['Error']}[/]")
                if hist.shell_type == "unknown":
                    console_err.print("[INFO] Shell type could not be determined. History fetching may be unreliable.")
                return 1

            stats["History Command Found"] = last_cmd
            console_err.print(f"[INFO] Found history command: '{last_cmd}'")

            script_name = Path(sys.argv[0]).name
            script_stem = Path(sys.argv[0]).stem

            parts = last_cmd.split()
            is_self = False
            if parts:
                first = parts[0]
                if first in (script_name, script_stem):
                    is_self = True
                if "python" in first.lower() and any(n in last_cmd for n in (script_name, script_stem)):
                    is_self = True
                if not is_self and any(n in last_cmd for n in (script_name, script_stem)):
                    is_self = True

            if is_self:
                stats["Error"] = f"Loop detected: History entry N={args.replay_n} ('{last_cmd}') is this script. Aborting."
                console_err.print(f"[bold red][WARNING] {stats['Error']}[/]")
                return 1

            try:
                resp = console_err.input(f"[CONFIRM] Re-run: '{last_cmd}'? [Y/n]: ")
            except EOFError:
                console_err.print("[WARNING] No input for confirmation (EOFError). Assuming 'No'.")
                return 0
            except KeyboardInterrupt:
                console_err.print("\n[INFO] User cancelled confirmation (KeyboardInterrupt).")
                return 0

            if resp.lower() == 'y':
                console_err.print(f"[INFO] User approved. Re-running: {last_cmd}")
                cmd_str = last_cmd
            else:
                console_err.print("[INFO] User cancelled re-run.")
                return 0
        else:
            # Default to replay N=1 if no command is given
            stats["Mode"] = "Replay History (N=1, default)"
            args.replay_n = 1
            return cmd_run(args, sys_api)


        if cmd_str is None:
            stats["Error"] = "No command to execute."
            console_err.print("[bold red][ERROR] Internal Error: No command to execute.[/]")
            return 1

        # Execute
        result = subprocess.run(cmd_str, shell=True, capture_output=True, text=True, check=False)
        stats["Command Executed"] = cmd_str
        stats["Command Exit Status"] = result.returncode
        combined = (result.stdout or "") + (result.stderr or "")
        out = combined.strip()
        stats["Stdout Length (raw)"] = len(result.stdout or "")
        stats["Stderr Length (raw)"] = len(result.stderr or "")

        if not out:
            console_out.print(f"Command '{cmd_str}' produced no output to copy.")
            stats["Output Status"] = "Empty"
            stats["Lines Copied"] = 0
            stats["Characters Copied"] = 0
            return 0

        if args.wrap:
            header = f"$ {cmd_str}"
            out = f"{header}\n```\n{out}\n```"
            stats["Wrapping Mode"] = "Wrapped (command + code block)"
        else:
            stats["Wrapping Mode"] = "Raw"

        sys_api.set_clipboard(out)
        console_out.print("Copied command output to clipboard.")
        stats["Output Status"] = "Copied"
        stats["Lines Copied"] = len(out.splitlines())
        stats["Characters Copied"] = len(out)
        if result.returncode != 0:
            console_err.print(f"[yellow][WARNING] Command '{cmd_str}' exited with status {result.returncode}[/]")
        code = 0
    except Exception as e:
        stats["Error"] = f"Unexpected error: {e}"
        console_err.print(f"[bold red]{stats['Error']}[/]")
        code = 1
    finally:
        if not args.no_stats:
            _print_stats_table("run (clip_tools) Statistics", stats, to_stderr=True)
    return code


# =====================================================================================
# Argument parsing / main
# =====================================================================================

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="clip_tools",
        description="Unified clipboard utilities.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # append
    sp = sub.add_parser("append", help="Append clipboard to a file.")
    sp.add_argument("file", help="Target file path.")
    sp.add_argument("--no-stats", "-N", action="store_true", help="Suppress statistics output.")
    sp.set_defaults(func=lambda args, api: cmd_append(args, api))

    # diff
    sp = sub.add_parser("diff", help="Diff clipboard with a file.")
    sp.add_argument("file", help="File to diff against clipboard.")
    sp.add_argument("-c", "--context-lines", type=int, default=3, help="Context lines (default: 3).")
    sp.add_argument("-t", "--similarity-threshold", type=float, default=0.75, help="Similarity threshold (0.0-1.0).")
    sp.add_argument("-L", "--loc-diff-warn", type=int, default=50, help="Warn if LOC difference exceeds this.")
    sp.add_argument("--no-stats", "-N", action="store_true", help="Suppress statistics output.")
    sp.set_defaults(func=lambda args, api: cmd_diff(args, api))

    # replace-block
    sp = sub.add_parser("replace-block", help="Replace a Python def/class in file with clipboard block.")
    sp.add_argument("file", help="Target Python file.")
    sp.add_argument("--no-stats", "-N", action="store_true", help="Suppress statistics output.")
    sp.set_defaults(func=lambda args, api: cmd_replace_block(args, api))

    # copy-buffer
    sp = sub.add_parser("copy-buffer", help="Copy terminal scrollback (tmux) to clipboard.")
    sp.add_argument("-f", "--full", action="store_true", help="Copy the entire scrollback buffer.")
    sp.add_argument("--no-stats", "-N", action="store_true", help="Suppress statistics output.")
    sp.set_defaults(func=lambda args, api: cmd_copy_buffer(args, api))

    # copy-log
    sp = sub.add_parser("copy-log", help="Copy last N lines from current shell session log to clipboard.")
    sp.add_argument("-n", "--lines", type=int, default=10, help="Number of lines to copy (default: 10).")
    sp.add_argument("--no-stats", "-N", action="store_true", help="Suppress statistics output.")
    sp.set_defaults(func=lambda args, api: cmd_copy_log(args, api))

    # copy
    sp = sub.add_parser("copy", help="Copy file(s) to clipboard with flexible wrapping and append options.")
    sp.add_argument("files", nargs="+", help="Path(s) to file(s).")
    fmt = sp.add_mutually_exclusive_group()
    fmt.add_argument("-r", "--raw-copy", action="store_true", help="Copy raw concatenated content.")
    fmt.add_argument("-w", "--wrap", action="store_true", help="Individually wrap each input file.")
    fmt.add_argument("-W", "--whole-wrap", action="store_true", help=f"Wrap all content in one marked block ('{WHOLE_WRAP_HEADER_MARKER}').")
    sp.add_argument("-f", "--show-full-path", action="store_true", help="Include absolute paths in headers (wrap modes).")
    sp.add_argument("-a", "--append", action="store_true", help="Append to existing clipboard content.")
    sp.add_argument("-o", "--override-append-wrapping", action="store_true",
                    help="With -a, append after existing clipboard using the new content's own format (skip smart insert).")
    sp.add_argument("--no-stats", "-N", action="store_true", help="Suppress statistics output.")
    sp.set_defaults(func=lambda args, api: cmd_copy(args, api))

    # paste
    sp = sub.add_parser("paste", help="Replace file with clipboard contents or print clipboard if no file given.")
    sp.add_argument("file", nargs="?", default=None, help="Target file (optional). If omitted, prints to stdout.")
    sp.add_argument("--no-stats", "-N", action="store_true", help="Suppress statistics output.")
    sp.set_defaults(func=lambda args, api: cmd_paste(args, api))

    # run
    sp = sub.add_parser("run", help="Run a command and copy its output to clipboard.")
    sp.add_argument("-r", "--replay-history", type=int, dest="replay_n", default=None,
                    help="Re-run Nth most recent history command (e.g., -r 1).")
    sp.add_argument("-w", "--wrap", action="store_true", help="Wrap the output in a code block headed by the command.")
    sp.add_argument("--no-stats", "-N", action="store_true", help="Suppress statistics output.")
    sp.add_argument("command_and_args", nargs=argparse.REMAINDER,
                    help="Command to execute (prefix with '--' if it begins with '-')")
    sp.set_defaults(func=lambda args, api: cmd_run(args, api))

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    sys_api = RealSysAPI()
    return args.func(args, sys_api)


if __name__ == "__main__":
    sys.exit(main())


# --- Legacy Aliases ---
# apc -> append
# cld -> diff
# crx -> replace-block
# cb2c -> copy-buffer
# cb2cf -> copy-buffer -f
# c2c -> copy
# c2cd -> copy -w
# c2cr -> copy -r
# c2ca -> copy -a
# rwc -> paste
# otc -> run
# otcw -> run -w
# ----------------------
