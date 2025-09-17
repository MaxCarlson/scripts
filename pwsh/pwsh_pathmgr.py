# File: pwsh/pwsh_pathmgr.py
#!/usr/bin/env python3
# pwsh_pathmgr.py (hardened + history + print modes)
# Windows-only PATH manager with backups, diff, validate, add/remove, clean, set-exact, restore.
# Safety rails:
#   - Never write EMPTY PATH (hard abort)
#   - Refuse to SHRINK on add/clean/set-exact/restore unless --force
#   - Back up before any write to ~/PathBackups or PWSH_PATHMGR_BACKUPS
#   - Support --dry-run on mutating subcommands (no backup, no write; show diff)
#   - Mutating ops prompt for confirmation only in interactive TTY; otherwise skip prompt
# Extras:
#   - Print modes: default (numbered + OK/MISS), lines (1 per line), single (joined)
#   - invalid: list only invalid entries (by existence)
#   - remove-invalid: remove all invalid entries
#   - History: first-run snapshot + JSONL journal of changes

import os
import sys
import re
import json
import argparse
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Dict

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

PRINT_MODES = ("default", "lines", "single")
JOURNAL_FILE = BACKUP_DIR / "path_history.jsonl"

def _now_stamp():
    return datetime.now().strftime("%Y%m%d-%H%M%S")

def _ts():
    return datetime.now().isoformat(timespec="seconds")

def _ensure_backup_dir():
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"{COLOR_WARN}[backup]{COLOR_RESET} WARNING: could not create backup dir {BACKUP_DIR}: {e}")

def _journal_append(entry: Dict):
    try:
        _ensure_backup_dir()
        with open(JOURNAL_FILE, "a", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False)
            f.write("\n")
    except Exception as e:
        print(f"{COLOR_WARN}[history]{COLOR_RESET} WARNING: failed to write history: {e}")

def _write_baseline_if_missing(scope: str, current_value: str):
    _ensure_backup_dir()
    baseline_file = BACKUP_DIR / f"baseline-{scope}.json"
    if baseline_file.exists():
        return
    data = {
        "scope": scope,
        "when": _ts(),
        "path_string": current_value,
        "segments": _split_path_string(current_value),
    }
    try:
        with open(baseline_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"{COLOR_WARN}[baseline]{COLOR_RESET} Wrote initial snapshot for {scope} to {baseline_file}")
    except Exception as e:
        print(f"{COLOR_WARN}[baseline]{COLOR_RESET} WARNING: could not write baseline {baseline_file}: {e}")

def _normalize_segments(segments: List[str]) -> List[str]:
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

def _split_path_string(path_str: str) -> List[str]:
    """Split + normalize (dedupe). Used for building and display."""
    if not path_str:
        return []
    cleaned = re.sub(r"[ \t]*;[ \t]*", ";", path_str.replace("\r", "").replace("\n", ""))
    cleaned = re.sub(r";{2,}", ";", cleaned)
    parts = [p for p in cleaned.split(";") if p is not None]
    return _normalize_segments(parts)

def _split_tokens_loose(path_str: str) -> List[str]:
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

def _join_segments(segments: List[str]) -> str:
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

def backup_path(scope: str) -> Path:
    _ensure_backup_dir()
    cur = read_path(scope)
    data = {
        "scope": scope,
        "when": _ts(),
        "path_string": cur,
        "segments": _split_path_string(cur),
    }
    dest = BACKUP_DIR / f"PATH-{scope}-{_now_stamp()}.json"
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"{COLOR_WARN}[backup]{COLOR_RESET} Saved {scope} PATH to {dest}")
    return dest

def print_segments(segs: List[str], *, title="PATH", mode="default"):
    if mode not in PRINT_MODES:
        mode = "default"
    if mode == "single":
        print(_join_segments(segs))
        return
    if mode == "lines":
        for s in segs:
            print(s)
        return
    # default: numbered + OK/MISS
    print(f"\n{title}:")
    if not segs:
        print("  <empty>")
        return
    width = len(str(len(segs)))
    for i, s in enumerate(segs, 1):
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

def get_invalid_segments(segs: List[str]) -> List[str]:
    invalid = []
    for s in segs:
        exp = _expand_for_check(s)
        if not os.path.isdir(exp):
            invalid.append(s)
    return invalid

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

def _confirm(default_no: bool = True) -> bool:
    # Only prompt when stdin is a real TTY; otherwise, auto-decline/accept handled by caller.
    try:
        ans = input("Proceed? [y/N]: " if default_no else "Proceed? [Y/n]: ")
    except EOFError:
        return False
    if not ans:
        return not default_no
    return ans.strip().lower() in ("y", "yes")

def _compute_added_removed(old_str: str, new_str: str) -> Tuple[List[str], List[str]]:
    old = _split_path_string(old_str)
    new = _split_path_string(new_str)
    oldl = {s.lower(): s for s in old}
    newl = {s.lower(): s for s in new}
    added = [newl[k] for k in newl.keys() - oldl.keys()]
    removed = [oldl[k] for k in oldl.keys() - newl.keys()]
    return added, removed

# Safe writer (with confirmation in interactive TTY & history)
def _safe_write_path(scope: str, new_value: str, *, op_hint: str, force: bool, dry_run: bool, assume_yes: bool):
    old = read_path(scope)
    # Create first-run baseline for this scope
    _write_baseline_if_missing(scope, old)

    # Use LOOSE tokens (no dedupe) to detect shrink properly
    old_tokens = _split_tokens_loose(old)
    new_tokens = _split_tokens_loose(new_value)

    # Hard guard: never write empty PATH (after normalization)
    if not _split_path_string(new_value):
        print(f"{COLOR_REM}[abort]{COLOR_RESET} Refusing to write EMPTY PATH for {scope} (op: {op_hint}). No changes made.")
        return

    # Show diff first
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

    # Confirmation only if interactive TTY; skip in non-interactive (pytest/subprocess)
    interactive = bool(getattr(sys.stdin, "isatty", lambda: False)())
    if interactive and not assume_yes and os.environ.get("PWSH_PATHMGR_ASSUME_YES", "").lower() not in ("1", "true", "yes"):
        if not _confirm(default_no=True):
            print(f"{COLOR_WARN}[abort]{COLOR_RESET} User declined to write changes.")
            return

    # Backup
    backup_path(scope)

    # Write
    if scope == PROCESS:
        os.environ["Path"] = new_value
        print(f"{COLOR_OK}[ok]{COLOR_RESET} Updated current process PATH.")
        added, removed = _compute_added_removed(old, new_value)
        _journal_append({"when": _ts(), "scope": scope, "op": op_hint, "added": added, "removed": removed,
                         "new_value": new_value})
        return

    if not IS_WINDOWS:
        raise SystemExit("Registry write is Windows-only.")
    _write_reg_path(scope, new_value)
    _wm_settingchange_broadcast()
    print(f"{COLOR_OK}[ok]{COLOR_RESET} Wrote {scope} PATH.")

    # history entry
    added, removed = _compute_added_removed(old, new_value)
    _journal_append({"when": _ts(), "scope": scope, "op": op_hint, "added": added, "removed": removed,
                     "new_value": new_value})

# Commands
def cmd_show(args):
    s = read_path(args.scope)
    segs = _split_path_string(s)
    print_segments(segs, title=f"{args.scope} PATH", mode=args.mode)

def cmd_validate(args):
    s = read_path(args.scope)
    segs = _split_path_string(s)
    print_segments(segs, title=f"Validate {args.scope} PATH", mode=args.mode)

def cmd_backup(args):
    backup_path(args.scope)

def cmd_restore(args):
    with open(args.file, "r", encoding="utf-8") as f:
        data = json.load(f)
    val = data.get("path_string", "")
    _safe_write_path(args.scope, val, op_hint="restore", force=args.force, dry_run=args.dry_run, assume_yes=args.yes)
    if not args.dry_run:
        print(f"{COLOR_OK}[ok]{COLOR_RESET} Restored {args.scope} PATH from {args.file}")

def cmd_add(args):
    cur = read_path(args.scope)
    new = build_new_string(cur, add=args.paths, cleanup=args.cleanup, dedupe=not args.no_dedupe)
    _safe_write_path(args.scope, new, op_hint="add", force=args.force, dry_run=args.dry_run, assume_yes=args.yes)

def cmd_remove(args):
    cur = read_path(args.scope)
    new = build_new_string(cur, remove=args.paths, cleanup=args.cleanup, dedupe=not args.no_dedupe)
    _safe_write_path(args.scope, new, op_hint="remove", force=args.force, dry_run=args.dry_run, assume_yes=args.yes)

def cmd_clean(args):
    cur = read_path(args.scope)
    new = build_new_string(cur, cleanup=True, dedupe=not args.no_dedupe)
    _safe_write_path(args.scope, new, op_hint="clean", force=args.force, dry_run=args.dry_run, assume_yes=args.yes)

def cmd_set_process(args):
    cur = read_path(PROCESS)
    new = build_new_string(cur, add=args.paths, cleanup=args.cleanup, dedupe=not args.no_dedupe)
    _safe_write_path(PROCESS, new, op_hint="add", force=args.force, dry_run=args.dry_run, assume_yes=args.yes)

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
    _safe_write_path(args.scope, new_val, op_hint="set-exact", force=args.force, dry_run=args.dry_run, assume_yes=args.yes)

def cmd_invalid(args):
    s = read_path(args.scope)
    segs = _split_path_string(s)
    bad = get_invalid_segments(segs)
    if args.mode == "single":
        print(_join_segments(bad))
    elif args.mode == "lines":
        for b in bad:
            print(b)
    else:
        width = len(str(len(bad)))
        print(f"\nInvalid entries in {args.scope} PATH:")
        if not bad:
            print("  <none>")
        else:
            for i, s in enumerate(bad, 1):
                print(f"  {str(i).rjust(width)}. [{COLOR_REM}MISS{COLOR_RESET}] {s}")

def cmd_remove_invalid(args):
    cur = read_path(args.scope)
    segs = _split_path_string(cur)
    bad = get_invalid_segments(segs)
    if not bad:
        print(f"{COLOR_OK}[ok]{COLOR_RESET} No invalid entries found in {args.scope} PATH.")
        return
    new = build_new_string(cur, remove=bad, cleanup=args.cleanup, dedupe=not args.no_dedupe)
    _safe_write_path(args.scope, new, op_hint="remove", force=args.force, dry_run=args.dry_run, assume_yes=args.yes)

# CLI helpers
def _parse_scope(value: str) -> str:
    if not value:
        return USER
    v = value.strip().lower()
    if v in ("u", "user"):
        return USER
    if v in ("m", "machine", "system"):
        return MACHINE
    if v in ("p", "proc", "process"):
        return PROCESS
    if v == USER.lower():
        return USER
    if v == MACHINE.lower():
        return MACHINE
    if v == PROCESS.lower():
        return PROCESS
    raise argparse.ArgumentTypeError(f"Invalid scope: {value}. Use user/machine/process or u/m/p.")

def _add_common_write_flags(p: argparse.ArgumentParser):
    p.add_argument("--dry-run", action="store_true", help="Show what would change; do not write.")
    p.add_argument("--force", "-f", action="store_true",
                   help="Allow shrinking PATH where normally forbidden (add/clean/set-exact/restore).")
    p.add_argument("--yes", "-y", action="store_true", dest="yes",
                   help="Do not prompt for confirmation before writing (interactive sessions only prompt by default).")

def build_parser():
    p = argparse.ArgumentParser(
        description="Windows PATH manager for PowerShell. Safe backups, diffs, validate, add/remove, clean, set-exact, restore."
    )
    p.add_argument("--scope", "-s", type=_parse_scope, default=USER,
                   help="Which PATH to read/modify: user/machine/process or u/m/p (default: user).")
    p.add_argument("--force", "-f", action="store_true",
                   help="Allow shrinking PATH on operations that normally forbid it (add/clean/set-exact/restore).")
    p.add_argument("--yes", "-y", action="store_true", dest="yes",
                   help="Do not prompt for confirmation before writing (interactive sessions only).")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub_show = sub.add_parser("show", help="Show PATH entries.")
    sub_show.add_argument("--mode", choices=PRINT_MODES, default="default",
                          help="Print mode: default (numbered+OK/MISS), lines, single.")
    sub_show.set_defaults(func=cmd_show)

    sub_val = sub.add_parser("validate", help="Validate entries (OK/MISS).")
    sub_val.add_argument("--mode", choices=PRINT_MODES, default="default",
                         help="Print mode: default (numbered+OK/MISS), lines, single.")
    sub_val.set_defaults(func=cmd_validate)

    sub_inv = sub.add_parser("invalid", help="List only invalid/missing entries.")
    sub_inv.add_argument("--mode", choices=PRINT_MODES, default="default",
                         help="Print mode for invalid listing: default (numbered), lines, single.")
    sub_inv.set_defaults(func=cmd_invalid)

    sub_bak = sub.add_parser("backup", help="Backup current PATH to ~/PathBackups (or PWSH_PATHMGR_BACKUPS).")
    sub_bak.set_defaults(func=cmd_backup)

    sub_res = sub.add_parser("restore", help="Restore PATH from a backup JSON.")
    sub_res.add_argument("file", help="Backup JSON file path.")
    _add_common_write_flags(sub_res)
    sub_res.set_defaults(func=cmd_restore)

    sub_add = sub.add_parser("add", help="Add one or more folders to PATH.")
    sub_add.add_argument("paths", nargs="+", help="Folders to add (use quotes if spaces).")
    sub_add.add_argument("--cleanup", action="store_true", help="Also normalize/clean the PATH.")
    sub_add.add_argument("--no-dedupe", action="store_true", help="Do not deduplicate entries.")
    _add_common_write_flags(sub_add)
    sub_add.set_defaults(func=cmd_add)

    sub_rm = sub.add_parser("remove", help="Remove folders from PATH (exact or 'contains:<text>').")
    sub_rm.add_argument("paths", nargs="+",
                        help="Exact path(s) to remove (case-insensitive), or use 'contains:<text>'.")
    sub_rm.add_argument("--cleanup", action="store_true", help="Also normalize/clean the PATH.")
    sub_rm.add_argument("--no-dedupe", action="store_true", help="Do not deduplicate entries.")
    _add_common_write_flags(sub_rm)
    sub_rm.set_defaults(func=cmd_remove)

    sub_clean = sub.add_parser("clean", help="Cleanup PATH: strip newlines/empties, collapse ;;, dedupe.")
    sub_clean.add_argument("--no-dedupe", action="store_true", help="Do not deduplicate entries.")
    _add_common_write_flags(sub_clean)
    sub_clean.set_defaults(func=cmd_clean)

    sub_proc = sub.add_parser("add-process", help="Add to the current session PATH only (no registry write).")
    sub_proc.add_argument("paths", nargs="+", help="Folders to add to this session PATH.")
    sub_proc.add_argument("--cleanup", action="store_true", help="Also normalize/clean the PATH.")
    sub_proc.add_argument("--no-dedupe", action="store_true", help="Do not deduplicate entries.")
    _add_common_write_flags(sub_proc)
    sub_proc.set_defaults(func=cmd_set_process)

    sub_set = sub.add_parser("set-exact", help="Set PATH exactly to provided value or file contents.")
    src = sub_set.add_mutually_exclusive_group(required=True)
    src.add_argument("--value", help="Exact PATH string to write.")
    src.add_argument("--from-file", help="Read exact PATH string from a UTF-8 text file.")
    _add_common_write_flags(sub_set)
    sub_set.set_defaults(func=cmd_set_exact)

    sub_rminv = sub.add_parser("remove-invalid", help="Remove all invalid/missing entries.")
    sub_rminv.add_argument("--cleanup", action="store_true", help="Also normalize/clean the PATH after removal.")
    sub_rminv.add_argument("--no-dedupe", action="store_true", help="Do not deduplicate entries.")
    _add_common_write_flags(sub_rminv)
    sub_rminv.set_defaults(func=cmd_remove_invalid)

    return p

def main():
    if not IS_WINDOWS:
        print("This tool is designed for Windows. Process-scope operations may still work, but registry scopes are Windows-only.")
    args = build_parser().parse_args()

    # Ensure a baseline exists for this scope at least on read
    try:
        cur = read_path(args.scope)
        _write_baseline_if_missing(args.scope, cur)
    except SystemExit:
        pass

    args.func(args)

if __name__ == "__main__":
    main()
