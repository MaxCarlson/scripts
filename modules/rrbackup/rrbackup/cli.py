from __future__ import annotations

import argparse
import os
import sys
from typing import Sequence

import dataclasses as dc

from . import __version__
from .config import load_config, Settings, BackupSet, platform_config_default
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
    start_backup,
    list_snapshots,
    repo_stats,
    run_check,
    run_forget_prune,
    show_in_progress,
)


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

    # setup (repo init)
    sp = sub.add_parser("setup", help="Initialize the restic repository (requires configured credentials).")
    sp.add_argument("--password-file", "-p", help="Optional override RESTIC_PASSWORD_FILE path for init")
    sp.add_argument("--remote-check", "-r", action="store_true", help="Run a remote accessibility check via restic unlock")
    sp.set_defaults(func=cmd_setup)

    # list snapshots
    sp = sub.add_parser("list", help="List snapshots.")
    sp.add_argument("--path", "-P", action="append", help="Filter by path (repeatable)")
    sp.add_argument("--tag", "-t", action="append", help="Filter by tag (repeatable)")
    sp.add_argument("--host", "-H", help="Filter by host")
    sp.set_defaults(func=cmd_list)

    # backup
    sp = sub.add_parser("backup", help="Run backup for a configured backup set.")
    sp.add_argument("--set", "-s", required=True, help="Backup set name from config.toml")
    sp.add_argument("--dry-run", "-n", action="store_true", help="Force dry-run for this invocation")
    sp.add_argument("--tag", "-t", action="append", help="Additional tag(s)")
    sp.add_argument("--exclude", "-e", action="append", help="Additional exclude(s)")
    sp.add_argument("--extra", "-x", action="append", help="Raw extra args for restic (repeatable)")
    sp.set_defaults(func=cmd_backup)

    # stats
    sp = sub.add_parser("stats", help="Show repo stats (restore-size).")
    sp.set_defaults(func=cmd_stats)

    # check
    sp = sub.add_parser("check", help="Run restic check.")
    sp.set_defaults(func=cmd_check)

    # forget/prune
    sp = sub.add_parser("prune", help="Apply retention policy (forget --prune).")
    sp.set_defaults(func=cmd_prune)

    # progress / in-progress
    sp = sub.add_parser("progress", help="Show in-progress rrbackup tasks and restic locks.")
    sp.set_defaults(func=cmd_progress)

    # config management
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
    cp.add_argument("--schedule", "-c", help="Human-friendly schedule description for this set.")
    cp.add_argument("--backup-type", "-b", default="incremental", help="Backup type descriptor (default: incremental).")
    cp.add_argument(
        "--max-snapshots",
        "-m",
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
    cp.add_argument("--clear", "-X", action="store_true", help="Clear all retention values.")
    cp.add_argument("--use-defaults", "-u", action="store_true", help="Reset to default retention policy.")
    cp.set_defaults(func=config_retention_command)

    return p


def _load_cfg_from_args(args: argparse.Namespace) -> Settings:
    return load_config(args.config)


def cmd_setup(args: argparse.Namespace) -> int:
    cfg = _load_cfg_from_args(args)
    # Initialize repository
    extra = []
    if args.password_file:
        os.environ["RESTIC_PASSWORD_FILE"] = os.path.expanduser(args.password_file)
    try:
        # restic init (idempotent: if already initialized, returns error; that's okay for first-time)
        from .runner import run_restic
        try:
            run_restic(cfg, ["init"], log_prefix="init")
            print("Repository initialized.")
        except RunError as e:
            print(f"[setup] init returned error (likely already initialized): {e}", file=sys.stderr)
        if args.remote_check:
            # 'unlock' is harmless and validates access & creds.
            run_restic(cfg, ["unlock"], log_prefix="unlock")
            print("Remote check (unlock) completed.")
        return 0
    except RunError as e:
        print(str(e), file=sys.stderr)
        return 2


def cmd_list(args: argparse.Namespace) -> int:
    cfg = _load_cfg_from_args(args)
    extra: list[str] = []
    if args.path:
        for p in args.path:
            extra += ["--path", os.path.expanduser(p)]
    if args.tag:
        for t in args.tag:
            extra += ["--tag", t]
    if args.host:
        extra += ["--host", args.host]
    try:
        list_snapshots(cfg, extra_args=extra)
        return 0
    except RunError as e:
        print(str(e), file=sys.stderr)
        return 3


def _get_set(cfg: Settings, name: str) -> BackupSet:
    for s in cfg.sets:
        if s.name == name:
            return s
    raise SystemExit(f"Backup set '{name}' not found in config.")


def cmd_backup(args: argparse.Namespace) -> int:
    cfg = _load_cfg_from_args(args)
    bset = _get_set(cfg, args.set)

    # Apply per-run overrides
    effective = dc.replace(
        bset,
        include=list(bset.include),
        exclude=list(bset.exclude) + (args.exclude or []),
        tags=list(bset.tags) + (args.tag or []),
        dry_run_default=True if args.dry_run else bset.dry_run_default,
    )

    try:
        start_backup(cfg, effective, extra_args=(args.extra or []), name_hint=f"backup-{effective.name}")
        return 0
    except RunError as e:
        print(str(e), file=sys.stderr)
        return 4


def cmd_stats(_: argparse.Namespace) -> int:
    cfg = _load_cfg_from_args(_)
    try:
        repo_stats(cfg)
        return 0
    except RunError as e:
        print(str(e), file=sys.stderr)
        return 5


def cmd_check(_: argparse.Namespace) -> int:
    cfg = _load_cfg_from_args(_)
    try:
        run_check(cfg)
        return 0
    except RunError as e:
        print(str(e), file=sys.stderr)
        return 6


def cmd_prune(_: argparse.Namespace) -> int:
    cfg = _load_cfg_from_args(_)
    try:
        run_forget_prune(cfg)
        return 0
    except RunError as e:
        print(str(e), file=sys.stderr)
        return 7


def cmd_progress(_: argparse.Namespace) -> int:
    cfg = _load_cfg_from_args(_)
    show_in_progress(cfg)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
