from __future__ import annotations

import datetime as dt
import os
import pathlib
import subprocess
import sys
import typing as t

from .config import Settings, BackupSet


class RunError(RuntimeError):
    pass


def _now_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _env_for_repo(cfg: Settings) -> dict[str, str]:
    env = os.environ.copy()
    if not cfg.repo:
        raise RunError("Repository not configured.")
    # Prefer password file if set; else env var name if provided.
    if cfg.repo.password_file:
        env["RESTIC_PASSWORD_FILE"] = os.path.expanduser(cfg.repo.password_file)
    elif cfg.repo.password_env:
        if cfg.repo.password_env not in env:
            raise RunError(
                f"Password env '{cfg.repo.password_env}' not present in environment."
            )
        env["RESTIC_PASSWORD"] = env[cfg.repo.password_env]
    return env


def _logfile(cfg: Settings, prefix: str) -> pathlib.Path:
    return pathlib.Path(cfg.log_dir) / f"{prefix}-{_now_stamp()}.log"


def _pidfile(cfg: Settings, name: str) -> pathlib.Path:
    return pathlib.Path(cfg.state_dir) / f"running-{name}.pid"


def _repo_url(cfg: Settings) -> str:
    assert cfg.repo and cfg.repo.url
    return cfg.repo.url


def run_restic(
    cfg: Settings,
    args: list[str],
    log_prefix: str,
    live_output: bool = True,
) -> int:
    """
    Run a restic command with repo credentials wired in.
    Capture output to a timestamped log file.
    """
    repo = _repo_url(cfg)
    env = _env_for_repo(cfg)

    cmd = [cfg.restic_bin, "-r", repo] + args
    log = _logfile(cfg, log_prefix)

    with log.open("wb") as f:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            text=False,
        )
        if live_output:
            # Stream to console and file
            for chunk in iter(lambda: proc.stdout.readline(), b""):
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
                f.write(chunk)
        else:
            out, _ = proc.communicate()
            f.write(out or b"")
        rc = proc.wait()
    if rc != 0:
        raise RunError(f"Command failed (rc={rc}). See log: {log}")
    return rc


def start_backup(cfg: Settings, bset: BackupSet, extra_args: list[str] | None = None, name_hint: str = "backup") -> None:
    """
    Execute a restic backup for the provided BackupSet.
    Creates a PID file while running for simple in-progress visibility.
    """
    pidfile = _pidfile(cfg, name_hint)
    try:
        pidfile.write_text(str(os.getpid()), encoding="utf-8")
        args = ["backup", "--verbose"]
        if bset.one_fs:
            args.append("--one-file-system")
        if bset.tags:
            for t in bset.tags:
                args.extend(["--tag", t])
        if bset.exclude:
            for ex in bset.exclude:
                args.extend(["--exclude", ex])
        if bset.dry_run_default:
            args.append("--dry-run")
        if extra_args:
            args.extend(extra_args)
        # Include paths last
        args.extend([os.path.expanduser(p) for p in bset.include])
        run_restic(cfg, args, log_prefix=f"backup-{bset.name}")
    finally:
        try:
            pidfile.unlink(missing_ok=True)
        except Exception:
            pass


def list_snapshots(cfg: Settings, extra_args: list[str] | None = None) -> None:
    args = ["snapshots"]
    if extra_args:
        args += extra_args
    run_restic(cfg, args, log_prefix="snapshots")


def repo_stats(cfg: Settings) -> None:
    # Show content stats in restore-size mode for practical capacity view
    run_restic(cfg, ["stats", "--mode", "restore-size"], log_prefix="stats")


def run_check(cfg: Settings) -> None:
    run_restic(cfg, ["check"], log_prefix="check")


def run_forget_prune(cfg: Settings) -> None:
    r = cfg.retention
    args: list[str] = ["forget", "--prune"]
    if r.keep_last is not None:
        args += ["--keep-last", str(r.keep_last)]
    if r.keep_hourly is not None:
        args += ["--keep-hourly", str(r.keep_hourly)]
    if r.keep_daily is not None:
        args += ["--keep-daily", str(r.keep_daily)]
    if r.keep_weekly is not None:
        args += ["--keep-weekly", str(r.keep_weekly)]
    if r.keep_monthly is not None:
        args += ["--keep-monthly", str(r.keep_monthly)]
    if r.keep_yearly is not None:
        args += ["--keep-yearly", str(r.keep_yearly)]
    run_restic(cfg, args, log_prefix="forget-prune")


def show_in_progress(cfg: Settings) -> None:
    """
    Naive view of in-progress work:
      - Show any rrbackup PID files
      - Ask restic for repo locks as additional signal
    """
    state = pathlib.Path(cfg.state_dir)
    pidfiles = list(state.glob("running-*.pid"))
    if pidfiles:
        print("rrbackup tasks in-progress:")
        for p in pidfiles:
            print(f"  {p.name} -> PID {p.read_text(encoding='utf-8').strip()}")
    else:
        print("No rrbackup PID files found.")

    print("\nrestic repo locks:")
    try:
        run_restic(cfg, ["list", "locks"], log_prefix="list-locks", live_output=True)
    except RunError as e:
        print(str(e), file=sys.stderr)
