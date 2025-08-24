#!/usr/bin/env python3
# pwsh_pathmgr.py
# Windows-only PATH manager with backups, diff, validate, add/remove, clean.
# Safe-by-default: every mutating action creates a timestamped backup.

import os
import sys
import re
import json
import argparse
from datetime import datetime
from pathlib import Path

# --- Windows-only imports (guarded) ---
IS_WINDOWS = (os.name == "nt")
if IS_WINDOWS:
    import winreg
    import ctypes
    import ctypes.wintypes as wt

# --- Optional color support ---
try:
    from colorama import init as colorama_init, Fore, Style
    colorama_init()
    COLOR_OK = Fore.GREEN
    COLOR_REM = Fore.RED
    COLOR_SAME = Style.DIM
    COLOR_WARN = Fore.YELLOW
    COLOR_RESET = Style.RESET_ALL
except Exception:
    # Fallback: no color
    COLOR_OK = COLOR_REM = COLOR_SAME = COLOR_WARN = COLOR_RESET = ""

# ---------- Constants ----------
HKCU_ENV = r"Environment"
HKLM_ENV = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
BACKUP_DIR = Path.home() / "PathBackups"
USER = "User"
MACHINE = "Machine"
PROCESS = "Process"

# ---------- Utilities ----------
def _now_stamp():
    return datetime.now().strftime("%Y%m%d-%H%M%S")

def _normalize_segments(segments):
    """Trim whitespace, drop empties, collapse internal newlines, keep order; no trailing-backslash stripping."""
    out = []
    seen_norm = set()
    for seg in segments:
        if seg is None:
            continue
        s = str(seg).replace("\r", "").replace("\n", "")
        s = s.strip().strip('"').strip()  # strip quotes/space noise
        if not s:
            continue
        # For dedupe comparisons, normalize case only (do NOT strip trailing '\')
        key = s.lower()
        if key in seen_norm:
            continue
        seen_norm.add(key)
        out.append(s)
    return out

def _split_path_string(path_str: str):
    if not path_str:
        return []
    # Replace newlines, collapse repeated semicolons
    cleaned = re.sub(r"[ \t]*;[ \t]*", ";", path_str.replace("\r", "").replace("\n", ""))
    cleaned = re.sub(r";{2,}", ";", cleaned)
    parts = [p for p in cleaned.split(";") if p is not None]
    return _normalize_segments(parts)

def _join_segments(segments):
    return ";".join(segments)

def _expand_for_check(seg: str) -> str:
    # Expand %VAR% and ~
    s = os.path.expandvars(seg)
    s = os.path.expanduser(s)
    return s

def _wm_settingchange_broadcast():
    """Tell Windows that environment changed so new processes see it."""
    # Best-effort; safe to skip if anything fails.
    try:
        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        SMTO_ABORTIFHUNG = 0x0002
        SendMessageTimeout = ctypes.windll.user32.SendMessageTimeoutW
        SendMessageTimeout.argtypes = [
            wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, wt.UINT, wt.UINT, ctypes.POINTER(wt.DWORD)
        ]
        result = wt.DWORD(0)
        SendMessageTimeout(HWND_BROADCAST, WM_SETTINGCHANGE, 0, ctypes.c_wchar_p("Environment"),
                           SMTO_ABORTIFHUNG, 5000, ctypes.byref(result))
    except Exception:
        pass

def _read_reg_path(scope: str) -> str:
    if scope == USER:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, HKCU_ENV, 0, winreg.KEY_READ) as k:
            try:
                val, typ = winreg.QueryValueEx(k, "Path")
                return val
            except FileNotFoundError:
                return ""
    elif scope == MACHINE:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, HKLM_ENV, 0, winreg.KEY_READ) as k:
            try:
                val, typ = winreg.QueryValueEx(k, "Path")
                return val
            except FileNotFoundError:
                return ""
    else:
        raise ValueError("Invalid scope for registry read")

def _write_reg_path(scope: str, path_str: str):
    # Always write as EXPAND_SZ to preserve %VAR% usage
    if scope == USER:
        root, sub = winreg.HKEY_CURRENT_USER, HKCU_ENV
    elif scope == MACHINE:
        root, sub = winreg.HKEY_LOCAL_MACHINE, HKLM_ENV
    else:
        raise ValueError("Invalid scope for registry write")
    with winreg.OpenKey(root, sub, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "Path", 0, winreg.REG_EXPAND_SZ, path_str)

def read_path(scope: str) -> str:
    if scope == PROCESS:
        return os.environ.get("Path") or os.environ.get("PATH") or ""
    if not IS_WINDOWS:
        raise SystemExit("This tool is Windows-only for User/Machine operations.")
    return _read_reg_path(scope)

def write_path(scope: str, new_value: str, do_backup: bool = True, dry_run: bool = False):
    if scope == PROCESS:
        # Process scope change (session-only)
        if do_backup:
            backup_path(scope)  # backup the current process PATH string
        if not dry_run:
            os.environ["Path"] = new_value
        return

    if do_backup:
        backup_path(scope)

    if dry_run:
        return

    _write_reg_path(scope, new_value)
    _wm_settingchange_broadcast()

def backup_path(scope: str) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    cur = read_path(scope)
    data = {
        "scope": scope,
        "when": datetime.now().isoformat(),
        "path_string": cur,
        "segments": _split_path_string(cur),
    }
    dest = BACKUP_DIR / f"PATH-{scope}-{_now_stamp()}.json"
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"{COLOR_WARN}[backup]{COLOR_RESET} Saved {scope} PATH to {dest}")
    return dest

def restore_from(file_path: Path, scope: str):
    p = Path(file_path)
    if not p.is_file():
        raise SystemExit(f"Backup not found: {p}")
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    src_scope = data.get("scope", scope)
    if scope not in (USER, MACHINE, PROCESS):
        raise SystemExit("Invalid target scope")
    val = data.get("path_string", "")
    if not isinstance(val, str):
        raise SystemExit("Invalid backup content")
    print_diff(scope, read_path(scope), val)
    write_path(scope, val, do_backup=True, dry_run=False)
    print(f"{COLOR_OK}[ok]{COLOR_RESET} Restored {scope} PATH from {p}")

def print_segments(segments, title="PATH"):
    print(f"\n{title}:")
    if not segments:
        print("  <empty>")
        return
    width = len(str(len(segments)))
    for i, s in enumerate(segments, 1):
        exp = _expand_for_check(s)
        exists = os.path.isdir(exp)
        badge = f"{COLOR_OK}OK{COLOR_RESET}" if exists else f"{COLOR_REM}MISS{COLOR_RESET}"
        print(f"  {str(i).rjust(width)}. [{badge}] {s}")

def print_diff(scope: str, old_str: str, new_str: str):
    old = _split_path_string(old_str)
    new = _split_path_string(new_str)
    # Build a stable order diff: walk through union keeping new order and then any removed trailing
    old_set = {s.lower(): s for s in old}
    new_set = {s.lower(): s for s in new}

    print(f"\nDiff for {scope} PATH:")
    # Show items in the order they will appear (new)
    for s in new:
        key = s.lower()
        if key not in old_set:
            print(f"  {COLOR_OK}+ {s}{COLOR_RESET}")
        else:
            print(f"    {COLOR_SAME}{s}{COLOR_RESET}")
    # Show removed ones at the end
    for s in old:
        key = s.lower()
        if key not in new_set:
            print(f"  {COLOR_REM}- {s}{COLOR_RESET}")

def build_new_string(base_str: str, add=None, remove=None, cleanup=False, dedupe=True):
    segs = _split_path_string(base_str)
    if cleanup:
        # cleanup already handled by _split_path_string normalization
        pass
    if remove:
        # support exact path remove (case-insensitive) OR substring match with '::contains::'
        to_remove = []
        for r in remove:
            r = r.strip()
            if not r:
                continue
            if r.startswith("~"):
                r = os.path.expanduser(r)
            # mark operator: contains: pattern
            if r.startswith("contains:"):
                needle = r.split(":", 1)[1].strip().lower()
                to_remove.extend([s for s in segs if needle in s.lower()])
            else:
                # exact (case-insensitive)
                to_remove.extend([s for s in segs if s.lower() == r.lower()])
        if to_remove:
            segs = [s for s in segs if s not in to_remove]

    if add:
        for a in add:
            a = a.strip().strip('"')
            if not a:
                continue
            if a.startswith("~"):
                a = os.path.expanduser(a)
            # Do not normalize trailing '\', keep user’s exact input form
            # but avoid duplicate (case-insensitive)
            if a.lower() not in [s.lower() for s in segs]:
                segs.append(a)

    if dedupe:
        segs = _normalize_segments(segs)

    return _join_segments(segs)

# ---------- Commands ----------
def cmd_show(args):
    s = read_path(args.scope)
    segs = _split_path_string(s)
    print_segments(segs, title=f"{args.scope} PATH")

def cmd_validate(args):
    s = read_path(args.scope)
    segs = _split_path_string(s)
    print_segments(segs, title=f"Validate {args.scope} PATH")

def cmd_backup(args):
    backup_path(args.scope)

def cmd_restore(args):
    restore_from(Path(args.file), args.scope)

def cmd_add(args):
    cur = read_path(args.scope)
    new = build_new_string(cur, add=args.paths, cleanup=args.cleanup, dedupe=not args.no_dedupe)
    print_diff(args.scope, cur, new)
    if args.dry_run:
        print(f"{COLOR_WARN}[dry-run]{COLOR_RESET} No changes written.")
        return
    write_path(args.scope, new, do_backup=True, dry_run=False)
    print(f"{COLOR_OK}[ok]{COLOR_RESET} Added entries to {args.scope} PATH.")

def cmd_remove(args):
    cur = read_path(args.scope)
    new = build_new_string(cur, remove=args.paths, cleanup=args.cleanup, dedupe=not args.no_dedupe)
    print_diff(args.scope, cur, new)
    if args.dry_run:
        print(f"{COLOR_WARN}[dry-run]{COLOR_RESET} No changes written.")
        return
    write_path(args.scope, new, do_backup=True, dry_run=False)
    print(f"{COLOR_OK}[ok]{COLOR_RESET} Removed entries from {args.scope} PATH.")

def cmd_clean(args):
    cur = read_path(args.scope)
    new = build_new_string(cur, cleanup=True, dedupe=not args.no_dedupe)
    print_diff(args.scope, cur, new)
    if args.dry_run:
        print(f"{COLOR_WARN}[dry-run]{COLOR_RESET} No changes written.")
        return
    write_path(args.scope, new, do_backup=True, dry_run=False)
    print(f"{COLOR_OK}[ok]{COLOR_RESET} Cleaned {args.scope} PATH.")

def cmd_set_process(args):
    # Quick helper: immediately add to current session PATH only.
    cur = read_path(PROCESS)
    new = build_new_string(cur, add=args.paths, cleanup=args.cleanup, dedupe=not args.no_dedupe)
    print_diff(PROCESS, cur, new)
    if args.dry_run:
        print(f"{COLOR_WARN}[dry-run]{COLOR_RESET} No changes written (process).")
        return
    write_path(PROCESS, new, do_backup=True, dry_run=False)
    print(f"{COLOR_OK}[ok]{COLOR_RESET} Updated current process PATH.")

# ---------- CLI ----------
def build_parser():
    p = argparse.ArgumentParser(
        description="Windows PATH manager for PowerShell. Safe backups, diffs, validate, add/remove, clean."
    )
    p.add_argument("--scope", choices=[USER, MACHINE, PROCESS], default=USER,
                   help="Which PATH to read/modify (default: User).")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub_show = sub.add_parser("show", help="Show PATH entries (with OK/MISS).")
    sub_show.set_defaults(func=cmd_show)

    sub_val = sub.add_parser("validate", help="Validate entries exist (OK/MISS).")
    sub_val.set_defaults(func=cmd_validate)

    sub_bak = sub.add_parser("backup", help="Backup current PATH to ~/PathBackups.")
    sub_bak.set_defaults(func=cmd_backup)

    sub_res = sub.add_parser("restore", help="Restore PATH from a backup JSON.")
    sub_res.add_argument("file", help="Backup JSON file path.")
    sub_res.set_defaults(func=cmd_restore)

    sub_add = sub.add_parser("add", help="Add one or more folders to PATH.")
    sub_add.add_argument("paths", nargs="+", help="Folders to add (use quotes if spaces).")
    sub_add.add_argument("--cleanup", action="store_true", help="Also normalize/clean the PATH.")
    sub_add.add_argument("--no-dedupe", action="store_true", help="Do not deduplicate entries.")
    sub_add.add_argument("--dry-run", action="store_true", help="Show diff only; do not write.")
    sub_add.set_defaults(func=cmd_add)

    sub_rm = sub.add_parser("remove", help="Remove folders from PATH (exact or 'contains:<text>').")
    sub_rm.add_argument("paths", nargs="+",
                        help="Exact path(s) to remove (case-insensitive), or use 'contains:<text>'.")
    sub_rm.add_argument("--cleanup", action="store_true", help="Also normalize/clean the PATH.")
    sub_rm.add_argument("--no-dedupe", action="store_true", help="Do not deduplicate entries.")
    sub_rm.add_argument("--dry-run", action="store_true", help="Show diff only; do not write.")
    sub_rm.set_defaults(func=cmd_remove)

    sub_clean = sub.add_parser("clean", help="Cleanup PATH: strip newlines/empties, collapse ;;, dedupe.")
    sub_clean.add_argument("--no-dedupe", action="store_true", help="Do not deduplicate entries.")
    sub_clean.add_argument("--dry-run", action="store_true", help="Show diff only; do not write.")
    sub_clean.set_defaults(func=cmd_clean)

    sub_proc = sub.add_parser("add-process", help="Add to the current session PATH only (no registry write).")
    sub_proc.add_argument("paths", nargs="+", help="Folders to add to this session PATH.")
    sub_proc.add_argument("--cleanup", action="store_true", help="Also normalize/clean the PATH.")
    sub_proc.add_argument("--no-dedupe", action="store_true", help="Do not deduplicate entries.")
    sub_proc.add_argument("--dry-run", action="store_true", help="Show diff only; do not write.")
    sub_proc.set_defaults(func=cmd_set_process)

    return p

def main():
    if not IS_WINDOWS:
        print("This tool is designed for Windows. Process-scope operations may still work, but registry scopes are Windows-only.")
    args = build_parser().parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
