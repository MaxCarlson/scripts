"""Command-line interface for path_manager."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from cross_platform.system_utils import SystemUtils

from . import core

PRINT_MODES = ("default", "lines", "single")

try:
    from colorama import Fore, Style, init as colorama_init

    colorama_init()
    COLOR_RESET = Style.RESET_ALL
    COLOR_BOLD = Style.BRIGHT
    COLOR_DIM = Style.DIM
    COLOR_WARN = Fore.YELLOW
    COLOR_ADD = Fore.GREEN
    COLOR_REM = Fore.RED
    SCOPE_COLORS = {
        core.SCOPE_USER: Fore.CYAN,
        core.SCOPE_MACHINE: Fore.MAGENTA,
        core.SCOPE_PROCESS: Fore.GREEN,
        "Combined": Fore.YELLOW,
    }
except Exception:
    COLOR_RESET = ""
    COLOR_BOLD = ""
    COLOR_DIM = ""
    COLOR_WARN = ""
    COLOR_ADD = ""
    COLOR_REM = ""
    SCOPE_COLORS = {}


def _scope_header(scope: str) -> str:
    color = SCOPE_COLORS.get(scope, "")
    return f"{color}{COLOR_BOLD}{scope} PATH{COLOR_RESET}"


def _term_width() -> int:
    try:
        import shutil

        return shutil.get_terminal_size(fallback=(120, 20)).columns
    except Exception:
        return 120


def _boxed_lines(lines: List[str], *, scope: str) -> List[str]:
    width = _term_width()
    box_width = max(int(width * 0.95), 40)
    label = f"[ {scope} PATH ]"
    max_label = box_width - 4
    if len(label) > max_label:
        label = label[: max_label - 3] + "..."
    pad_len = max(box_width - 2 - len(label), 0)
    color = SCOPE_COLORS.get(scope, "")
    top = f"{color}+{label}{'-' * pad_len}+{COLOR_RESET}"
    bottom = f"{color}+{'-' * (box_width - 2)}+{COLOR_RESET}"

    framed: List[str] = [top]
    for line in lines:
        content = line
        max_content = box_width - 4
        if len(content) > max_content:
            content = content[: max_content - 3] + "..."
        padding = " " * (max_content - len(content))
        framed.append(f"{color}|{COLOR_RESET} {content}{padding} {color}|{COLOR_RESET}")
    framed.append(bottom)
    return framed


def _format_path_list(
    segments: List[str],
    *,
    scope: str,
    mode: str,
    leading_gap: bool = False,
    invalid_set: Optional[set] = None,
) -> None:
    if mode not in PRINT_MODES:
        mode = "default"
    if leading_gap:
        print("\n\n", end="")
    if mode == "single":
        line = core.join_segments(segments)
        if invalid_set:
            line = f"{COLOR_REM}{line}{COLOR_RESET}"
        lines = [line]
        for line in _boxed_lines(lines, scope=scope):
            print(line)
        return
    if mode == "lines":
        lines = []
        if not segments:
            lines = ["<empty>"]
        else:
            for segment in segments:
                if invalid_set and segment in invalid_set:
                    lines.append(f"{COLOR_REM}{segment}{COLOR_RESET}")
                else:
                    lines.append(segment)
        for line in _boxed_lines(lines, scope=scope):
            print(line)
        return
    width = len(str(len(segments)))
    color = SCOPE_COLORS.get(scope, "")
    if not segments:
        lines = ["<empty>"]
    else:
        lines = []
        for idx, segment in enumerate(segments, 1):
            entry_color = COLOR_REM if invalid_set and segment in invalid_set else ""
            lines.append(f"{color}{str(idx).rjust(width)}.{COLOR_RESET} {entry_color}{segment}{COLOR_RESET}")
    for line in _boxed_lines(lines, scope=scope):
        print(line)


def _print_diff(scope: str, old_value: str, new_value: str) -> None:
    added, removed = core.compute_diff(old_value, new_value)
    print(f"\nDiff for {scope} PATH:")
    for segment in core.split_path_string(new_value):
        label = "+" if segment in added else " "
        color = COLOR_ADD if label == "+" else COLOR_DIM
        print(f"  {color}{label} {segment}{COLOR_RESET}")
    for segment in removed:
        print(f"  {COLOR_REM}- {segment}{COLOR_RESET}")


def _add_scope_arg(parser: argparse.ArgumentParser, *, default_scope: str) -> None:
    parser.add_argument(
        "-s",
        "--scope",
        default=default_scope,
        help="Scope: user, machine, process, combined (default varies by command).",
    )


def _add_write_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-n", "--dry-run", dest="dry_run", action="store_true", default=True,
                        help="Show changes; do not write (default).")
    parser.add_argument("-a", "--apply", dest="dry_run", action="store_false",
                        help="Apply changes (disables dry-run).")
    parser.add_argument("-f", "--force", action="store_true", help="Allow shrinking PATH when normally forbidden.")
    parser.add_argument("-y", "--confirm", action="store_true", help="Skip confirmation prompt.")


def _coerce_paths(values: Iterable[str], system: SystemUtils) -> List[str]:
    coerced: List[str] = []
    for raw in values:
        if raw is None:
            continue
        as_dir = core.coerce_to_directory(raw, system=system)
        coerced.append(str(as_dir))
    return coerced


def _get_segments_for_scope(scope: str, system: SystemUtils) -> Tuple[str, List[str]]:
    scope_value = core.resolve_scope(scope)
    if scope_value == "Combined":
        return "Combined", core.get_combined_segments(system=system)
    return scope_value, core.split_path_string(core.read_path(scope_value, system=system), system=system)


def cmd_list(args: argparse.Namespace) -> None:
    system = SystemUtils()
    if args.both:
        if not system.is_windows():
            raise SystemExit("--both is Windows-only.")
        for idx, scope in enumerate((core.SCOPE_USER, core.SCOPE_MACHINE)):
            value = core.read_path(scope, system=system)
            segments = core.split_path_string(value, system=system)
            invalid = set(core.get_invalid_segments(segments, system=system))
            _format_path_list(segments, scope=scope, mode=args.mode, leading_gap=idx > 0, invalid_set=invalid)
        return
    scope_value, segments = _get_segments_for_scope(args.scope, system)
    if scope_value == "Combined" and system.is_windows():
        machine = core.split_path_string(core.read_path(core.SCOPE_MACHINE, system=system), system=system)
        user = core.split_path_string(core.read_path(core.SCOPE_USER, system=system), system=system)
        invalid_machine = set(core.get_invalid_segments(machine, system=system))
        invalid_user = set(core.get_invalid_segments(user, system=system))
        _format_path_list(
            machine,
            scope=core.SCOPE_MACHINE,
            mode=args.mode,
            leading_gap=False,
            invalid_set=invalid_machine,
        )
        _format_path_list(
            user,
            scope=core.SCOPE_USER,
            mode=args.mode,
            leading_gap=True,
            invalid_set=invalid_user,
        )
        return
    invalid = set(core.get_invalid_segments(segments, system=system))
    _format_path_list(segments, scope=scope_value, mode=args.mode, invalid_set=invalid)


def cmd_backup(_args: argparse.Namespace) -> None:
    backup = core.backup_all()
    print(f"Backup saved: {backup}")


def _apply_write(scope: str, new_value: str, *, args: argparse.Namespace, allow_shrink: bool) -> None:
    force_override = args.force
    if args.dry_run and not allow_shrink and not args.force:
        old_value = core.read_path(scope)
        old_tokens = core.split_tokens_loose(old_value)
        new_tokens = core.split_tokens_loose(new_value)
        old_count = sum(1 for t in old_tokens if t)
        new_count = sum(1 for t in new_tokens if t)
        if new_count < old_count:
            print(f"{COLOR_WARN}{COLOR_BOLD}[DRY-RUN]{COLOR_RESET} This change would shrink PATH; apply requires --force.")
            force_override = True
    if args.dry_run:
        print(f"{COLOR_WARN}{COLOR_BOLD}[DRY-RUN]{COLOR_RESET} No changes will be written.")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = core.get_backup_dir()
        print(f"{COLOR_WARN}{COLOR_DIM}Backup would be saved to: {backup_dir / f'PATH-ALL-{stamp}.json'}{COLOR_RESET}")
    result = core.safe_write_path(
        scope,
        new_value,
        dry_run=args.dry_run,
        force=force_override,
        confirm=args.confirm,
        allow_shrink=allow_shrink,
    )
    _print_diff(scope, result.old_value, result.new_value)
    if result.backup_file:
        print(f"Backup saved: {result.backup_file}")
    if args.dry_run:
        print(f"{COLOR_WARN}{COLOR_BOLD}[DRY-RUN]{COLOR_RESET} Done.")


def cmd_add(args: argparse.Namespace) -> None:
    system = SystemUtils()
    scope_value = core.resolve_scope(args.scope)
    if scope_value == "Combined":
        raise SystemExit("Add does not support combined scope.")
    current = core.read_path(scope_value, system=system)
    paths = _coerce_paths(args.paths, system)
    if paths:
        current_segments = core.split_path_string(current, system=system)
        current_index = core.build_command_index(current_segments, system=system)
        for path_str in paths:
            target_dir = Path(path_str)
            execs = core.list_executables_in_dir(target_dir, system=system)
            conflicts = []
            for name_key, candidate_paths in execs.items():
                existing = current_index.get(name_key)
                if existing is None:
                    continue
                conflicts.append((candidate_paths[0].name, existing.paths[0]))
            if conflicts:
                print(f"{COLOR_WARN}{COLOR_BOLD}Warning:{COLOR_RESET} potential command conflicts in {path_str}")
                for name, existing in conflicts:
                    print(f"  - {name} currently resolves to {existing}")
                print(
                    f"{COLOR_WARN}Note:{COLOR_RESET} new PATH entries are appended; existing commands will keep precedence "
                    "unless you promote the new entry."
                )
    new_value = core.build_new_string(
        current,
        add=paths,
        cleanup=args.cleanup,
        dedupe=not args.no_dedupe,
        system=system,
    )
    _apply_write(scope_value, new_value, args=args, allow_shrink=False)


def cmd_remove(args: argparse.Namespace) -> None:
    system = SystemUtils()
    scope_value = core.resolve_scope(args.scope)
    if scope_value == "Combined":
        raise SystemExit("Remove does not support combined scope.")
    current = core.read_path(scope_value, system=system)
    new_value = core.build_new_string(
        current,
        remove=args.paths,
        cleanup=args.cleanup,
        dedupe=not args.no_dedupe,
        system=system,
    )
    _apply_write(scope_value, new_value, args=args, allow_shrink=True)


def cmd_clean(args: argparse.Namespace) -> None:
    system = SystemUtils()
    scope_value = core.resolve_scope(args.scope)
    if scope_value == "Combined":
        raise SystemExit("Clean does not support combined scope.")
    current = core.read_path(scope_value, system=system)
    new_value = core.build_new_string(current, cleanup=True, dedupe=not args.no_dedupe, system=system)
    _apply_write(scope_value, new_value, args=args, allow_shrink=False)


def cmd_invalid(args: argparse.Namespace) -> None:
    system = SystemUtils()
    scope_value, segments = _get_segments_for_scope(args.scope, system)
    invalid = core.get_invalid_segments(segments, system=system)
    _format_path_list(invalid, scope=scope_value, mode=args.mode, invalid_set=set(invalid))


def cmd_remove_invalid(args: argparse.Namespace) -> None:
    system = SystemUtils()
    scope_value = core.resolve_scope(args.scope)
    if scope_value == "Combined":
        raise SystemExit("Remove-invalid does not support combined scope.")
    current = core.read_path(scope_value, system=system)
    segments = core.split_path_string(current, system=system)
    invalid = core.get_invalid_segments(segments, system=system)
    if not invalid:
        print(f"No invalid entries found in {scope_value} PATH.")
        return
    new_value = core.build_new_string(
        current,
        remove=invalid,
        cleanup=args.cleanup,
        dedupe=not args.no_dedupe,
        system=system,
    )
    _apply_write(scope_value, new_value, args=args, allow_shrink=True)


def cmd_restore(args: argparse.Namespace) -> None:
    system = SystemUtils()
    backup_path = Path(args.input)
    if not backup_path.is_file():
        raise SystemExit(f"Backup not found: {backup_path}")
    scopes = core.load_backup(backup_path)

    target_scope = core.resolve_scope(args.scope) if args.scope else None
    if target_scope == "Combined":
        raise SystemExit("Restore does not support combined scope.")

    if target_scope:
        if target_scope not in scopes:
            raise SystemExit(f"Scope {target_scope} not present in backup.")
        value = scopes[target_scope].get("path_string", "")
        _apply_write(target_scope, value, args=args, allow_shrink=False)
        return

    for scope_key, payload in scopes.items():
        value = payload.get("path_string", "")
        _apply_write(scope_key, value, args=args, allow_shrink=False)


def cmd_check(args: argparse.Namespace) -> None:
    system = SystemUtils()
    scope_value, segments = _get_segments_for_scope(args.scope, system)
    print(_scope_header(scope_value))
    target_dir = core.coerce_to_directory(args.target, system=system)
    target_str = str(target_dir)

    normalized_segments = [core.expand_path(s) for s in segments]
    target_expanded = core.expand_path(target_str)

    already = False
    for seg in normalized_segments:
        seg_expanded = core.expand_path(seg)
        if system.is_windows():
            if seg_expanded.lower() == target_expanded.lower():
                already = True
                break
        else:
            if seg_expanded == target_expanded:
                already = True
                break

    print(f"Target: {args.target}")
    print(f"Directory: {target_str}")
    print(f"Scope: {scope_value}")
    print(f"Already on PATH: {'yes' if already else 'no'}")

    index = core.build_command_index(segments, system=system)
    target_execs = core.list_executables_in_dir(target_dir, system=system)

    added = []
    shadowed = []
    for name_key, paths in target_execs.items():
        current = index.get(name_key)
        if current is None:
            added.append(paths[0].name)
        else:
            shadowed.append((paths[0].name, current.paths[0]))

    if added:
        print("\nNew commands added:")
        for item in sorted(set(added), key=str.lower):
            print(f"  + {item}")
    else:
        print("\nNew commands added: <none>")

    if shadowed:
        print("\nCommands already resolved earlier:")
        for name, existing in shadowed:
            print(f"  - {name} (current: {existing})")


def cmd_duplicates(args: argparse.Namespace) -> None:
    system = SystemUtils()
    scope_value, segments = _get_segments_for_scope(args.scope, system)
    print(_scope_header(scope_value))
    index = core.build_command_index(segments, system=system)

    if args.command:
        key = args.command.lower() if system.is_windows() else args.command
        record = index.get(key)
        if not record:
            print(f"No matches for '{args.command}' in {scope_value} PATH.")
            return
        print(f"{record.name} resolves in this order:")
        for path in record.paths:
            print(f"  - {path}")
        return

    dupes = {name: rec for name, rec in index.items() if len(rec.paths) > 1}
    if not dupes:
        print(f"No duplicates found in {scope_value} PATH.")
        return
    for name in sorted(dupes.keys()):
        record = dupes[name]
        print(f"\n{record.name} resolves in this order:")
        for path in record.paths:
            print(f"  - {path}")


def _move_segment(segments: List[str], target: str, *, to_front: bool, system: SystemUtils) -> List[str]:
    key = core._segment_key(target, system)
    filtered = [s for s in segments if core._segment_key(s, system) != key]
    insert_at = 0 if to_front else max(len(filtered) - 1, 0)
    filtered.insert(insert_at, target)
    return filtered


def cmd_promote(args: argparse.Namespace) -> None:
    system = SystemUtils()
    scope_value = core.resolve_scope(args.scope)
    if scope_value == "Combined":
        raise SystemExit("Promote does not support combined scope.")
    current_value = core.read_path(scope_value, system=system)
    segments = core.split_path_string(current_value, system=system)

    if args.path:
        target_dir = core.coerce_to_directory(args.path, system=system)
    else:
        index = core.build_command_index(segments, system=system)
        key = args.command.lower() if system.is_windows() else args.command
        record = index.get(key)
        if not record:
            raise SystemExit(f"Command '{args.command}' not found in PATH.")
        target_dir = record.paths[0].parent

    target_str = str(target_dir)
    if core._segment_key(target_str, system) not in {core._segment_key(s, system) for s in segments}:
        raise SystemExit(f"{target_str} is not currently on PATH for {scope_value}.")

    to_front = not args.to_end
    new_segments = _move_segment(segments, target_str, to_front=to_front, system=system)
    if args.dedupe:
        new_segments = core.normalize_segments(new_segments, system)

    changes = core.analyze_resolution_changes(segments, new_segments, system=system)
    if changes:
        print("Resolution changes:")
        for name in sorted(changes.keys()):
            before, after = changes[name]
            print(f"  * {name}: {before} -> {after}")
    else:
        print("No resolution changes detected.")

    new_value = core.join_segments(new_segments, system=system)
    _apply_write(scope_value, new_value, args=args, allow_shrink=not args.dedupe)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PATH manager with backups, validation, and ordering tools.")
    sub = parser.add_subparsers(dest="command", required=True)

    list_cmd = sub.add_parser("list", help="List PATH entries.")
    _add_scope_arg(list_cmd, default_scope="user")
    list_cmd.add_argument("-m", "--mode", choices=PRINT_MODES, default="default", help="Output format.")
    list_cmd.add_argument("-b", "--both", action="store_true", help="Show user + machine separately (Windows-only).")
    list_cmd.set_defaults(func=cmd_list)

    backup_cmd = sub.add_parser("backup", help="Backup all PATH scopes to JSON.")
    backup_cmd.set_defaults(func=cmd_backup)

    restore_cmd = sub.add_parser("restore", help="Restore PATH from a backup JSON.")
    restore_cmd.add_argument("-i", "--input", required=True, help="Backup JSON file.")
    _add_scope_arg(restore_cmd, default_scope="")
    _add_write_flags(restore_cmd)
    restore_cmd.set_defaults(func=cmd_restore)

    add_cmd = sub.add_parser("add", help="Add folders to PATH.")
    _add_scope_arg(add_cmd, default_scope="user")
    add_cmd.add_argument("-p", "--paths", nargs="+", required=True, help="Paths to add.")
    add_cmd.add_argument("-c", "--cleanup", action="store_true", help="Normalize PATH while adding.")
    add_cmd.add_argument("-d", "--no-dedupe", action="store_true", help="Do not deduplicate entries.")
    _add_write_flags(add_cmd)
    add_cmd.set_defaults(func=cmd_add)

    remove_cmd = sub.add_parser("remove", help="Remove folders from PATH.")
    _add_scope_arg(remove_cmd, default_scope="user")
    remove_cmd.add_argument("-p", "--paths", nargs="+", required=True, help="Paths to remove or contains:<text>.")
    remove_cmd.add_argument("-c", "--cleanup", action="store_true", help="Normalize PATH after removal.")
    remove_cmd.add_argument("-d", "--no-dedupe", action="store_true", help="Do not deduplicate entries.")
    _add_write_flags(remove_cmd)
    remove_cmd.set_defaults(func=cmd_remove)

    clean_cmd = sub.add_parser("clean", help="Normalize and dedupe PATH.")
    _add_scope_arg(clean_cmd, default_scope="user")
    clean_cmd.add_argument("-d", "--no-dedupe", action="store_true", help="Do not deduplicate entries.")
    _add_write_flags(clean_cmd)
    clean_cmd.set_defaults(func=cmd_clean)

    invalid_cmd = sub.add_parser("invalid", help="List invalid PATH entries.")
    _add_scope_arg(invalid_cmd, default_scope="user")
    invalid_cmd.add_argument("-m", "--mode", choices=PRINT_MODES, default="default", help="Output format.")
    invalid_cmd.set_defaults(func=cmd_invalid)

    remove_invalid_cmd = sub.add_parser("remove-invalid", help="Remove invalid PATH entries.")
    _add_scope_arg(remove_invalid_cmd, default_scope="user")
    remove_invalid_cmd.add_argument("-c", "--cleanup", action="store_true", help="Normalize PATH after removal.")
    remove_invalid_cmd.add_argument("-d", "--no-dedupe", action="store_true", help="Do not deduplicate entries.")
    _add_write_flags(remove_invalid_cmd)
    remove_invalid_cmd.set_defaults(func=cmd_remove_invalid)

    check_cmd = sub.add_parser("check", help="Analyze a path or executable against PATH.")
    _add_scope_arg(check_cmd, default_scope="combined")
    check_cmd.add_argument("-t", "--target", required=True, help="Path or executable to analyze.")
    check_cmd.set_defaults(func=cmd_check)

    dup_cmd = sub.add_parser("duplicates", help="List commands that resolve from multiple PATH entries.")
    _add_scope_arg(dup_cmd, default_scope="combined")
    dup_cmd.add_argument("-c", "--command", help="Check a single command name.")
    dup_cmd.set_defaults(func=cmd_duplicates)

    promote_cmd = sub.add_parser("promote", help="Move a PATH entry earlier to change resolution order.")
    _add_scope_arg(promote_cmd, default_scope="user")
    promote_cmd.add_argument("-c", "--command", required=True, help="Command name to promote.")
    promote_cmd.add_argument("-p", "--path", help="Specific path entry to promote.")
    promote_cmd.add_argument("-n", "--dry-run", dest="dry_run", action="store_true", default=True,
                             help="Show changes; do not write (default).")
    promote_cmd.add_argument("-a", "--apply", dest="dry_run", action="store_false",
                             help="Apply changes (disables dry-run).")
    promote_cmd.add_argument("-e", "--to-end", action="store_true", help="Move entry to the end of PATH.")
    promote_cmd.add_argument("-d", "--dedupe", action="store_true", help="Deduplicate PATH entries while promoting.")
    promote_cmd.add_argument("-f", "--force", action="store_true", help="Allow shrinking PATH when deduping.")
    promote_cmd.add_argument("-y", "--confirm", action="store_true", help="Skip confirmation prompt.")
    promote_cmd.set_defaults(func=cmd_promote)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
