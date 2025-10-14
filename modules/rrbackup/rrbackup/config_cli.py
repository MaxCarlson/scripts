from __future__ import annotations

import argparse
import os
import shutil
import string
import sys
from pathlib import Path
from typing import Optional

from .config import (
    BackupSet,
    Repo,
    Retention,
    Settings,
    load_config,
    resolve_config_path,
    save_config,
    settings_to_dict,
)
from .runner import RunError, run_restic


def _expand_path(path: Path) -> Path:
    """Expand environment variables and user home in a Path."""
    return Path(os.path.expandvars(str(path))).expanduser()


def _target_path(args: argparse.Namespace) -> Path:
    """
    Determine which configuration file path to operate on using precedence:
    explicit --path > global --config > RRBACKUP_CONFIG env > default.
    """
    raw = getattr(args, "path", None) or getattr(args, "config", None)
    resolved = resolve_config_path(raw)
    return _expand_path(resolved)


def _load_existing_config(args: argparse.Namespace, *, expand: bool = False) -> tuple[Settings, Path]:
    """Load configuration (optionally expanded) and return with its resolved path."""
    target = _target_path(args)
    cfg = load_config(str(target), expand=expand)
    return cfg, target


def _dump_settings(settings: Settings) -> str:
    """Render a Settings object back to TOML text."""
    from .config import tomli_w  # type: ignore[attr-defined]

    if tomli_w is None:
        raise RuntimeError("tomli-w is required to display rrbackup configuration.")
    data = settings_to_dict(settings)
    return tomli_w.dumps(data)


def config_init_command(args: argparse.Namespace) -> int:
    """Create a new rrbackup configuration file with default values."""
    target = _target_path(args)
    settings = Settings()
    try:
        save_config(settings, str(target), overwrite=args.force)
    except FileExistsError:
        print(f"[rrbackup] Configuration already exists: {target}. Use --force/-f to overwrite.", file=sys.stderr)
        return 1
    except RuntimeError as err:
        print(str(err), file=sys.stderr)
        return 1

    print(f"Created rrbackup config at {target}.")
    return 0


def config_show_command(args: argparse.Namespace) -> int:
    """Show current configuration (raw or expanded)."""
    try:
        cfg, target = _load_existing_config(args, expand=args.effective)
    except FileNotFoundError as err:
        print(str(err), file=sys.stderr)
        return 1

    print(f"# rrbackup config: {target}")
    try:
        print(_dump_settings(cfg))
    except RuntimeError as err:
        print(f"[rrbackup] Unable to show configuration: {err}", file=sys.stderr)
        return 1
    return 0


def config_list_sets_command(args: argparse.Namespace) -> int:
    """List backup sets defined in the configuration."""
    try:
        cfg, target = _load_existing_config(args, expand=False)
    except FileNotFoundError as err:
        print(str(err), file=sys.stderr)
        return 1

    if not cfg.sets:
        print(f"No backup sets defined in {target}.")
        return 0

    print(f"Backup sets in {target}:")
    for bset in cfg.sets:
        print(
            f"  - {bset.name} (includes: {len(bset.include)} paths, "
            f"excludes: {len(bset.exclude)}, schedule: {bset.schedule or 'unscheduled'})"
        )
    return 0


def _ensure_includes(includes: list[str]) -> None:
    if not includes:
        raise ValueError("At least one --include/-i path is required.")


def _value_or_none(value: Optional[str]) -> Optional[str]:
    """Treat blank strings as None for easier CLI use."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def config_add_set_command(args: argparse.Namespace) -> int:
    """Add a backup set entry to the configuration."""
    includes = [os.path.expanduser(p) for p in (args.include or [])]
    try:
        _ensure_includes(includes)
    except ValueError as err:
        print(f"[rrbackup] {err}", file=sys.stderr)
        return 1

    try:
        cfg, target = _load_existing_config(args, expand=False)
    except FileNotFoundError as err:
        print(str(err), file=sys.stderr)
        return 1

    if any(bset.name == args.name for bset in cfg.sets):
        print(f"[rrbackup] Backup set '{args.name}' already exists in {target}.", file=sys.stderr)
        return 1

    new_set = BackupSet(
        name=args.name,
        include=includes,
        exclude=list(args.exclude or []),
        tags=list(args.tag or []),
        one_fs=args.one_fs,
        dry_run_default=args.dry_run_default,
        schedule=_value_or_none(args.schedule),
        backup_type=args.backup_type,
        max_snapshots=args.max_snapshots,
        encryption=_value_or_none(args.encryption),
        compression=_value_or_none(args.compression),
    )
    cfg.sets.append(new_set)

    try:
        save_config(cfg, str(target), overwrite=True)
    except RuntimeError as err:
        print(str(err), file=sys.stderr)
        return 1

    print(f"Added backup set '{args.name}' to {target}.")
    return 0


def config_remove_set_command(args: argparse.Namespace) -> int:
    """Remove a backup set from the configuration."""
    try:
        cfg, target = _load_existing_config(args, expand=False)
    except FileNotFoundError as err:
        print(str(err), file=sys.stderr)
        return 1

    before = len(cfg.sets)
    cfg.sets = [bset for bset in cfg.sets if bset.name != args.name]
    if len(cfg.sets) == before:
        print(f"[rrbackup] Backup set '{args.name}' not found in {target}.", file=sys.stderr)
        return 1

    try:
        save_config(cfg, str(target), overwrite=True)
    except RuntimeError as err:
        print(str(err), file=sys.stderr)
        return 1

    print(f"Removed backup set '{args.name}' from {target}.")
    return 0


def config_set_command(args: argparse.Namespace) -> int:
    """Update top-level configuration values such as repository and binary paths."""
    try:
        cfg, target = _load_existing_config(args, expand=False)
    except FileNotFoundError as err:
        print(str(err), file=sys.stderr)
        return 1

    updated = False

    repo = cfg.repo or Repo(url="")
    if args.repo_url is not None:
        repo.url = args.repo_url
        updated = True
    if args.password_file is not None:
        repo.password_file = _value_or_none(args.password_file)
        updated = True
    if args.password_env is not None:
        repo.password_env = _value_or_none(args.password_env)
        updated = True
    cfg.repo = repo if repo.url or repo.password_env or repo.password_file else None

    if args.restic_bin is not None:
        cfg.restic_bin = args.restic_bin
        updated = True
    if args.rclone_bin is not None:
        cfg.rclone_bin = args.rclone_bin
        updated = True
    if args.state_dir is not None:
        cfg.state_dir = _value_or_none(args.state_dir)
        updated = True
    if args.log_dir is not None:
        cfg.log_dir = _value_or_none(args.log_dir)
        updated = True

    if not updated:
        print("[rrbackup] No updates specified. Use --help for available options.", file=sys.stderr)
        return 1

    try:
        save_config(cfg, str(target), overwrite=True)
    except RuntimeError as err:
        print(str(err), file=sys.stderr)
        return 1

    print(f"Updated configuration values in {target}.")
    return 0


def config_retention_command(args: argparse.Namespace) -> int:
    """Update retention policy values."""
    if args.clear and args.use_defaults:
        print("[rrbackup] --clear/-X and --use-defaults/-u cannot be used together.", file=sys.stderr)
        return 1

    try:
        cfg, target = _load_existing_config(args, expand=False)
    except FileNotFoundError as err:
        print(str(err), file=sys.stderr)
        return 1

    if args.clear:
        cfg.retention = Retention(
            keep_last=None,
            keep_hourly=None,
            keep_daily=None,
            keep_weekly=None,
            keep_monthly=None,
            keep_yearly=None,
        )
    elif args.use_defaults:
        cfg.retention = Retention()
    else:
        ret = cfg.retention
        for attr, value in (
            ("keep_last", args.keep_last),
            ("keep_hourly", args.keep_hourly),
            ("keep_daily", args.keep_daily),
            ("keep_weekly", args.keep_weekly),
            ("keep_monthly", args.keep_monthly),
            ("keep_yearly", args.keep_yearly),
        ):
            if value is not None:
                setattr(ret, attr, value)

    try:
        save_config(cfg, str(target), overwrite=True)
    except RuntimeError as err:
        print(str(err), file=sys.stderr)
        return 1

    print(f"Updated retention policy in {target}.")
    return 0


def _prompt_text(prompt: str, *, default: Optional[str] = None, required: bool = False) -> str:
    while True:
        suffix = f" [{default}]" if default else ""
        try:
            response = input(f"{prompt}{suffix}: ").strip()
        except EOFError:
            raise SystemExit(1)
        except KeyboardInterrupt:
            print("\n[rrbackup] Setup wizard cancelled.", file=sys.stderr)
            raise SystemExit(1)
        if not response and default is not None:
            return default
        if response:
            return response
        if not required:
            return ""
        print("A value is required.", file=sys.stderr)


def _prompt_bool(prompt: str, *, default: bool = True) -> bool:
    choice = "Y/n" if default else "y/N"
    while True:
        try:
            response = input(f"{prompt} [{choice}]: ").strip().lower()
        except EOFError:
            raise SystemExit(1)
        except KeyboardInterrupt:
            print("\n[rrbackup] Setup wizard cancelled.", file=sys.stderr)
            raise SystemExit(1)
        if not response:
            return default
        if response in {"y", "yes"}:
            return True
        if response in {"n", "no"}:
            return False
        print("Please answer 'y' or 'n'.", file=sys.stderr)


def _prompt_int(
    prompt: str,
    *,
    default: Optional[int] = None,
    allow_empty: bool = True,
) -> Optional[int]:
    while True:
        suffix = ""
        if default is not None:
            suffix = f" [{default}]"
        elif not allow_empty:
            suffix = " (required)"
        try:
            response = input(f"{prompt}{suffix}: ").strip()
        except EOFError:
            raise SystemExit(1)
        except KeyboardInterrupt:
            print("\n[rrbackup] Setup wizard cancelled.", file=sys.stderr)
            raise SystemExit(1)

        if not response:
            if default is not None:
                return default
            if allow_empty:
                return None
            print("A value is required.", file=sys.stderr)
            continue
        try:
            return int(response)
        except ValueError:
            print("Please enter a valid integer.", file=sys.stderr)


def _prompt_list(
    prompt: str,
    *,
    min_items: int = 0,
    guidance: Optional[str] = None,
) -> list[str]:
    items: list[str] = []
    if guidance:
        print(guidance)
    while True:
        suffix = "" if items else " (enter value)"
        try:
            response = input(f"{prompt}{suffix} (blank to finish): ").strip()
        except EOFError:
            raise SystemExit(1)
        except KeyboardInterrupt:
            print("\n[rrbackup] Setup wizard cancelled.", file=sys.stderr)
            raise SystemExit(1)
        if not response:
            if len(items) >= min_items:
                return items
            print(f"Please provide at least {min_items} value(s).", file=sys.stderr)
            continue
        items.append(response)


def _prompt_choice(prompt: str, options: list[str], *, default_index: Optional[int] = None) -> int:
    while True:
        print(prompt)
        for idx, option in enumerate(options, start=1):
            marker = " (default)" if default_index is not None and default_index == idx - 1 else ""
            print(f"  {idx}. {option}{marker}")
        try:
            response = input("Select option number: ").strip()
        except EOFError:
            raise SystemExit(1)
        except KeyboardInterrupt:
            print("\n[rrbackup] Setup wizard cancelled.", file=sys.stderr)
            raise SystemExit(1)
        if not response and default_index is not None:
            return default_index
        if response.isdigit():
            choice = int(response) - 1
            if 0 <= choice < len(options):
                return choice
        print("Please enter a valid option number.", file=sys.stderr)


def _list_available_drives() -> list[str]:
    drives: list[str] = []
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            candidate = Path(f"{letter}:/")
            if candidate.exists():
                drives.append(f"{letter}:/")
    return drives


def _select_repository_url() -> str:
    options = [
        "Local folder or drive path (e.g., D:/rrbackup)",
        "Google Drive via rclone remote",
        "Custom restic repository URL",
    ]
    choice = _prompt_choice("\nWhere should the backup repository live?", options, default_index=0)

    if choice == 0:
        drives = _list_available_drives()
        if drives:
            print("Detected drives: " + ", ".join(drives))
        local_path = _prompt_text(
            "Local repository path (will be created if needed)",
            default=str(Path.home() / "restic-repo"),
            required=True,
        )
        return str(_expand_path(Path(local_path)))

    if choice == 1:
        if shutil.which("rclone") is None:
            print(
                "[rrbackup] rclone not found on PATH. Please install and configure rclone before running backups.",
                file=sys.stderr,
            )
        remote_name = _prompt_text("Existing rclone remote name", default="gdrive", required=True)
        remote_path = _prompt_text("Remote path for restic repository", default="backups/rrbackup", required=True)
        remote_path = remote_path.lstrip("/")
        print(
            "Reminder: ensure the rclone remote is authorized (e.g., run `rclone config reconnect "
            f"{remote_name}:`)."
        )
        return f"rclone:{remote_name}:{remote_path}"

    return _prompt_text("Restic repository URL", required=True)


def _prompt_encryption_method() -> tuple[Optional[str], Optional[str]]:
    options = [
        "Use a password file (recommended)",
        "Use an environment variable",
        "I'll configure encryption manually later",
    ]
    choice = _prompt_choice("\nHow should restic retrieve its encryption password?", options, default_index=0)
    if choice == 0:
        password_file = _prompt_text(
            "Password file path",
            default="~/.config/rrbackup/restic_password.txt",
            required=True,
        )
        return os.path.expanduser(password_file), None
    if choice == 1:
        env_name = _prompt_text(
            "Environment variable that contains the password",
            default="RESTIC_PASSWORD",
            required=True,
        )
        return None, env_name
    print("You can update the configuration later with `rrb config set --password-file` or `--password-env`.")
    return None, None


def _collect_backup_sets() -> list[BackupSet]:
    sets: list[BackupSet] = []
    print("\nConfigure backup sets. You can add multiple sets, each with their own include/exclude lists.")
    while True:
        add_set = _prompt_bool(
            "Would you like to add a backup set?",
            default=True if not sets else False,
        )
        if not add_set:
            break
        name = _prompt_text("Set name", required=True)
        includes = _prompt_list(
            "Include path",
            min_items=1,
            guidance="Provide full paths to include. Repeat until you've added all desired paths.",
        )
        excludes = _prompt_list("Exclude pattern", guidance="Provide glob patterns to exclude (optional).")
        tags = _prompt_list("Tag", guidance="Optional restic tags to associate with this backup set.")
        schedule_desc = _prompt_text(
            "How often should this backup run? (e.g., daily 02:00, weekly Sunday 01:30)",
            default="",
            required=False,
        )
        backup_type_choice = _prompt_choice(
            "Backup type for this set:",
            [
                "Standard incremental (restic default)",
                "Full (run as a full copy each time)",
                "Custom description",
            ],
            default_index=0,
        )
        if backup_type_choice == 0:
            backup_type = "incremental"
        elif backup_type_choice == 1:
            backup_type = "full"
        else:
            backup_type = _prompt_text("Describe the backup type", required=True)

        max_snapshots = _prompt_int(
            "How many snapshots should be kept for this set? (blank to use global retention)",
            allow_empty=True,
        )

        encryption_choice = _prompt_choice(
            "Encryption for this set:",
            [
                "Use repository default",
                "Custom description",
                "None (not recommended)",
            ],
            default_index=0,
        )
        if encryption_choice == 0:
            encryption = "repository-default"
        elif encryption_choice == 1:
            encryption = _prompt_text("Describe encryption requirements", required=True)
        else:
            encryption = "none"

        compression_choice = _prompt_choice(
            "Compression preference:",
            [
                "Auto (restic default)",
                "Maximum compression",
                "Minimal compression",
                "Custom description",
            ],
            default_index=0,
        )
        if compression_choice == 0:
            compression = "auto"
        elif compression_choice == 1:
            compression = "max"
        elif compression_choice == 2:
            compression = "minimal"
        else:
            compression = _prompt_text("Describe compression preference", required=True)

        one_fs = _prompt_bool("Use --one-file-system for this set?", default=False)
        dry_run_default = _prompt_bool("Enable dry-run by default for this set?", default=False)
        sets.append(
            BackupSet(
                name=name,
                include=includes,
                exclude=excludes,
                tags=tags,
                one_fs=one_fs,
                dry_run_default=dry_run_default,
                schedule=schedule_desc or None,
                backup_type=backup_type,
                max_snapshots=max_snapshots,
                encryption=encryption,
                compression=compression,
            )
        )
    return sets


def _build_settings_from_wizard() -> Settings:
    print("rrbackup setup wizard\n----------------------")
    print("This wizard will create a configuration file for rrbackup.\n")

    repo_url = _select_repository_url()
    password_file, password_env = _prompt_encryption_method()

    restic_bin = _prompt_text("restic binary (leave default unless customized)", default="restic", required=True)
    rclone_bin = _prompt_text("rclone binary (leave default unless customized)", default="rclone", required=True)

    state_dir = _value_or_none(_prompt_text("State directory (blank for OS default)"))
    log_dir = _value_or_none(_prompt_text("Log directory (blank to use state-dir/logs)"))

    if _prompt_bool("Use default retention policy (daily=7, weekly=4, monthly=6, yearly=2)?", default=True):
        retention = Retention()
    else:
        retention = Retention(
            keep_last=_prompt_int("Keep last snapshots (blank to skip)"),
            keep_hourly=_prompt_int("Keep hourly snapshots (blank to skip)"),
            keep_daily=_prompt_int("Keep daily snapshots (blank to skip)"),
            keep_weekly=_prompt_int("Keep weekly snapshots (blank to skip)"),
            keep_monthly=_prompt_int("Keep monthly snapshots (blank to skip)"),
            keep_yearly=_prompt_int("Keep yearly snapshots (blank to skip)"),
        )

    sets = _collect_backup_sets()
    if not sets:
        print("No backup sets were defined. You can add them later with `rrb config add-set`.", file=sys.stderr)

    repo = Repo(url=repo_url, password_env=password_env, password_file=password_file)
    return Settings(
        restic_bin=restic_bin,
        rclone_bin=rclone_bin,
        log_dir=log_dir,
        state_dir=state_dir,
        repo=repo,
        sets=sets,
        retention=retention,
    )


def config_wizard_command(args: argparse.Namespace) -> int:
    """Interactive setup wizard for creating a configuration."""
    target = _target_path(args)
    if target.exists() and not args.force:
        print(f"[rrbackup] Configuration already exists at {target}. Use --force/-f to overwrite.", file=sys.stderr)
        return 1

    settings = _build_settings_from_wizard()
    try:
        save_config(settings, str(target), overwrite=True)
    except RuntimeError as err:
        print(str(err), file=sys.stderr)
        return 1

    print(f"\nConfiguration saved to {target}.")

    if args.initialize_repo:
        print("Initializing restic repository using the new configuration...")
        try:
            cfg = load_config(str(target), expand=True)
            run_restic(cfg, ["init"], log_prefix="init")
            print("Repository initialized successfully.")
        except (FileNotFoundError, RunError) as err:
            print(f"[rrbackup] Failed to initialize repository: {err}", file=sys.stderr)
            return 2

    return 0
