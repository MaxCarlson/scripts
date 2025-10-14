from __future__ import annotations

import argparse
import os
import subprocess
import sys
from getpass import getpass
from pathlib import Path
from typing import Optional

from .config import (
    Repo,
    Settings,
    load_config,
    resolve_config_path,
    save_config,
    settings_to_dict,
)
from .config_cli import _build_settings_from_wizard  # type: ignore[attr-defined]
from .interactive import launch_editor, prompt_bool, prompt_choice
from .runner import RunError, run_restic

try:
    from .config import tomli_w  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - handled via dependency
    tomli_w = None


def _resolve_config(args: argparse.Namespace) -> Path:
    """Resolve the configuration path for the wizard run."""
    target = resolve_config_path(getattr(args, "config", None))
    return Path(os.path.expandvars(str(target))).expanduser()


def _render_settings(settings: Settings) -> str:
    """Return TOML representation of settings for user display."""
    if tomli_w is None:
        raise RuntimeError("tomli-w is required to display rrbackup configuration.")
    return tomli_w.dumps(settings_to_dict(settings))


def _summarise_sets(settings: Settings) -> str:
    lines = []
    for bset in settings.sets:
        lines.append(
            f"  - {bset.name}: include {len(bset.include)} path(s), "
            f"exclude {len(bset.exclude)} pattern(s), schedule={bset.schedule or 'none'}, "
            f"type={bset.backup_type}, max_snapshots={bset.max_snapshots or 'inherit'}"
        )
    return "\n".join(lines) if lines else "  (no backup sets defined)"


def _prompt_recreate_config(target: Path) -> Settings:
    """Run the interactive config wizard (reusing config_cli implementation)."""
    settings = _build_settings_from_wizard()
    save_config(settings, str(target), overwrite=True)
    return settings


def _handle_configuration_step(target: Path) -> Settings:
    """
    Ensure a configuration file exists, allowing the user to inspect, edit, or recreate it.
    """
    while True:
        if target.exists():
            settings = load_config(str(target), expand=False)
            print("\nConfiguration file detected at:", target)
            print(_summarise_sets(settings))
            choice = prompt_choice(
                "\nConfiguration options:",
                [
                    "Keep current configuration",
                    "View full TOML configuration",
                    "Edit configuration in nvim",
                    "Re-run configuration wizard",
                    "Exit setup",
                ],
                default_index=0,
            )
            if choice == 0:
                return settings
            if choice == 1:
                try:
                    print("\n" + _render_settings(settings))
                except RuntimeError as err:
                    print(f"[rrbackup] Unable to render configuration: {err}")
                continue
            if choice == 2:
                if not launch_editor(target):
                    print("You can edit the file manually with any editor of your choice.")
                continue
            if choice == 3:
                settings = _prompt_recreate_config(target)
                return settings
            raise SystemExit(1)

        print(f"\nNo configuration found at {target}.")
        choice = prompt_choice(
            "How would you like to proceed?",
            [
                "Run the rrbackup configuration wizard",
                "Open nvim to create/edit the config manually",
                "Exit setup",
            ],
            default_index=0,
        )
        if choice == 0:
            settings = _prompt_recreate_config(target)
            return settings
        if choice == 1:
            if not launch_editor(target):
                print(f"[rrbackup] Unable to launch editor. Please create {target} manually.")
            continue
        raise SystemExit(1)


def _ensure_password_file(repo: Repo, *, overwrite: bool = False) -> None:
    if not repo.password_file:
        return

    password_path = Path(os.path.expanduser(repo.password_file))
    password_path.parent.mkdir(parents=True, exist_ok=True)

    if password_path.exists() and not overwrite:
        print(f"Password file already exists at {password_path}.")
        return

    while True:
        pwd = getpass("Enter restic repository password: ")
        confirm = getpass("Confirm password: ")
        if pwd != confirm:
            print("Passwords do not match. Try again.")
            continue
        password_path.write_text(pwd, encoding="utf-8")
        print(f"Password file written to {password_path}.")
        break


def _handle_password_step(settings: Settings) -> None:
    repo = settings.repo
    if not repo:
        print("[rrbackup] Repository details not configured yet; skipping password setup.")
        return

    if repo.password_file:
        password_path = Path(os.path.expanduser(repo.password_file))
        exists = password_path.exists()
        while True:
            status = "exists" if exists else "missing"
            choice = prompt_choice(
                f"\nPassword file ({password_path}) currently {status}. Choose an option:",
                [
                    "Keep current password file" if exists else "Create password file now",
                    "Overwrite password file using secure prompt",
                    "Open password file in nvim",
                    "Skip password setup for now",
                ],
                default_index=0,
            )
            if choice == 0:
                if not exists:
                    _ensure_password_file(repo, overwrite=False)
                return
            if choice == 1:
                _ensure_password_file(repo, overwrite=True)
                return
            if choice == 2:
                if not launch_editor(password_path):
                    print(f"[rrbackup] Please edit {password_path} manually.")
                exists = password_path.exists()
                continue
            print("Skipping password file setup. Ensure RESTIC_PASSWORD_FILE is configured before taking backups.")
            return
    elif repo.password_env:
        print(
            f"\nThe configuration uses the environment variable '{repo.password_env}' for the restic password.\n"
            "Ensure this variable is set in the environment of any scheduled tasks or shells that invoke rrbackup."
        )
        if prompt_bool("Would you like to see guidance on setting environment variables?", default=False):
            print(
                "\nExamples:\n"
                "  PowerShell (session): $env:RESTIC_PASSWORD = 'your-password'\n"
                "  Windows permanent (User): setx RESTIC_PASSWORD \"your-password\"\n"
                "  Linux/macOS shell: export RESTIC_PASSWORD='your-password'\n"
            )
    else:
        print(
            "\nNo password configuration detected. Restic requires either a password file or password environment "
            "variable. You can update the config later with `rrb config set --password-file`."
        )


def _rclone_config_path() -> Path:
    if os.name == "nt":
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
        return Path(appdata) / "rclone" / "rclone.conf"
    return Path.home() / ".config" / "rclone" / "rclone.conf"


def _run_rclone_command(cmd: list[str]) -> int:
    try:
        proc = subprocess.run(cmd, check=False)
        return proc.returncode
    except FileNotFoundError:
        print("[rrbackup] rclone executable not found. Install rclone or adjust the binary path.")
        return 127


def _handle_rclone_step(settings: Settings) -> None:
    repo = settings.repo
    if not repo:
        return

    url = repo.url
    if not url.startswith("rclone:"):
        print("\nRepository does not use an rclone remote; skipping rclone configuration.")
        return

    spec = url[len("rclone:") :]
    if ":" in spec:
        remote_name, remote_path = spec.split(":", 1)
    else:
        remote_name, remote_path = spec, ""

    print(f"\nRepository uses rclone remote '{remote_name}' with path '{remote_path}'.")

    while True:
        remotes_output = ""
        rc = _run_rclone_command([settings.rclone_bin, "listremotes"])
        if rc == 0:
            try:
                capture = subprocess.run(
                    [settings.rclone_bin, "listremotes"],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                remotes_output = capture.stdout.strip()
            except Exception:
                pass

        remote_present = remote_name + ":" in remotes_output
        status = "available" if remote_present else "not detected"

        choice = prompt_choice(
            f"Rclone remote '{remote_name}' is currently {status}. What would you like to do?",
            [
                "Continue (I'll verify manually later)" if remote_present else "Configure now",
                "Run `rclone config reconnect` for this remote",
                "Open rclone config in nvim",
                "View detailed instructions",
                "Skip rclone setup",
            ],
            default_index=0 if remote_present else 1,
        )

        if choice == 0:
            if remote_present:
                return
            print("Remote still missing; please ensure rclone is configured.")
            continue

        if choice == 1:
            print("Launching `rclone config reconnect`. Follow the prompts in the terminal window.")
            _run_rclone_command([settings.rclone_bin, "config", "reconnect", f"{remote_name}:"])
            continue

        if choice == 2:
            cfg_path = _rclone_config_path()
            if not launch_editor(cfg_path):
                print(f"[rrbackup] Unable to open {cfg_path}.")
            continue

        if choice == 3:
            print(
                "\nTo configure Google Drive with rclone:\n"
                "  1. Run `rclone config`.\n"
                "  2. Choose 'n' for a new remote and enter a name (e.g., gdrive).\n"
                "  3. Select storage 'drive'.\n"
                "  4. Follow the OAuth prompts. When complete, the remote will appear in rclone.conf.\n"
                "  5. Use `rclone ls <remote>:` to verify connectivity.\n"
            )
            continue

        print("Skipping rclone setup for now.")
        return


def _handle_restic_initialisation(cfg: Settings) -> None:
    print("\nRestic repository initialization")
    while True:
        options = [
            "Check repository connectivity (restic snapshots)",
            "Initialize repository (restic init)",
            "Skip restic setup",
        ]
        choice = prompt_choice(
            f"Repository URL: {cfg.repo.url if cfg.repo else 'not configured'}. Choose an action:",
            options,
            default_index=0,
        )
        if choice == 2:
            print("Skipping restic setup for now.")
            return

        cmd = ["snapshots"] if choice == 0 else ["init"]
        action = "Checking repository snapshots..." if choice == 0 else "Initializing repository..."
        print(action)
        try:
            run_restic(cfg, cmd, log_prefix="setup", live_output=True)
            print("Success.")
        except RunError as err:
            print(f"[rrbackup] Restic command failed: {err}")
        if choice == 0:
            continue
        return


def run_setup_wizard(args: argparse.Namespace) -> int:
    """Interactive setup wizard for rrbackup."""
    target = _resolve_config(args)
    print("=== rrbackup Setup Wizard ===")
    print("This guided wizard will help you configure rrbackup, including configuration, passwords, rclone, and restic.")

    settings = _handle_configuration_step(target)
    # Reload expanded settings to ensure directories exist for subsequent steps.
    cfg = load_config(str(target), expand=True)

    _handle_password_step(cfg)
    _handle_rclone_step(cfg)

    if cfg.repo:
        _handle_restic_initialisation(cfg)
    else:
        print("\nRepository URL not configured. Configure repository before attempting backups.")

    print("\nSetup wizard complete. You can rerun `rrb setup --wizard` anytime to revisit these steps.")
    return 0
