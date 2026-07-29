from __future__ import annotations

import argparse
import dataclasses as dc
import os
import sys
from typing import Sequence

from . import __version__
from .config import BackupSet, Settings, load_config, platform_config_default
from .config_cli import (
    config_add_set_command,
    config_init_command,
    config_list_sets_command,
    config_remove_set_command,
    config_retention_command,
    config_set_command,
    config_show_command,
    config_wizard_command,
)
from .runner import (
    RunError,
    list_snapshots,
    repo_stats,
    run_check,
    run_forget_prune,
    show_in_progress,
    start_backup,
)
from .setup_wizard import run_setup_wizard


CLI_CONFIGURATION_ERROR_EXIT = 2


def _epilog() -> str:
    default_cfg = platform_config_default()
    return (
        "Examples:\n"
        "  rrb --config ~/.config/rrbackup/config.toml list\n"
        "  rrb -c %APPDATA%/rrbackup/config.toml backup --set daily\n"
        "  rrb backup --set local-c && rrb prune && rrb stats\n"
        "\n"
        f"Default config path: {default_cfg}\n"
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rrb",
        description="Restic + Rclone backup CLI",
        epilog=_epilog(),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument("--version", "-V", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--config", "-c", help="Path to config TOML (overrides RRBACKUP_CONFIG/env & defaults)")
    p.add_argument("--verbose", "-v", action="store_true", help="Enable verbose CLI info (not restic verbosity)")

    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("setup", help="Initialize the restic repository (requires configured credentials).")
    sp.add_argument("--password-file", "-p", help="Optional override RESTIC_PASSWORD_FILE path for init")
    sp.add_argument("--remote-check", "-r", action="store_true", help="Run a remote accessibility check via restic unlock")
    sp.add_argument("--wizard", "-w", action="store_true", help="Launch the interactive setup wizard.")
    sp.set_defaults(func=cmd_setup)

    sp = sub.add_parser("list", help="List snapshots.")
    sp.add_argument("--path", "-P", action="append", help="Filter by path (repeatable)")
    sp.add_argument("--tag", "-t", action="append", help="Filter by tag (repeatable)")
    sp.add_argument("--host", "-H", help="Filter by host")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("backup", help="Run backup for a configured backup set.")
    sp.add_argument("--set", "-s", required=True, help="Backup set name from config.toml")
    sp.add_argument("--dry-run", "-n", action="store_true", help="Force dry-run for this invocation")
    sp.add_argument("--tag", "-t", action="append", help="Additional tag(s)")
    sp.add_argument("--exclude", "-e", action="append", help="Additional exclude(s)")
    sp.add_argument("--extra", "-x", action="append", help="Raw extra args for restic (repeatable)")
    sp.set_defaults(func=cmd_backup)

    sp = sub.add_parser("stats", help="Show repo stats (restore-size).")
    sp.set_defaults(func=cmd_stats)

    sp = sub.add_parser("check", help="Run restic check.")
    sp.set_defaults(func=cmd_check)

    sp = sub.add_parser("prune", help="Apply retention policy (forget --prune).")
    sp.set_defaults(func=cmd_prune)

    sp = sub.add_parser("progress", help="Show in-progress rrbackup tasks and restic locks.")
    sp.set_defaults(func=cmd_progress)

    sp = sub.add_parser("config", help="Manage rrbackup configuration files.")
    sp.add_argument("--path", "-p", help="Config path override (takes precedence over --config/env/default).")
    cfg_sub = sp.add_subparsers(dest="config_cmd", required=True)

    cp = cfg_sub.add_parser("init", help="Create a new configuration with default values.")
    cp.add_argument("--force", "-f", action="store_true", help="Overwrite an existing file if present.")
    cp.set_defaults(func=config_init_command)

    cp = cfg_sub.add_parser("wizard", help="Interactive setup wizard to create a configuration.")
    cp.add_argument("--force", "-f", action="store_true", help="Overwrite an existing file if present.")
    cp.add_argument("--initialize-repo", "-i", action="store_true", help="Run restic init after saving the config.")
    cp.set_defaults(func=config_wizard_command)

    cp = cfg_sub.add_parser("show", help="Display the configuration as TOML.")
    cp.add_argument("--effective", "-e", action="store_true", help="Show expanded values with defaults applied.")
    cp.set_defaults(func=config_show_command)

    cp = cfg_sub.add_parser("list-sets", help="List configured backup sets.")
    cp.set_defaults(func=config_list_sets_command)

    cp = cfg_sub.add_parser("add-set", help="Add a backup set to the configuration.")
    cp.add_argument("--name", "-n", required=True, help="Name of the backup set.")
    cp.add_argument("--include", "-i", action="append", required=True, help="Path to include (repeatable).")
    cp.add_argument("--exclude", "-e", action="append", help="Exclude glob pattern (repeatable).")
    cp.add_argument("--tag", "-t", action="append", help="Tag to apply to the set (repeatable).")
    cp.add_argument("--one-fs", "-o", action="store_true", help="Enable restic --one-file-system.")
    cp.add_argument("--dry-run-default", "-d", action="store_true", help="Enable dry-run by default.")
    cp.add_argument("--schedule", "-S", help="Human-friendly schedule description for this set.")
    cp.add_argument("--backup-type", "-B", default="incremental", help="Backup type descriptor (default: incremental).")
    cp.add_argument(
        "--max-snapshots",
        "-M",
        type=int,
        help="Override snapshots to retain for this set (blank uses global retention).",
    )
    cp.add_argument("--encryption", "-E", help="Encryption notes for this set.")
    cp.add_argument("--compression", "-C", help="Compression preference for this set.")
    cp.set_defaults(func=config_add_set_command)

    cp = cfg_sub.add_parser("remove-set", help="Remove a backup set from the configuration.")
    cp.add_argument("--name", "-n", required=True, help="Name of the backup set to remove.")
    cp.set_defaults(func=config_remove_set_command)

    cp = cfg_sub.add_parser("set", help="Update repository, binary, or directory settings.")
    cp.add_argument("--repo-url", "-r", help="Restic repository URL.")
    cp.add_argument("--password-file", "-P", help="Path to restic password file (blank to clear).")
    cp.add_argument("--password-env", "-E", help="Environment variable with restic password (blank to clear).")
    cp.add_argument("--restic-bin", "-R", help="restic binary name or path.")
    cp.add_argument("--rclone-bin", "-C", help="rclone binary name or path.")
    cp.add_argument("--state-dir", "-S", help="State directory for logs/PID files (blank to use default).")
    cp.add_argument("--log-dir", "-L", help="Log directory (blank to use default).")
    cp.set_defaults(func=config_set_command)

    cp = cfg_sub.add_parser("retention", help="Update retention policy settings.")
    cp.add_argument("--keep-last", "-L", type=int, help="Number of latest snapshots to keep.")
    cp.add_argument("--keep-hourly", "-H", type=int, help="Hourly snapshots to keep.")
    cp.add_argument("--keep-daily", "-D", type=int, help="Daily snapshots to keep.")
    cp.add_argument("--keep-weekly", "-W", type=int, help="Weekly snapshots to keep.")
    cp.add_argument("--keep-monthly", "-M", type=int, help="Monthly snapshots to keep.")
    cp.add_argument("--keep-yearly", "-Y", type=int, help="Yearly snapshots to keep.")
    cp.add_argument("--max-total-size", "-Z", help="Maximum total repository size (e.g., 512GB).")
    cp.add_argument("--clear", "-X", action="store_true", help="Clear all retention values.")
    cp.add_argument("--use-defaults", "-u", action="store_true", help="Reset to default retention policy.")
    cp.set_defaults(func=config_retention_command)

    return p


def _load_cfg_from_args(args: argparse.Namespace) -> Settings:
    return load_config(args.config)


def cmd_setup(args: argparse.Namespace) -> int:
    if getattr(args, "wizard", False):
        return run_setup_wizard(args)

    cfg = _load_cfg_from_args(args)
    if args.password_file:
        os.environ["RESTIC_PASSWORD_FILE"] = os.path.expanduser(args.password_file)

    try:
        from .runner import run_restic

        try:
            run_restic(cfg, ["init"], log_prefix="init")
            print("Repository initialized.")
        except RunError as exc:
            print(f"[setup] init returned error (likely already initialized): {exc}", file=sys.stderr)

        if args.remote_check:
            run_restic(cfg, ["unlock"], log_prefix="unlock")
            print("Remote check (unlock) completed.")

        return 0
    except RunError as exc:
        print(str(exc), file=sys.stderr)
        return 2


def cmd_list(args: argparse.Namespace) -> int:
    cfg = _load_cfg_from_args(args)
    extra: list[str] = []
    if args.path:
        for path in args.path:
            extra += ["--path", os.path.expanduser(path)]
    if args.tag:
        for tag in args.tag:
            extra += ["--tag", tag]
    if args.host:
        extra += ["--host", args.host]

    try:
        list_snapshots(cfg, extra_args=extra)
        return 0
    except RunError as exc:
        print(str(exc), file=sys.stderr)
        return 3


def _get_set(cfg: Settings, name: str) -> BackupSet:
    for backup_set in cfg.sets:
        if backup_set.name == name:
            return backup_set
    raise SystemExit(f"Backup set '{name}' not found in config.")


def cmd_backup(args: argparse.Namespace) -> int:
    cfg = _load_cfg_from_args(args)
    backup_set = _get_set(cfg, args.set)

    effective = dc.replace(
        backup_set,
        include=list(backup_set.include),
        exclude=list(backup_set.exclude) + (args.exclude or []),
        tags=list(backup_set.tags) + (args.tag or []),
        dry_run_default=True if args.dry_run else backup_set.dry_run_default,
    )

    try:
        start_backup(cfg, effective, extra_args=(args.extra or []), name_hint=f"backup-{effective.name}")
        return 0
    except RunError as exc:
        print(str(exc), file=sys.stderr)
        return 4


def cmd_stats(args: argparse.Namespace) -> int:
    cfg = _load_cfg_from_args(args)
    try:
        repo_stats(cfg)
        return 0
    except RunError as exc:
        print(str(exc), file=sys.stderr)
        return 5


def cmd_check(args: argparse.Namespace) -> int:
    cfg = _load_cfg_from_args(args)
    try:
        run_check(cfg)
        return 0
    except RunError as exc:
        print(str(exc), file=sys.stderr)
        return 6


def cmd_prune(args: argparse.Namespace) -> int:
    cfg = _load_cfg_from_args(args)
    try:
        run_forget_prune(cfg)
        return 0
    except RunError as exc:
        print(str(exc), file=sys.stderr)
        return 7


def cmd_progress(args: argparse.Namespace) -> int:
    cfg = _load_cfg_from_args(args)
    show_in_progress(cfg)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse and dispatch the legacy RRBackup CLI with stable boundary errors."""
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    try:
        return int(args.func(args))
    except (OSError, ValueError) as exc:
        print(f"rrb: {exc}", file=sys.stderr)
        return CLI_CONFIGURATION_ERROR_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
