from __future__ import annotations

import argparse
import os
import platform
import secrets
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Iterable

from .config import (
    BackupSet,
    Repo,
    RetentionPolicy,
    Schedule,
    Settings,
    load_config,
    platform_config_default,
    resolve_config_path,
    save_config,
)
from .config_cli import _collect_backup_sets
from .interactive import launch_editor, prompt_bool, prompt_choice, prompt_int, prompt_text
from .runner import RunError, run_forget_prune, run_restic, start_backup


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _run_command(args: list[str], *, capture: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run a subprocess command safely."""
    return subprocess.run(
        args,
        capture_output=capture,
        text=True,
        env=env,
    )


def _shlex_quote(value: str) -> str:
    if os.name == "nt":
        return f'"{value}"'
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _sanitize_name(name: str) -> str:
    safe = "".join(ch if ch.isalnum() else "-" for ch in name.strip())
    return safe.strip("-") or "rrbackup-set"


def _parse_time_value(value: str | None, default: str = "02:00") -> tuple[str, str]:
    if not value:
        value = default
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError("Time must be in HH:MM format")
    hour, minute = (int(part) for part in parts)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("Time must be between 00:00 and 23:59")
    return f"{hour:02d}", f"{minute:02d}"


def _current_platform() -> str:
    system = platform.system().lower()
    if "windows" in system:
        return "windows"
    if system in {"linux", "darwin"}:
        if "TERMUX_VERSION" in os.environ:
            return "termux"
        return "linux"
    return system


def _default_password_path() -> Path:
    if _current_platform() == "windows":
        appdata = os.environ.get("APPDATA") or str(platform_config_default().parent)
        return Path(appdata) / "rrbackup" / "restic_password.txt"
    return Path.home() / ".config" / "rrbackup" / "restic_password.txt"


def _default_state_dir() -> Path:
    platform_name = _current_platform()
    if platform_name == "windows":
        localapp = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(localapp) / "rrbackup"
    return Path.home() / ".cache" / "rrbackup"


# ---------------------------------------------------------------------------
# Wizard implementation
# ---------------------------------------------------------------------------


class SetupWizard:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.platform = _current_platform()
        self.config_path = resolve_config_path(getattr(args, "config", None))

        if self.config_path.exists():
            self.settings = load_config(self.config_path, expand=False)
            self.existing_config = True
        else:
            self.settings = Settings()
            self.existing_config = False

        self.expanded_settings: Settings | None = None

    # ------------------------------------------------------------------ public
    def run(self) -> int:
        self._step_welcome()
        self._step_verify_tools()
        self._step_configure_repository()
        self._step_password_file()
        self._step_state_directories()
        self._step_backup_sets()
        self._step_global_retention()
        if not self._step_review_and_save():
            print("Aborted by user.")
            return 1
        self._expanded_settings()
        self._step_initialize_repository()
        self._step_scheduler_install()
        self._step_optional_backup()
        print("\nSetup wizard complete. You can rerun `rrb setup --wizard` at any time.")
        return 0

    # ------------------------------------------------------------------ steps
    def _step_welcome(self) -> None:
        print("=== RRBackup Setup Wizard ===\n")
        print(
            "This wizard will guide you through:\n"
            "  • Verifying restic and rclone installations\n"
            "  • Configuring the repository destination\n"
            "  • Creating a secure password file\n"
            "  • Defining backup sets with schedules and retention\n"
            "  • Installing scheduled tasks\n"
            "  • Optionally running a first backup\n"
        )
        if not prompt_bool("Continue?", default=True):
            raise SystemExit(0)

    def _step_verify_tools(self) -> None:
        print("\n-- Verifying required tools --")
        self.settings.restic_bin = self._ensure_tool(
            "restic",
            current=self.settings.restic_bin,
            install_commands=self._restic_install_commands(),
        )
        self.settings.rclone_bin = self._ensure_tool(
            "rclone",
            current=self.settings.rclone_bin,
            install_commands=self._rclone_install_commands(),
        )

    def _step_configure_repository(self) -> None:
        print("\n-- Configure repository destination --")
        if self.settings.repo:
            print(f"Current repository: {self.settings.repo.url}")
            choice = prompt_choice(
                "Repository options:",
                [
                    "Keep existing repository",
                    "Change repository destination",
                    "View rclone instructions",
                ],
                default_index=0,
            )
            if choice == 2:
                self._print_rclone_help()
            if choice == 0:
                return

        repo_choice = prompt_choice(
            "Where should backups be stored?",
            [
                "Google Drive (via rclone)",
                "Local folder or drive",
                "Custom restic repository URL",
            ],
            default_index=0,
        )

        if repo_choice == 0:
            repo_url = self._configure_gdrive_repository()
        elif repo_choice == 1:
            repo_url = self._configure_local_repository()
        else:
            repo_url = prompt_text("Enter restic repository URL", required=True)
        self.settings.repo = Repo(url=repo_url)

    def _step_password_file(self) -> None:
        if not self.settings.repo:
            return

        print("\n-- Configure restic password file --")
        default_path = self.settings.repo.password_file or str(_default_password_path())

        if self.settings.repo.password_file and Path(self.settings.repo.password_file).exists():
            print(f"Existing password file: {self.settings.repo.password_file}")
            choice = prompt_choice(
                "Password options:",
                [
                    "Keep existing password file",
                    "Regenerate password",
                    "Open password file in editor",
                    "Switch to environment variable",
                ],
                default_index=0,
            )
            if choice == 0:
                return
            if choice == 2:
                launch_editor(Path(self.settings.repo.password_file))
                return
            if choice == 3:
                env_name = prompt_text("Environment variable name", default="RESTIC_PASSWORD", required=True)
                self.settings.repo.password_env = env_name
                self.settings.repo.password_file = None
                print("Remember to set the environment variable before running backups.")
                return

        password = secrets.token_urlsafe(32)
        path = Path(os.path.expandvars(os.path.expanduser(prompt_text("Password file path", default=default_path, required=True))))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(password, encoding="utf-8")
        self._secure_password_file(path)
        self.settings.repo.password_file = str(path)
        self.settings.repo.password_env = None
        if prompt_bool("Display generated password now?", default=False):
            print(f"Generated password: {password}")
        else:
            print("Password stored securely. Back it up in a safe location.")

    def _step_state_directories(self) -> None:
        print("\n-- Configure state and log directories --")
        state_default = self.settings.state_dir or str(_default_state_dir())
        log_default = self.settings.log_dir or ""
        self.settings.state_dir = prompt_text("State directory", default=state_default, required=True)
        self.settings.log_dir = prompt_text("Log directory (blank for state/logs)", default=log_default, required=False) or None

    def _step_backup_sets(self) -> None:
        print("\n-- Define backup sets --")
        if self.settings.sets:
            print("Existing backup sets:")
            for bset in self.settings.sets:
                label = bset.schedule.description if isinstance(bset.schedule, Schedule) and bset.schedule.description else bset.schedule.type
                print(f"  • {bset.name}: schedule={label}")
            choice = prompt_choice(
                "Backup set options:",
                [
                    "Keep existing sets",
                    "Rebuild backup sets",
                    "Edit configuration manually (opens editor)",
                ],
                default_index=0,
            )
            if choice == 0:
                return
            if choice == 2:
                if launch_editor(self.config_path):
                    print("Re-run wizard after manual edits if needed.")
                    raise SystemExit(0)
                else:
                    print("Unable to launch editor. Continuing wizard.")

        sets = _collect_backup_sets()
        if sets:
            self.settings.sets = sets
        else:
            print("[rrbackup] No backup sets defined. Use `rrb config add-set` later if desired.")

    def _step_global_retention(self) -> None:
        print("\n-- Retention defaults --")
        policy = self.settings.retention_defaults
        summary = (
            f"keep_last={policy.keep_last}, keep_daily={policy.keep_daily}, keep_weekly={policy.keep_weekly}, "
            f"keep_monthly={policy.keep_monthly}, keep_yearly={policy.keep_yearly}, max_total_size={policy.max_total_size or 'unlimited'}"
        )
        print(f"Current defaults: {summary}")
        if not prompt_bool("Adjust retention defaults?", default=not self.existing_config):
            return

        keep_last = prompt_int("Keep last snapshots (blank to skip)")
        keep_hourly = prompt_int("Keep hourly snapshots (blank to skip)")
        keep_daily = prompt_int("Keep daily snapshots (blank to skip)", default=policy.keep_daily)
        keep_weekly = prompt_int("Keep weekly snapshots (blank to skip)", default=policy.keep_weekly)
        keep_monthly = prompt_int("Keep monthly snapshots (blank to skip)", default=policy.keep_monthly)
        keep_yearly = prompt_int("Keep yearly snapshots (blank to skip)", default=policy.keep_yearly)
        size_limit = prompt_text("Maximum total size (e.g., 1024GB) (blank for unlimited)")

        new_policy = RetentionPolicy(
            keep_last=keep_last,
            keep_hourly=keep_hourly,
            keep_daily=keep_daily,
            keep_weekly=keep_weekly,
            keep_monthly=keep_monthly,
            keep_yearly=keep_yearly,
        )
        if size_limit:
            try:
                raw, bytes_value = self._parse_size(size_limit)
            except ValueError as exc:
                print(f"[rrbackup] {exc}. Ignoring size limit.")
            else:
                new_policy.max_total_size = raw
                new_policy.max_total_size_bytes = bytes_value
        self.settings.retention_defaults = new_policy

    def _step_initialize_repository(self) -> None:
        if not self.expanded_settings or not self.expanded_settings.repo:
            print("[rrbackup] Repository not configured; skipping initialization.")
            return

        print("\n-- Restic repository initialization --")
        runtime = self.expanded_settings
        env = os.environ.copy()
        if runtime.repo.password_file:
            env["RESTIC_PASSWORD_FILE"] = runtime.repo.password_file

        try:
            run_restic(runtime, ["snapshots"], log_prefix="setup-snapshots")
            print("Repository reachable (restic snapshots succeeded).")
        except RunError:
            if prompt_bool("Repository not found. Initialize now?", default=True):
                try:
                    run_restic(runtime, ["init"], log_prefix="setup-init", live_output=True)
                    print("Repository initialized successfully.")
                except RunError as err:
                    print(f"[rrbackup] Restic init failed: {err}")
            else:
                print("Skipping repository initialization.")

    def _step_scheduler_install(self) -> None:
        scheduled_sets = [b for b in self.settings.sets if isinstance(b.schedule, Schedule) and b.schedule.type != "manual"]
        if not scheduled_sets:
            return

        print("\n-- Scheduler installation --")
        scheduler = self._select_scheduler()
        if scheduler == "skip":
            print("Skipping scheduler integration.")
            return

        for bset in scheduled_sets:
            try:
                if scheduler == "windows":
                    self._install_windows_task(bset)
                elif scheduler == "systemd":
                    self._install_systemd_timer(bset)
                elif scheduler == "cron":
                    self._install_cron_entry(bset)
            except Exception as exc:
                print(f"[warn] Failed to install schedule for set '{bset.name}': {exc}")

    def _step_optional_backup(self) -> None:
        if not self.settings.sets or not self.expanded_settings:
            return
        choice = prompt_choice(
            "Run an initial backup now?",
            [
                "No, skip",
                "Dry-run all sets",
                "Run full backup for all sets",
            ],
            default_index=0,
        )
        if choice == 0:
            return

        runtime = self.expanded_settings
        if runtime.repo and runtime.repo.password_file:
            os.environ["RESTIC_PASSWORD_FILE"] = runtime.repo.password_file

        for bset in runtime.sets:
            label = "dry-run" if choice == 1 else "backup"
            print(f"\n>>> Starting {label} for set '{bset.name}'")
            extra = ["--dry-run"] if choice == 1 else []
            try:
                start_backup(runtime, bset, extra_args=extra, name_hint=f"wizard-{bset.name}")
            except RunError as err:
                print(f"[rrbackup] Backup failed: {err}")

        if choice == 2 and prompt_bool("Apply retention immediately?", default=True):
            try:
                run_forget_prune(runtime)
                print("Retention applied successfully.")
            except RunError as err:
                print(f"[rrbackup] Retention operation failed: {err}")

    # ------------------------------------------------------------------ helpers
    def _ensure_tool(self, tool: str, *, current: str, install_commands: Iterable[list[str]]) -> str:
        candidate = current or tool
        while True:
            resolved = shutil.which(candidate)
            if resolved:
                print(f"[OK] Found {tool}: {resolved}")
                self._show_tool_version(candidate)
                return candidate

            print(f"[WARN] {tool} not found on PATH ({candidate}).")
            choice = prompt_choice(
                f"Install {tool}?",
                [
                    "Attempt automatic install",
                    "Enter custom path",
                    "Skip (I'll handle manually)",
                ],
                default_index=0,
            )
            if choice == 2:
                return candidate
            if choice == 1:
                candidate = prompt_text(f"Path to {tool}", required=True)
                continue
            if choice == 0:
                if self._attempt_install(install_commands):
                    candidate = tool
                else:
                    print(f"[rrbackup] Automatic installation failed. You can install {tool} manually.")
                    candidate = prompt_text(f"Path to {tool}", required=True)

    def _attempt_install(self, commands: Iterable[list[str]]) -> bool:
        for cmd in commands:
            print(f"Running: {' '.join(cmd)}")
            try:
                result = _run_command(cmd)
            except FileNotFoundError:
                print(f"[rrbackup] Command not available: {cmd[0]}")
                return False
            if result.returncode != 0:
                print(result.stderr.strip())
                return False
        return True

    def _restic_install_commands(self) -> list[list[str]]:
        if self.platform == "windows":
            return [["winget", "install", "-e", "--id", "restic.restic"]]
        if self.platform == "linux":
            return [["sudo", "apt", "update"], ["sudo", "apt", "install", "-y", "restic"]]
        if self.platform == "termux":
            return [["pkg", "install", "-y", "restic"]]
        return []

    def _rclone_install_commands(self) -> list[list[str]]:
        if self.platform == "windows":
            return [["winget", "install", "-e", "--id", "Rclone.Rclone"]]
        if self.platform == "linux":
            return [["sudo", "apt", "update"], ["sudo", "apt", "install", "-y", "rclone"]]
        if self.platform == "termux":
            return [["pkg", "install", "-y", "rclone"]]
        return []

    def _show_tool_version(self, tool: str) -> None:
        try:
            result = _run_command([tool, "version"])
        except Exception:
            return
        if result.stdout:
            print("  " + result.stdout.splitlines()[0])

    def _configure_gdrive_repository(self) -> str:
        remote = prompt_text("rclone remote name", default="gdrive", required=True)
        path = prompt_text("Remote path", default="/backups/rrbackup", required=True).lstrip("/")
        url = f"rclone:{remote}:{path}"
        self._verify_rclone_remote(remote, path)
        return url

    def _configure_local_repository(self) -> str:
        default = str(Path.home() / "rrbackup" / "repo")
        target = Path(os.path.expanduser(prompt_text("Local repository path", default=default, required=True)))
        target.mkdir(parents=True, exist_ok=True)
        return str(target)

    def _verify_rclone_remote(self, remote: str, repo_path: str) -> None:
        print(f"Verifying rclone remote '{remote}:' ...")
        try:
            about = _run_command([self.settings.rclone_bin, "about", f"{remote}:"], capture=True)
        except FileNotFoundError:
            print("[rrbackup] rclone not available; skipping remote verification.")
            return
        if about.returncode != 0:
            print(f"[warn] rclone about failed: {about.stderr.strip()}")
            if prompt_bool("Attempt to reconnect remote now?", default=True):
                _run_command([self.settings.rclone_bin, "config", "reconnect", f"{remote}:"], capture=False)
        else:
            print(about.stdout.strip() or "Remote reachable.")

        mkdir = _run_command([self.settings.rclone_bin, "mkdir", f"{remote}:{repo_path}"])
        if mkdir.returncode != 0:
            print(f"[warn] Unable to ensure remote path exists: {mkdir.stderr.strip()}")
        else:
            print("Verified remote path exists (or was created).")

    def _print_rclone_help(self) -> None:
        print(
            "\nTo configure Google Drive:\n"
            "  1. Run `rclone config`\n"
            "  2. Choose 'n' for a new remote and give it a name (e.g., gdrive)\n"
            "  3. Select storage 'drive' and follow the OAuth prompts\n"
            "  4. Verify with `rclone ls gdrive:`\n"
        )

    def _secure_password_file(self, path: Path) -> None:
        if self.platform == "windows":
            try:
                user = os.getlogin()
                _run_command(["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:R", "/c"], capture=False)
            except Exception:
                print("[warn] Unable to harden password file automatically. Adjust permissions manually if needed.")
        else:
            try:
                os.chmod(path, 0o600)
            except PermissionError:
                print("[warn] Unable to chmod password file. Please set permissions manually.")

    def _expanded_settings(self) -> Settings:
        if not self.expanded_settings:
            self.expanded_settings = self.settings.expand()
        return self.expanded_settings

    def _review_summary(self) -> str:
        repo_url = self.settings.repo.url if self.settings.repo else "(not configured)"
        password_file = self.settings.repo.password_file if self.settings.repo else "(not configured)"
        retention = self.settings.retention_defaults
        retention_summary = (
            f"keep_last={retention.keep_last}, keep_daily={retention.keep_daily}, keep_weekly={retention.keep_weekly}, "
            f"keep_monthly={retention.keep_monthly}, keep_yearly={retention.keep_yearly}, max_total_size={retention.max_total_size or 'unlimited'}"
        )
        sets_summary = "\n".join(
            f"  • {b.name}: include {len(b.include)} path(s), schedule={b.schedule.description if b.schedule.description else b.schedule.type}"
            for b in self.settings.sets
        ) or "  • No backup sets defined"
        return textwrap.dedent(
            f"""
            Repository: {repo_url}
            Password file: {password_file}
            State dir: {self.settings.state_dir}
            Log dir: {self.settings.log_dir or '(state/logs)'}
            Retention defaults: {retention_summary}
            Backup sets:
{sets_summary}
            """
        ).strip()

    def _step_review_and_save(self) -> bool:
        print("\n-- Review configuration --")
        print(self._review_summary())
        if not prompt_bool("Save configuration?", default=True):
            return False
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        save_config(self.settings, self.config_path, overwrite=True)
        print(f"Configuration saved to {self.config_path}")
        return True

    def _select_scheduler(self) -> str:
        if self.platform == "windows":
            return "windows"

        options: list[str] = []
        labels: list[str] = []
        if shutil.which("systemctl"):
            options.append("systemd")
            labels.append("systemd user timers")
        if shutil.which("crontab"):
            options.append("cron")
            labels.append("cron (crontab)")

        if self.platform == "termux":
            options = ["cron"]
            labels = ["cron (Termux cronie)"]

        if not options:
            print("[warn] No scheduler detected. You can configure scheduling manually later.")
            return "skip"

        selection = prompt_choice(
            "Choose scheduler:",
            [f"Use {label}" for label in labels] + ["Skip scheduler setup"],
            default_index=0,
        )
        if selection == len(labels):
            return "skip"
        return options[selection]

    def _install_windows_task(self, bset: BackupSet) -> None:
        schedule = bset.schedule
        task_name = f"RRBackup\\{_sanitize_name(bset.name)}"
        hour, minute = _parse_time_value(schedule.time)
        command = (
            f"{_shlex_quote(sys.executable)} -m rrbackup.cli --config {_shlex_quote(str(self.config_path))} "
            f"backup --set {_shlex_quote(bset.name)}"
        )
        args = ["schtasks", "/Create", "/TN", task_name, "/TR", command, "/F"]
        if schedule.type == "hourly" and schedule.interval_hours:
            args += ["/SC", "HOURLY", "/MO", str(max(1, schedule.interval_hours))]
        elif schedule.type == "weekly" and schedule.day_of_week:
            args += ["/SC", "WEEKLY", "/D", schedule.day_of_week[:3], "/ST", f"{hour}:{minute}"]
        elif schedule.type == "monthly" and schedule.day_of_month:
            args += ["/SC", "MONTHLY", "/D", str(schedule.day_of_month), "/ST", f"{hour}:{minute}"]
        else:
            args += ["/SC", "DAILY", "/ST", f"{hour}:{minute}"]
        result = _run_command(args)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "schtasks failed")
        print(f"Installed Windows Task Scheduler job: {task_name}")

    def _systemd_paths(self) -> tuple[Path, Path]:
        config_dir = Path.home() / ".config" / "systemd" / "user"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir, Path.home()

    def _install_systemd_timer(self, bset: BackupSet) -> None:
        config_dir, _ = self._systemd_paths()
        unit_name = f"rrbackup-{_sanitize_name(bset.name)}"
        service_path = config_dir / f"{unit_name}.service"
        timer_path = config_dir / f"{unit_name}.timer"

        exec_cmd = (
            f"{_shlex_quote(sys.executable)} -m rrbackup.cli --config {_shlex_quote(str(self.config_path))} "
            f"backup --set {_shlex_quote(bset.name)}"
        )
        service_content = textwrap.dedent(
            f"""
            [Unit]
            Description=RRBackup backup for {bset.name}

            [Service]
            Type=oneshot
            ExecStart={exec_cmd}
            """
        ).strip()
        timer_content = textwrap.dedent(
            f"""
            [Unit]
            Description=RRBackup schedule for {bset.name}

            [Timer]
            OnCalendar={self._systemd_calendar(bset.schedule)}
            Persistent=true

            [Install]
            WantedBy=timers.target
            """
        ).strip()
        service_path.write_text(service_content, encoding="utf-8")
        timer_path.write_text(timer_content, encoding="utf-8")
        _run_command(["systemctl", "--user", "daemon-reload"], capture=False)
        enable = _run_command(["systemctl", "--user", "enable", "--now", f"{unit_name}.timer"])
        if enable.returncode != 0:
            raise RuntimeError(enable.stderr.strip() or "systemctl enable failed")
        print(f"Installed systemd timer: {unit_name}.timer")

    def _systemd_calendar(self, schedule: Schedule) -> str:
        if schedule.type == "hourly" and schedule.interval_hours:
            return f"*-*-* *:00/{max(1, schedule.interval_hours)}:00"
        if schedule.type == "weekly" and schedule.day_of_week:
            hour, minute = _parse_time_value(schedule.time)
            return f"{schedule.day_of_week} {hour}:{minute}:00"
        if schedule.type == "monthly" and schedule.day_of_month:
            hour, minute = _parse_time_value(schedule.time)
            return f"*-{schedule.day_of_month:02d} {hour}:{minute}:00"
        hour, minute = _parse_time_value(schedule.time)
        return f"*-*-* {hour}:{minute}:00"

    def _install_cron_entry(self, bset: BackupSet) -> None:
        schedule = bset.schedule
        hour, minute = _parse_time_value(schedule.time)
        if schedule.type == "hourly" and schedule.interval_hours:
            cron_prefix = f"0 */{max(1, schedule.interval_hours)} * * *"
        elif schedule.type == "weekly" and schedule.day_of_week:
            cron_prefix = f"{minute} {hour} * * {self._cron_weekday(schedule.day_of_week)}"
        elif schedule.type == "monthly" and schedule.day_of_month:
            cron_prefix = f"{minute} {hour} {schedule.day_of_month} * *"
        else:
            cron_prefix = f"{minute} {hour} * * *"
        command = f"{sys.executable} -m rrbackup.cli --config {self.config_path} backup --set {_shlex_quote(bset.name)}"
        entry = f"{cron_prefix} {command} # RRBackup {bset.name}"

        print(f"Installing cron entry for set '{bset.name}'")
        existing = ""
        crontab_list = _run_command(["crontab", "-l"])
        if crontab_list.returncode == 0:
            existing = crontab_list.stdout
        lines = [line for line in existing.splitlines() if f"# RRBackup {bset.name}" not in line]
        lines.append(entry)
        content = "\n".join(line for line in lines if line.strip()) + "\n"
        process = subprocess.Popen(["crontab", "-"], stdin=subprocess.PIPE, text=True)
        process.communicate(content)
        if process.returncode != 0:
            raise RuntimeError("Failed to install cron entry.")

    def _cron_weekday(self, day: str | None) -> str:
        mapping = {
            "sunday": "0",
            "monday": "1",
            "tuesday": "2",
            "wednesday": "3",
            "thursday": "4",
            "friday": "5",
            "saturday": "6",
        }
        if not day:
            return "0"
        return mapping.get(day.lower(), "0")

    def _parse_size(self, value: str) -> tuple[str, int]:
        value = value.strip().upper()
        for suffix, multiplier in (("TB", 1024**4), ("GB", 1024**3), ("MB", 1024**2), ("KB", 1024), ("B", 1)):
            if value.endswith(suffix):
                number = float(value[:- len(suffix)].strip())
                return value, int(number * multiplier)
        return value, int(float(value))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_setup_wizard(args: argparse.Namespace) -> int:
    wizard = SetupWizard(args)
    return wizard.run()
