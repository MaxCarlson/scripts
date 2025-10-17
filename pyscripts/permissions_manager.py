#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
perm_manager.py — Standalone, cross-platform Permissions Manager CLI

This script is a self-contained CLI tool (lives OUTSIDE the cross_platform package)
that imports utilities from your existing cross_platform module. It supports:

Subcommands
- view: Show permissions for a path (normalized + raw).
- diff: Compare permissions between a source template and one or more targets.
- copy: Copy permissions from source -> target (optionally recursive, dry-run).
- audit-drift: Detect where permissions deviate within a tree (vs. root or provided template).
- set: Apply a preset permission set (Windows/Posix catalogs in cross_platform).
- presets: List built-in presets with descriptions.
- export: Save a template from a source to JSON for reuse.
- import-apply: Load a saved template and apply to target(s).
- win-noninherit: (Windows) List items with inheritance disabled (heuristic).

Key Behaviors
- Dry-run (-n/--dry-run): prints a permissions-diff of what would change (no writes).
- Recursive depth (-r/--recursive-depth): 0 = target only, 1 = target + direct children, etc.
- Ownership overrides: --owner/-o and --group/-g (group is POSIX only).
- Windows: toggle inheritance with --disable-inheritance/-i or --enable-inheritance/-e.
- Privilege preflight: before write operations, uses cross_platform.PrivilegesManager to
  assess elevation/tooling needs and surface actionable errors (without silently elevating).

Environment
- Works in Windows (PowerShell 7+), WSL2/Ubuntu, and Android Termux (where tools exist).
- Degrades gracefully when ACL tools (icacls/getfacl/setfacl) are unavailable.

Examples
    # View
    python tools/perm_manager.py view -p "C:\\Data"
    python tools/perm_manager.py view -p ./somefile --json

    # Diff one source vs multiple targets
    python tools/perm_manager.py diff -s ./src_perm -t ./dst1 ./dst2

    # Copy with dry-run, depth 2
    python tools/perm_manager.py copy -s ./src -t ./dst -r 2 -n

    # Audit drift under a root
    python tools/perm_manager.py audit-drift -p ./root -r 3

    # Apply a preset
    python tools/perm_manager.py set -p ./folder --preset posix-750-team

    # Export/import
    python tools/perm_manager.py export -s ./src_perm -o ./templates/src_perm.json
    python tools/perm_manager.py import-apply -i ./templates/src_perm.json -t ./dst -n
"""

from __future__ import annotations

import argparse
import json
import os
import getpass
from pathlib import Path
from typing import Iterable

# Import from your cross_platform module (provided separately by you)
from cross_platform.debug_utils import write_debug, print_parsed_args
from cross_platform.system_utils import SystemUtils
from cross_platform.privileges_manager import PrivilegesManager
from cross_platform.permissions_utils import (
    read_permissions,
    diff_permissions,
    apply_permissions,
    save_template,
    load_template,
    scan_drift,
    list_non_inheriting_windows,
    PermissionsTemplate,
    PermissionsUtils,
)
from cross_platform.permissions_presets import list_presets, get_preset


# ---------- helpers ----------

def iter_with_depth(root: Path, max_depth: int, follow_symlinks: bool) -> Iterable[Path]:
    return PermissionsUtils().iter_with_depth(root, max_depth, follow_symlinks)


def format_diff(diff: dict) -> str:
    lines: list[str] = []
    lines.append(f"Backend: {diff.get('backend')}")
    if diff.get("mode_change"):
        lines.append(f"  mode: {diff['mode_change']}")
    if diff.get("owner_change"):
        lines.append(f"  owner: {diff['owner_change']}")
    if diff.get("group_change"):
        lines.append(f"  group: {diff['group_change']}")
    added = diff.get("added") or []
    removed = diff.get("removed") or []
    if added:
        lines.append("  + add:")
        for a in added:
            lines.append(f"    + {a}")
    if removed:
        lines.append("  - remove:")
        for r in removed:
            lines.append(f"    - {r}")
    if len(lines) == 1:
        lines.append("  (no changes)")
    return "\n".join(lines)


def current_user_windows() -> str | None:
    try:
        domain = os.environ.get("USERDOMAIN")
        user = os.environ.get("USERNAME") or getpass.getuser()
        if domain and user:
            return f"{domain}\\{user}"
        return user
    except Exception:
        return None


def _inheritance_flag(su: SystemUtils, args) -> bool | None:
    if not su.is_windows():
        return None
    if getattr(args, "disable_inheritance", False) and getattr(args, "enable_inheritance", False):
        write_debug("Both --disable-inheritance and --enable-inheritance set; ignoring both.", channel="Warning")
        return None
    if getattr(args, "disable_inheritance", False):
        return True
    if getattr(args, "enable_inheritance", False):
        return False
    return None


def _preflight_permissions(pm: PrivilegesManager, target: Path, *, will_change_owner: bool, will_change_group: bool,
                           will_change_mode: bool, will_change_acl: bool) -> None:
    """
    Use PrivilegesManager to check elevation/tooling needs before writes.
    Raises PermissionError with actionable message if prerequisites are missing.
    """
    pm.ensure_or_explain_permissions(
        target,
        will_change_owner=will_change_owner,
        will_change_group=will_change_group,
        will_change_mode=will_change_mode,
        will_change_acl=will_change_acl,
        auto_elevate_windows=False,  # do not silently elevate; surface guidance instead
    )


# ---------- CLI ----------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Standalone Cross-platform Permissions Manager (imports cross_platform.*)",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument("-v", "--verbose", "-V", action="store_true", help="Verbose output")
    sub = p.add_subparsers(dest="cmd", required=True)

    # view
    sp = sub.add_parser("view", help="View permissions for a path")
    sp.add_argument("-p", "--path", "-P", required=True)
    sp.add_argument("-j", "--json", "-J", action="store_true", help="JSON output")

    # diff
    sp = sub.add_parser("diff", help="Diff permissions of one or more targets against a source")
    sp.add_argument("-s", "--source", "-S", required=True)
    sp.add_argument("-t", "--targets", "-T", nargs="+", required=True)
    sp.add_argument("-j", "--json", "-J", action="store_true", help="JSON output")

    # copy
    sp = sub.add_parser("copy", help="Copy permissions from source to target (optionally recursive)")
    sp.add_argument("-s", "--source", "-S", required=True)
    sp.add_argument("-t", "--target", "-T", required=True)
    sp.add_argument("-r", "--recursive-depth", "-R", type=int, default=0)
    sp.add_argument("-l", "--follow-symlinks", "-L", action="store_true")
    sp.add_argument("-n", "--dry-run", "-N", action="store_true")
    sp.add_argument("-c", "--clear-existing", "-C", action="store_true")
    sp.add_argument("-x", "--no-acl", "-X", action="store_true")
    sp.add_argument("-o", "--owner", default=None)
    sp.add_argument("-g", "--group", default=None)
    sp.add_argument("-i", "--disable-inheritance", action="store_true")
    sp.add_argument("-e", "--enable-inheritance", action="store_true")

    # audit-drift
    sp = sub.add_parser("audit-drift", help="Report where folder permissions deviate within a tree")
    sp.add_argument("-p", "--path", "-P", required=True, help="Root path to audit")
    sp.add_argument("-r", "--recursive-depth", "-R", type=int, default=1)
    sp.add_argument("-l", "--follow-symlinks", "-L", action="store_true")
    sp.add_argument("-s", "--source-template", "-S", default=None, help="Optional source path to use as reference")

    # set (presets)
    sp = sub.add_parser("set", help="Apply a preset permission set to a path")
    sp.add_argument("-p", "--path", "-P", required=True)
    sp.add_argument("--preset", "-z", required=True, help="Preset id (see 'presets' subcommand)")
    sp.add_argument("-r", "--recursive-depth", "-R", type=int, default=0)
    sp.add_argument("-l", "--follow-symlinks", "-L", action="store_true")
    sp.add_argument("-n", "--dry-run", "-N", action="store_true")
    sp.add_argument("-o", "--owner", default=None, help="Override owner (optional)")
    sp.add_argument("-g", "--group", default=None, help="Override group (POSIX)")
    sp.add_argument("-i", "--disable-inheritance", action="store_true")
    sp.add_argument("-e", "--enable-inheritance", action="store_true")

    # presets (listing)
    sp = sub.add_parser("presets", help="List built-in presets")
    sp.add_argument("-j", "--json", "-J", action="store_true", help="JSON output")

    # export
    sp = sub.add_parser("export", help="Capture permissions to a JSON template")
    sp.add_argument("-s", "--source", "-S", required=True)
    sp.add_argument("-o", "--output", "-O", required=True)

    # import-apply
    sp = sub.add_parser("import-apply", help="Apply a saved JSON template to target(s)")
    sp.add_argument("-i", "--input", "-I", required=True)
    sp.add_argument("-t", "--targets", "-T", nargs="+", required=True)
    sp.add_argument("-r", "--recursive-depth", "-R", type=int, default=0)
    sp.add_argument("-l", "--follow-symlinks", "-L", action="store_true")
    sp.add_argument("-n", "--dry-run", "-N", action="store_true")
    sp.add_argument("-c", "--clear-existing", "-C", action="store_true")
    sp.add_argument("-x", "--no-acl", "-X", action="store_true")
    sp.add_argument("-o", "--owner", default=None)
    sp.add_argument("-g", "--group", default=None)
    sp.add_argument("-i", "--disable-inheritance", action="store_true")
    sp.add_argument("-e", "--enable-inheritance", action="store_true")

    # win-noninherit
    sp = sub.add_parser("win-noninherit", help="(Windows) List items with ACL inheritance disabled")
    sp.add_argument("-p", "--path", "-P", required=True)
    sp.add_argument("-r", "--recursive-depth", "-R", type=int, default=1)
    sp.add_argument("-l", "--follow-symlinks", "-L", action="store_true")

    return p


# ---------- subcommand handlers ----------

def cmd_view(args) -> int:
    t = read_permissions(args.path)
    if args.json:
        data = PermissionsUtils().to_dict(t)
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        print(f"Path: {args.path}")
        print(f"Backend: {t.backend}")
        if t.mode is not None:
            print(f"Mode: {oct(t.mode)}")
        if t.owner:
            print(f"Owner: {t.owner}")
        if t.group:
            print(f"Group: {t.group}")
        if t.payload:
            print("Payload:")
            print("~~~")
            print(t.payload)
            print("~~~")
    return 0


def cmd_diff(args) -> int:
    src_t = read_permissions(args.source)
    out = []
    for tgt in args.targets:
        d = diff_permissions(src_t, tgt)
        out.append({"target": tgt, "diff": d})
    if args.json:
        print(json.dumps(out, indent=2, sort_keys=True))
    else:
        for item in out:
            print(f"[DIFF] {item['target']}")
            print(format_diff(item["diff"]))
            print()
    return 0


def cmd_copy(args) -> int:
    src = Path(args.source).resolve()
    tgt = Path(args.target).resolve()
    if not src.exists() or not tgt.exists():
        write_debug("Source or target does not exist.", channel="Error")
        return 2

    su = SystemUtils()
    pm = PrivilegesManager()

    template = read_permissions(str(src))

    if args.dry_run:
        for p in iter_with_depth(tgt, args.recursive_depth, args.follow_symlinks):
            d = diff_permissions(template, str(p))
            print(f"[DRY-RUN DIFF] {p}")
            print(format_diff(d))
            print()
        return 0

    # Preflight once on the target root (heuristic for subtree)
    try:
        _preflight_permissions(
            pm,
            tgt,
            will_change_owner=bool(args.owner),
            will_change_group=bool(args.group),
            will_change_mode=(template.mode is not None),
            will_change_acl=not args.no_acl,
        )
    except PermissionError as e:
        write_debug(str(e), channel="Error")
        return 3

    inh = _inheritance_flag(su, args)
    changed = 0
    for p in iter_with_depth(tgt, args.recursive_depth, args.follow_symlinks):
        try:
            apply_permissions(
                template, str(p),
                clear_existing=args.clear_existing,
                owner=args.owner,
                group=args.group,
                no_acl=args.no_acl,
                disable_inheritance=inh,
            )
            changed += 1
        except Exception as e:
            write_debug(f"Apply failed for {p}: {e}", channel="Error")
    write_debug(f"Applied permissions to {changed} path(s).", channel="Success" if changed else "Warning")
    return 0


def cmd_audit_drift(args) -> int:
    root = Path(args.path).resolve()
    if not root.exists():
        write_debug("Path does not exist.", channel="Error")
        return 2

    ref = read_permissions(args.source_template) if args.source_template else None
    diffs = scan_drift(str(root), reference=ref, max_depth=args.recursive_depth, follow_symlinks=bool(args.follow_symlinks))
    if not diffs:
        print("No drift detected.")
        return 0

    for rel, d in diffs:
        print(f"[DRIFT] {rel}")
        print(format_diff(d))
        print()
    return 0


def cmd_set(args) -> int:
    su = SystemUtils()
    pm = PrivilegesManager()
    preset = get_preset(args.preset)
    if not preset:
        write_debug(f"Unknown preset '{args.preset}'. See 'presets' subcommand.", channel="Error")
        return 2

    path = Path(args.path).resolve()
    if not path.exists():
        write_debug("Path does not exist.", channel="Error")
        return 2

    pu = PermissionsUtils()
    # Build a template from the preset for the current platform
    if su.is_windows() and "windows" in preset["platforms"]:
        base = read_permissions(str(path))
        win = preset["windows"]
        grants = list(win.get("grants", []))
        # Replace CURRENT_USER placeholder if present
        if any("CURRENT_USER" in g for g in grants):
            cu = current_user_windows()
            grants = [g.replace("CURRENT_USER", cu) if cu else g for g in grants]
        payload = "\n".join(grants)
        tmpl = PermissionsTemplate(
            backend="windows_icacls",
            payload=payload,
            mode=None,
            owner=args.owner or win.get("owner") or base.owner,
            group=None,
            source_kind="dir" if path.is_dir() else "file",
            meta={"preset": preset["id"], "title": preset["title"]},
        )
        if args.dry_run:
            for p in iter_with_depth(path, args.recursive_depth, args.follow_symlinks):
                d = diff_permissions(tmpl, str(p))
                print(f"[DRY-RUN DIFF] {p}")
                print(format_diff(d))
                print()
            return 0

        # Preflight
        try:
            _preflight_permissions(
                pm,
                path,
                will_change_owner=bool(tmpl.owner),
                will_change_group=False,
                will_change_mode=False,
                will_change_acl=True,
            )
        except PermissionError as e:
            write_debug(str(e), channel="Error")
            return 3

        inh = _inheritance_flag(su, args)
        applied = 0
        for p in iter_with_depth(path, args.recursive_depth, args.follow_symlinks):
            apply_permissions(tmpl, str(p), clear_existing=True,
                              owner=tmpl.owner, no_acl=False, disable_inheritance=inh)
            applied += 1
        write_debug(f"Preset '{preset['id']}' applied to {applied} path(s).", channel="Success")
        return 0

    elif (su.is_linux() or su.is_macos()) and "posix" in preset["platforms"]:
        pos = preset["posix"]
        base = read_permissions(str(path))
        tmpl = PermissionsTemplate(
            backend="posix_acl" if (pos.get("acl")) else "posix_mode",
            payload=pos.get("acl") or "",
            mode=pos.get("mode", base.mode),
            owner=args.owner or pos.get("owner") or base.owner,
            group=args.group or pos.get("group") or base.group,
            source_kind="dir" if path.is_dir() else "file",
            meta={"preset": preset["id"], "title": preset["title"]},
        )
        if args.dry_run:
            for p in iter_with_depth(path, args.recursive_depth, args.follow_symlinks):
                d = diff_permissions(tmpl, str(p))
                print(f"[DRY-RUN DIFF] {p}")
                print(format_diff(d))
                print()
            return 0

        # Preflight
        try:
            _preflight_permissions(
                pm,
                path,
                will_change_owner=bool(tmpl.owner),
                will_change_group=bool(tmpl.group),
                will_change_mode=bool(tmpl.mode is not None),
                will_change_acl=bool(tmpl.backend == "posix_acl"),
            )
        except PermissionError as e:
            write_debug(str(e), channel="Error")
            return 3

        applied = 0
        for p in iter_with_depth(path, args.recursive_depth, args.follow_symlinks):
            apply_permissions(tmpl, str(p), clear_existing=True, owner=tmpl.owner, group=tmpl.group, no_acl=False)
            applied += 1
        write_debug(f"Preset '{preset['id']}' applied to {applied} path(s).", channel="Success")
        return 0

    else:
        write_debug("Preset does not match this platform.", channel="Error")
        return 2


def cmd_presets(args) -> int:
    pres = list_presets()
    if args.json:
        print(json.dumps(pres, indent=2, sort_keys=True))
    else:
        for p in pres:
            print(f"{p['id']}: {p['title']}")
            print(f"  Platforms: {', '.join(p['platforms'])}")
            print(f"  {p['description']}")
            print()
    return 0


def cmd_export(args) -> int:
    t = read_permissions(args.source)
    save_template(t, args.output)
    write_debug(f"Template saved to {args.output}", channel="Success")
    return 0


def cmd_import_apply(args) -> int:
    su = SystemUtils()
    pm = PrivilegesManager()
    tmpl = load_template(args.input)

    # Preflight once per target root before writes
    will_change_owner = bool(args.owner or tmpl.owner)
    will_change_group = bool(args.group or tmpl.group)
    will_change_mode = bool(tmpl.mode is not None)
    will_change_acl = not args.no_acl

    for tgt in args.targets:
        path = Path(tgt).resolve()
        if not path.exists():
            write_debug(f"Target not found: {path}", channel="Warning")
            continue

        if args.dry_run:
            for p in iter_with_depth(path, args.recursive_depth, args.follow_symlinks):
                d = diff_permissions(tmpl, str(p))
                print(f"[DRY-RUN DIFF] {p}")
                print(format_diff(d))
                print()
            continue

        try:
            _preflight_permissions(
                pm,
                path,
                will_change_owner=will_change_owner,
                will_change_group=will_change_group,
                will_change_mode=will_change_mode,
                will_change_acl=will_change_acl,
            )
        except PermissionError as e:
            write_debug(str(e), channel="Error")
            continue

        inh = _inheritance_flag(su, args)
        for p in iter_with_depth(path, args.recursive_depth, args.follow_symlinks):
            apply_permissions(
                tmpl, str(p),
                clear_existing=args.clear_existing,
                owner=args.owner or tmpl.owner,
                group=args.group or tmpl.group,
                no_acl=args.no_acl,
                disable_inheritance=inh,
            )
    write_debug("Import-apply completed.", channel="Success")
    return 0


def cmd_win_noninherit(args) -> int:
    su = SystemUtils()
    if not su.is_windows():
        write_debug("This command is Windows-only.", channel="Error")
        return 2
    items = list_non_inheriting_windows(args.path, max_depth=args.recursive_depth, follow_symlinks=bool(args.follow_symlinks))
    if not items:
        print("All items appear to have inherited ACEs.")
        return 0
    for s in items:
        print(s)
    return 0


# ---------- main ----------

def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    print_parsed_args(args)
    if getattr(args, "verbose", False):
        write_debug("Verbose mode enabled.", channel="Debug")

    cmd = args.cmd
    if cmd == "view":
        return cmd_view(args)
    if cmd == "diff":
        return cmd_diff(args)
    if cmd == "copy":
        return cmd_copy(args)
    if cmd == "audit-drift":
        return cmd_audit_drift(args)
    if cmd == "set":
        return cmd_set(args)
    if cmd == "presets":
        return cmd_presets(args)
    if cmd == "export":
        return cmd_export(args)
    if cmd == "import-apply":
        return cmd_import_apply(args)
    if cmd == "win-noninherit":
        return cmd_win_noninherit(args)

    write_debug(f"Unknown command '{cmd}'", channel="Error")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
