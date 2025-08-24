# File: pwsh/pwsh_pathmgr.py
#!/usr/bin/env python3
# pwsh_pathmgr.py (hardened)
# Windows-only PATH manager with backups, diff, validate, add/remove, clean, set-exact, restore.
# Safety rails:
#   - Never write EMPTY PATH (hard abort)
#   - Refuse to SHRINK on add/clean/set-exact/restore unless --force
#   - Back up before any write to ~/PathBackups or PWSH_PATHMGR_BACKUPS
#   - Support --dry-run on mutating subcommands (no backup, no write; show diff)

import os
import sys
import re
import json
import argparse
from datetime import datetime
from pathlib import Path

IS_WINDOWS = (os.name == "nt")
if IS_WINDOWS:
    import winreg
    import ctypes
    import ctypes.wintypes as wt

# Color (optional)
try:
    from colorama import init as colorama_init, Fore, Style
    colorama_init()
    COLOR_OK = Fore.GREEN
    COLOR_REM = Fore.RED
    COLOR_SAME = Style.DIM
    COLOR_WARN = Fore.YELLOW
    COLOR_RESET = Style.RESET_ALL
except Exception:
    COLOR_OK = COLOR_REM = COLOR_SAME = COLOR_WARN = COLOR_RESET = ""

# Constants
HKCU_ENV = r"Environment"
HKLM_ENV = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
BACKUP_DIR = Path(os.environ.get("PWSH_PATHMGR_BACKUPS", str(Path.home() / "PathBackups")))
USER = "User"
MACHINE = "Machine"
PROCESS = "Process"

# Utils
def _now_stamp():
    return datetime.now().strftime("%Y%m%d-%H%M%S")

def _normalize_segments(segments):
    """Trim whitespace/quotes, drop empties, dedupe (case-insensitive), keep first occurrence."""
    out, seen = [], set()
    for seg in segments:
        if seg is None:
            continue
        s = str(seg).replace("\r", "").replace("\n", "")
        s = s.strip().strip('"').strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out

def _split_path_string(path_str: str):
    """Split + normalize (dedupe). Used for building and display."""
    if not path_str:
        return []
    cleaned = re.sub(r"[ \t]*;[ \t]*", ";", path_str.replace("\r", "").replace("\n", ""))
    cleaned = re.sub(r";{2,}", ";", cleaned)
    parts = [p for p in cleaned.split(";") if p is not None]
    return _normalize_segments(parts)

def _split_tokens_loose(path_str: str):
    """
    Split but DO NOT dedupe. Trim whitespace/quotes. Keep empty tokens as '' so
    we can accurately detect shrink caused by cleanup/dedupe.
    """
    if path_str is None:
        return []
    s = path_str.replace("\r", "").replace("\n", "")
    parts = s.split(";")
    tokens = []
    for p in parts:
        t = p.strip().strip('"').strip()
        tokens.append(t)  # preserve empties as ''
    return tokens

def _join_segments(segments):
    return ";".join(segments)

def _expand_for_check(seg: str) -> str:
    return os.path.expanduser(os.path.expandvars(seg))

def _wm_settingchange_broadcast():
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
                val, _ = winreg.QueryValueEx(k, "Path")
                return val
            except FileNotFoundError:
                return ""
    elif scope == MACHINE:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, HKLM_ENV, 0, winreg.KEY_READ) as k:
            try:
                val, _ = winreg.QueryValueEx(k, "Path")
                return val
            except FileNotFoundError:
                return ""
    else:
        raise ValueError("Invalid scope for registry read")

def _write_reg_path(scope: str, path_str: str):
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

def _ensure_backup_dir():
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"{COLOR_WARN}[backup]{COLOR_RESET} WARNING: could not create backup dir {BACKUP_DIR}: {e}")

def backup_path(scope: str) -> Path:
    _ensure_backup_dir()
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
    old_set = {s.lower(): s for s in old}
    new_set = {s.lower(): s for s in new}

    print(f"\nDiff for {scope} PATH:")
    for s in new:
        if s.lower() not in old_set:
            print(f"  {COLOR_OK}+ {s}{COLOR_RESET}")
        else:
            print(f"    {COLOR_SAME}{s}{COLOR_RESET}")
    for s in old:
        if s.lower() not in new_set:
            print(f"  {COLOR_REM}- {s}{COLOR_RESET}")

def build_new_string(base_str: str, add=None, remove=None, cleanup=False, dedupe=True):
    segs = _split_path_string(base_str)
    # cleanup effects already applied by _split_path_string
    if remove:
        to_remove = []
        for r in remove:
            r = r.strip()
            if not r:
                continue
            if r.startswith("~"):
                r = os.path.expanduser(r)
            if r.startswith("contains:"):
                needle = r.split(":", 1)[1].strip().lower()
                to_remove.extend([s for s in segs if needle in s.lower()])
            else:
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
            if a.lower() not in [s.lower() for s in segs]:
                segs.append(a)

    if dedupe:
        segs = _normalize_segments(segs)
    return _join_segments(segs)

# Safe writer
def _safe_write_path(scope: str, new_value: str, *, op_hint: str, force: bool, dry_run: bool):
    old = read_path(scope)
    # Use LOOSE tokens (no dedupe) to detect shrink properly (e.g., duplicates/empties removed)
    old_tokens = _split_tokens_loose(old)
    new_tokens = _split_tokens_loose(new_value)

    # Hard guard: never write empty PATH (after normalization)
    if not _split_path_string(new_value):
        print(f"{COLOR_REM}[abort]{COLOR_RESET} Refusing to write EMPTY PATH for {scope} (op: {op_hint}). No changes made.")
        return

    # Show diff first for clarity
    print_diff(scope, old, new_value)

    # For these ops, shrinking requires --force (but never abort on dry-run)
    if not force and op_hint in ("add", "clean", "set-exact", "restore"):
        old_cnt = sum(1 for t in old_tokens if t != "")
        new_cnt = sum(1 for t in new_tokens if t != "")
        if new_cnt < old_cnt:
            if dry_run:
                print(f"{COLOR_WARN}[dry-run]{COLOR_RESET} Would shrink PATH (requires --force to actually write). No changes written.")
                return
            print(f"{COLOR_REM}[abort]{COLOR_RESET} New PATH has fewer entries than current for {scope} during '{op_hint}'. Use --force to allow.")
            return

    if dry_run:
        print(f"{COLOR_WARN}[dry-run]{COLOR_RESET} No changes written.")
        return

    backup_path(scope)

    if scope == PROCESS:
        os.environ["Path"] = new_value
        print(f"{COLOR_OK}[ok]{COLOR_RESET} Updated current process PATH.")
        return

    if not IS_WINDOWS:
        raise SystemExit("Registry write is Windows-only.")
    _write_reg_path(scope, new_value)
    _wm_settingchange_broadcast()
    print(f"{COLOR_OK}[ok]{COLOR_RESET} Wrote {scope} PATH.")

# Commands
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
    with open(args.file, "r", encoding="utf-8") as f:
        data = json.load(f)
    val = data.get("path_string", "")
    _safe_write_path(args.scope, val, op_hint="restore", force=args.force, dry_run=args.dry_run)
    if not args.dry_run:
        print(f"{COLOR_OK}[ok]{COLOR_RESET} Restored {args.scope} PATH from {args.file}")

def cmd_add(args):
    cur = read_path(args.scope)
    new = build_new_string(cur, add=args.paths, cleanup=args.cleanup, dedupe=not args.no_dedupe)
    _safe_write_path(args.scope, new, op_hint="add", force=args.force, dry_run=args.dry_run)

def cmd_remove(args):
    cur = read_path(args.scope)
    new = build_new_string(cur, remove=args.paths, cleanup=args.cleanup, dedupe=not args.no_dedupe)
    _safe_write_path(args.scope, new, op_hint="remove", force=args.force, dry_run=args.dry_run)

def cmd_clean(args):
    cur = read_path(args.scope)
    new = build_new_string(cur, cleanup=True, dedupe=not args.no_dedupe)
    _safe_write_path(args.scope, new, op_hint="clean", force=args.force, dry_run=args.dry_run)

def cmd_set_process(args):
    cur = read_path(PROCESS)
    new = build_new_string(cur, add=args.paths, cleanup=args.cleanup, dedupe=not args.no_dedupe)
    _safe_write_path(PROCESS, new, op_hint="add", force=args.force, dry_run=args.dry_run)

def cmd_set_exact(args):
    if args.value is None and args.from_file is None:
        raise SystemExit("Provide --value or --from-file.")
    if args.value is not None:
        new_val = args.value
    else:
        p = Path(args.from_file)
        if not p.is_file():
            raise SystemExit(f"--from-file not found: {p}")
        new_val = p.read_text(encoding="utf-8")
    _safe_write_path(args.scope, new_val, op_hint="set-exact", force=args.force, dry_run=args.dry_run)

# CLI
def build_parser():
    p = argparse.ArgumentParser(
        description="Windows PATH manager for PowerShell. Safe backups, diffs, validate, add/remove, clean, set-exact, restore."
    )
    p.add_argument("--scope", choices=[USER, MACHINE, PROCESS], default=USER,
                   help="Which PATH to read/modify (default: User).")
    # Keep global --force for compatibility (when placed before subcommand)
    p.add_argument("--force", action="store_true",
                   help="Allow shrinking PATH on operations that normally forbid it (add/clean/set-exact/restore).")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub_show = sub.add_parser("show", help="Show PATH entries (with OK/MISS).")
    sub_show.set_defaults(func=cmd_show)

    sub_val = sub.add_parser("validate", help="Validate entries exist (OK/MISS).")
    sub_val.set_defaults(func=cmd_validate)

    sub_bak = sub.add_parser("backup", help="Backup current PATH to ~/PathBackups (or PWSH_PATHMGR_BACKUPS).")
    sub_bak.set_defaults(func=cmd_backup)

    sub_res = sub.add_parser("restore", help="Restore PATH from a backup JSON.")
    sub_res.add_argument("file", help="Backup JSON file path.")
    sub_res.add_argument("--dry-run", action="store_true", help="Show what would change; do not write.")
    sub_res.add_argument("--force", action="store_true", help="Allow shrinking when restoring.")
    sub_res.set_defaults(func=cmd_restore)

    sub_add = sub.add_parser("add", help="Add one or more folders to PATH.")
    sub_add.add_argument("paths", nargs="+", help="Folders to add (use quotes if spaces).")
    sub_add.add_argument("--cleanup", action="store_true", help="Also normalize/clean the PATH.")
    sub_add.add_argument("--no-dedupe", action="store_true", help="Do not deduplicate entries.")
    sub_add.add_argument("--dry-run", action="store_true", help="Show what would change; do not write.")
    sub_add.add_argument("--force", action="store_true", help="Allow shrinking if cleanup/dedupe reduces entries.")
    sub_add.set_defaults(func=cmd_add)

    sub_rm = sub.add_parser("remove", help="Remove folders from PATH (exact or 'contains:<text>').")
    sub_rm.add_argument("paths", nargs="+",
                        help="Exact path(s) to remove (case-insensitive), or use 'contains:<text>'.")
    sub_rm.add_argument("--cleanup", action="store_true", help="Also normalize/clean the PATH.")
    sub_rm.add_argument("--no-dedupe", action="store_true", help="Do not deduplicate entries.")
    sub_rm.add_argument("--dry-run", action="store_true", help="Show what would change; do not write.")
    sub_rm.add_argument("--force", action="store_true", help="Allow shrinking if cleanup/dedupe reduces entries.")
    sub_rm.set_defaults(func=cmd_remove)

    sub_clean = sub.add_parser("clean", help="Cleanup PATH: strip newlines/empties, collapse ;;, dedupe.")
    sub_clean.add_argument("--no-dedupe", action="store_true", help="Do not deduplicate entries.")
    sub_clean.add_argument("--dry-run", action="store_true", help="Show what would change; do not write.")
    sub_clean.add_argument("--force", action="store_true", help="Allow shrinking if cleanup/dedupe reduces entries.")
    sub_clean.set_defaults(func=cmd_clean)

    sub_proc = sub.add_parser("add-process", help="Add to the current session PATH only (no registry write).")
    sub_proc.add_argument("paths", nargs="+", help="Folders to add to this session PATH.")
    sub_proc.add_argument("--cleanup", action="store_true", help="Also normalize/clean the PATH.")
    sub_proc.add_argument("--no-dedupe", action="store_true", help="Do not deduplicate entries.")
    sub_proc.add_argument("--dry-run", action="store_true", help="Show what would change; do not write.")
    sub_proc.add_argument("--force", action="store_true", help="Allow shrinking if cleanup/dedupe reduces entries.")
    sub_proc.set_defaults(func=cmd_set_process)

    sub_set = sub.add_parser("set-exact", help="Set PATH exactly to provided value or file contents.")
    src = sub_set.add_mutually_exclusive_group(required=True)
    src.add_argument("--value", help="Exact PATH string to write.")
    src.add_argument("--from-file", help="Read exact PATH string from a UTF-8 text file.")
    sub_set.add_argument("--dry-run", action="store_true", help="Show what would change; do not write.")
    sub_set.add_argument("--force", action="store_true", help="Allow shrinking when setting exact value.")
    sub_set.set_defaults(func=cmd_set_exact)

    return p

def main():
    if not IS_WINDOWS:
        print("This tool is designed for Windows. Process-scope operations may still work, but registry scopes are Windows-only.")
    args = build_parser().parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
