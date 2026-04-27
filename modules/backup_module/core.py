from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

try:
    import psutil
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "The 'psutil' package is required. Install it with: uv pip install psutil"
    ) from exc


UTC = timezone.utc

DEFAULT_REPOSITORY = r"B:\ResticRepos\PC-Local"
DEFAULT_PASSWORD_FILE = r"C:\BackupConfig\restic-local-password.txt"
DEFAULT_SOURCES_FILE = r"C:\BackupConfig\local-sources.txt"
DEFAULT_EXCLUDES_FILE = r"C:\BackupConfig\local-excludes.txt"
DEFAULT_STATUS_FILE = r"C:\BackupConfig\local-backup-status.json"
DEFAULT_LOG_FILE = r"C:\BackupConfig\local-backup.log"
DEFAULT_LOCK_FILE = r"C:\BackupConfig\local-backup.lock"
DEFAULT_CONFIG_PATH = r"C:\BackupConfig\local_backup_config.json"
DEFAULT_TAG = "local-main"
DEFAULT_RESTIC_EXECUTABLE = "restic"
DEFAULT_RESTORE_ROOT = r"B:\ResticRestore"


def utc_now() -> datetime:
    return datetime.now(UTC)


def local_now() -> datetime:
    return datetime.now().astimezone()


def to_iso8601(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def from_iso8601(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def is_windows_drive_path(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", value))


def is_unc_path(value: str) -> bool:
    return value.startswith("\\\\")


def is_probably_remote_repository(value: str) -> bool:
    if is_windows_drive_path(value) or is_unc_path(value):
        return False
    return ":" in value


def expand_user_vars(raw_value: str) -> str:
    return os.path.expandvars(os.path.expanduser(raw_value))


def resolve_config_path(
    base_dir: Path,
    raw_value: Optional[str],
    *,
    allow_remote: bool = False,
) -> Optional[str]:
    if raw_value is None or raw_value == "":
        return raw_value

    expanded = expand_user_vars(raw_value)

    if allow_remote and is_probably_remote_repository(expanded):
        return expanded

    if is_windows_drive_path(expanded) or is_unc_path(expanded):
        return str(Path(expanded))

    path = Path(expanded)
    if path.is_absolute():
        return str(path)

    return str((base_dir / path).resolve())


def default_state_dir() -> Path:
    env_value = os.environ.get("BACKUP_MODULE_STATE_DIR")
    if env_value:
        return Path(expand_user_vars(env_value)).resolve()
    return Path(DEFAULT_STATUS_FILE).parent


def default_config_candidates() -> list[Path]:
    return [
        Path(expand_user_vars(DEFAULT_CONFIG_PATH)),
        Path.cwd() / "local_backup_config.json",
        Path.cwd() / "backup_config.json",
        Path.cwd() / "backup_module_config.json",
    ]


def resolve_default_config_path(raw_config_path: Optional[str]) -> Path:
    if raw_config_path:
        return Path(expand_user_vars(raw_config_path)).resolve()

    env_value = os.environ.get("BACKUP_MODULE_CONFIG")
    if env_value:
        return Path(expand_user_vars(env_value)).resolve()

    for candidate in default_config_candidates():
        if candidate.exists():
            return candidate.resolve()

    return Path(expand_user_vars(DEFAULT_CONFIG_PATH))


def env_or_default(env_name: str, default_value: str) -> str:
    return expand_user_vars(os.environ.get(env_name, default_value))


def default_restore_target(default_restore_root: str = DEFAULT_RESTORE_ROOT) -> str:
    stamp = local_now().strftime("%Y%m%d-%H%M%S")
    root = Path(expand_user_vars(default_restore_root))
    return str(root / f"restore-{stamp}")


@dataclass
class BackupConfig:
    repository: str = field(
        default_factory=lambda: env_or_default(
            "BACKUP_MODULE_REPOSITORY", DEFAULT_REPOSITORY
        )
    )
    password_file: str = field(
        default_factory=lambda: env_or_default(
            "BACKUP_MODULE_PASSWORD_FILE", DEFAULT_PASSWORD_FILE
        )
    )
    sources_file: Optional[str] = field(
        default_factory=lambda: env_or_default(
            "BACKUP_MODULE_SOURCES_FILE", DEFAULT_SOURCES_FILE
        )
    )
    excludes_file: Optional[str] = field(
        default_factory=lambda: env_or_default(
            "BACKUP_MODULE_EXCLUDES_FILE", DEFAULT_EXCLUDES_FILE
        )
    )
    status_file: str = field(
        default_factory=lambda: env_or_default(
            "BACKUP_MODULE_STATUS_FILE", DEFAULT_STATUS_FILE
        )
    )
    log_file: str = field(
        default_factory=lambda: env_or_default(
            "BACKUP_MODULE_LOG_FILE", DEFAULT_LOG_FILE
        )
    )
    lock_file: str = field(
        default_factory=lambda: env_or_default(
            "BACKUP_MODULE_LOCK_FILE", DEFAULT_LOCK_FILE
        )
    )
    tag: Optional[str] = field(
        default_factory=lambda: os.environ.get("BACKUP_MODULE_TAG", DEFAULT_TAG)
    )
    restic_executable: str = field(
        default_factory=lambda: os.environ.get(
            "BACKUP_MODULE_RESTIC_EXECUTABLE", DEFAULT_RESTIC_EXECUTABLE
        )
    )
    default_restore_root: str = field(
        default_factory=lambda: env_or_default(
            "BACKUP_MODULE_DEFAULT_RESTORE_ROOT", DEFAULT_RESTORE_ROOT
        )
    )
    use_fs_snapshot: bool = True
    exclude_caches: bool = True
    dry_run: bool = False
    not_backup_days: float = 3.0
    min_cpu_cutoff: float = 25.0
    max_cpu_cutoff: float = 85.0
    cpu_sample_seconds: float = 5.0
    cpu_check_interval_seconds: float = 300.0
    max_wait_minutes: float = 60.0
    extra_backup_args: list[str] = field(default_factory=list)

    @classmethod
    def from_json_file(cls, config_path: str | Path) -> "BackupConfig":
        path = Path(config_path).expanduser().resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        base_dir = path.parent
        default_config = cls()

        repository = resolve_config_path(
            base_dir,
            data.get("repository", default_config.repository),
            allow_remote=True,
        )
        password_file = resolve_config_path(
            base_dir, data.get("password_file", default_config.password_file)
        )
        sources_file = resolve_config_path(
            base_dir, data.get("sources_file", default_config.sources_file)
        )
        excludes_file = resolve_config_path(
            base_dir, data.get("excludes_file", default_config.excludes_file)
        )
        status_file = resolve_config_path(
            base_dir, data.get("status_file", default_config.status_file)
        )
        log_file = resolve_config_path(
            base_dir, data.get("log_file", default_config.log_file)
        )
        lock_file = resolve_config_path(
            base_dir, data.get("lock_file", default_config.lock_file)
        )
        default_restore_root = resolve_config_path(
            base_dir,
            data.get("default_restore_root", default_config.default_restore_root),
        )

        if repository is None:
            raise ValueError("Config field 'repository' is required.")
        if password_file is None:
            raise ValueError("Config field 'password_file' is required.")
        if status_file is None:
            raise ValueError("Config field 'status_file' resolved to None.")
        if log_file is None:
            raise ValueError("Config field 'log_file' resolved to None.")
        if lock_file is None:
            raise ValueError("Config field 'lock_file' resolved to None.")
        if default_restore_root is None:
            raise ValueError("Config field 'default_restore_root' resolved to None.")

        config = cls(
            repository=repository,
            password_file=password_file,
            sources_file=sources_file,
            excludes_file=excludes_file,
            status_file=status_file,
            log_file=log_file,
            lock_file=lock_file,
            tag=data.get("tag", default_config.tag),
            restic_executable=data.get(
                "restic_executable", default_config.restic_executable
            ),
            default_restore_root=default_restore_root,
            use_fs_snapshot=bool(data.get("use_fs_snapshot", True)),
            exclude_caches=bool(data.get("exclude_caches", True)),
            dry_run=bool(data.get("dry_run", False)),
            not_backup_days=float(data.get("not_backup_days", 3.0)),
            min_cpu_cutoff=float(data.get("min_cpu_cutoff", 25.0)),
            max_cpu_cutoff=float(data.get("max_cpu_cutoff", 85.0)),
            cpu_sample_seconds=float(data.get("cpu_sample_seconds", 5.0)),
            cpu_check_interval_seconds=float(
                data.get("cpu_check_interval_seconds", 300.0)
            ),
            max_wait_minutes=float(data.get("max_wait_minutes", 60.0)),
            extra_backup_args=list(data.get("extra_backup_args", [])),
        )
        config.validate()
        return config

    @classmethod
    def minimal(
        cls,
        *,
        repository: str,
        password_file: str,
        restic_executable: str = DEFAULT_RESTIC_EXECUTABLE,
    ) -> "BackupConfig":
        return cls(
            repository=repository,
            password_file=password_file,
            restic_executable=restic_executable,
        )

    def validate(self) -> None:
        if not self.repository:
            raise ValueError("repository is required.")
        if not self.password_file:
            raise ValueError("password_file is required.")
        if self.not_backup_days < 0:
            raise ValueError("not_backup_days must be >= 0.")
        if self.min_cpu_cutoff < 0 or self.max_cpu_cutoff < 0:
            raise ValueError("CPU cutoff values must be >= 0.")
        if self.min_cpu_cutoff > 100 or self.max_cpu_cutoff > 100:
            raise ValueError("CPU cutoff values must be <= 100.")
        if self.min_cpu_cutoff > self.max_cpu_cutoff:
            raise ValueError("min_cpu_cutoff cannot be greater than max_cpu_cutoff.")
        if self.cpu_sample_seconds <= 0:
            raise ValueError("cpu_sample_seconds must be > 0.")
        if self.cpu_check_interval_seconds <= 0:
            raise ValueError("cpu_check_interval_seconds must be > 0.")
        if self.max_wait_minutes < 0:
            raise ValueError("max_wait_minutes must be >= 0.")

    def ensure_runtime_paths(self) -> None:
        for raw_path in [self.status_file, self.log_file, self.lock_file]:
            Path(raw_path).parent.mkdir(parents=True, exist_ok=True)

    def require_repository_input_files(self) -> None:
        password_path = Path(self.password_file)
        if not password_path.exists():
            raise FileNotFoundError(f"Password file does not exist: {password_path}")

    def require_backup_input_files(self) -> None:
        self.require_repository_input_files()

        if not self.sources_file:
            raise ValueError(
                "sources_file is required for the backup subcommand. "
                "Set it in the config or pass --sources_file."
            )

        sources_path = Path(self.sources_file)
        if not sources_path.exists():
            raise FileNotFoundError(f"Sources file does not exist: {sources_path}")

        if self.excludes_file:
            exclude_path = Path(self.excludes_file)
            if not exclude_path.exists():
                raise FileNotFoundError(f"Exclude file does not exist: {exclude_path}")


@dataclass
class RunDecision:
    should_run: bool
    cpu_percent: float
    threshold_used: float
    overdue_mode: bool
    days_since_success: Optional[float]
    reason: str


class AlreadyRunningError(RuntimeError):
    pass


class ProcessLock:
    def __init__(self, lock_path: str | Path) -> None:
        self.lock_path = Path(lock_path)
        self.acquired = False

    def acquire(self) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        while True:
            try:
                fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    payload = {
                        "pid": os.getpid(),
                        "acquired_utc": to_iso8601(utc_now()),
                    }
                    json.dump(payload, handle, indent=4)
                    handle.write("\n")
                self.acquired = True
                return
            except FileExistsError:
                existing = self._read_existing_payload()
                pid = existing.get("pid")
                if isinstance(pid, int) and psutil.pid_exists(pid):
                    raise AlreadyRunningError(
                        f"Another backup process appears to be running with PID {pid}. "
                        f"Lock file: {self.lock_path}"
                    )
                self._remove_stale_lock()

    def release(self) -> None:
        if not self.acquired:
            return

        try:
            self.lock_path.unlink(missing_ok=True)
        finally:
            self.acquired = False

    def _read_existing_payload(self) -> dict[str, Any]:
        try:
            return json.loads(self.lock_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _remove_stale_lock(self) -> None:
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            return


def read_status(status_path: str | Path) -> dict[str, Any]:
    path = Path(status_path)
    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_status(status_path: str | Path, payload: dict[str, Any]) -> None:
    path = Path(status_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, indent=4, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def get_last_success_time(status_payload: dict[str, Any]) -> Optional[datetime]:
    raw_value = status_payload.get("last_success_utc")
    if not raw_value:
        return None

    try:
        return from_iso8601(raw_value)
    except Exception:
        return None


def days_since(
    last_success: Optional[datetime], now: Optional[datetime] = None
) -> Optional[float]:
    if last_success is None:
        return None

    if now is None:
        now = utc_now()

    delta = now - last_success
    return delta.total_seconds() / 86400.0


def measure_cpu_percent(sample_seconds: float) -> float:
    return float(psutil.cpu_percent(interval=sample_seconds))


def evaluate_run_decision(
    config: BackupConfig,
    last_success: Optional[datetime],
    cpu_percent: float,
) -> RunDecision:
    age_days = days_since(last_success)
    overdue_mode = age_days is None or age_days >= config.not_backup_days
    threshold = config.max_cpu_cutoff if overdue_mode else config.min_cpu_cutoff
    should_run = cpu_percent <= threshold

    if age_days is None:
        age_text = "No prior successful backup is recorded."
    else:
        age_text = f"Last successful backup was {age_days:.2f} day(s) ago."

    if should_run:
        reason = (
            f"{age_text} Current CPU usage is {cpu_percent:.2f}%, "
            f"which is within the allowed threshold of {threshold:.2f}%."
        )
    else:
        mode_text = "overdue fallback" if overdue_mode else "normal"
        reason = (
            f"{age_text} Current CPU usage is {cpu_percent:.2f}%, "
            f"which is above the {mode_text} threshold of {threshold:.2f}%."
        )

    return RunDecision(
        should_run=should_run,
        cpu_percent=cpu_percent,
        threshold_used=threshold,
        overdue_mode=overdue_mode,
        days_since_success=age_days,
        reason=reason,
    )


def wait_for_backup_window(
    config: BackupConfig,
    last_success: Optional[datetime],
    *,
    verbose: bool = False,
) -> RunDecision:
    deadline = utc_now() + timedelta(minutes=config.max_wait_minutes)

    while True:
        cpu_percent = measure_cpu_percent(config.cpu_sample_seconds)
        decision = evaluate_run_decision(config, last_success, cpu_percent)

        if verbose:
            print(decision.reason)

        if decision.should_run:
            return decision

        if utc_now() >= deadline:
            return decision

        remaining_seconds = max(0.0, (deadline - utc_now()).total_seconds())
        sleep_seconds = min(config.cpu_check_interval_seconds, remaining_seconds)
        if sleep_seconds <= 0:
            return decision

        if verbose:
            print(f"Waiting {sleep_seconds:.0f} second(s) before checking CPU again.")
        time.sleep(sleep_seconds)


def base_restic_command(config: BackupConfig) -> list[str]:
    return [
        config.restic_executable,
        "-r",
        config.repository,
        "--password-file",
        config.password_file,
    ]


def build_restic_backup_command(config: BackupConfig) -> list[str]:
    command = base_restic_command(config)
    command.append("backup")

    if config.use_fs_snapshot:
        command.append("--use-fs-snapshot")

    if not config.sources_file:
        raise ValueError("sources_file is required to build a restic backup command.")

    command.extend(
        [
            "--files-from-verbatim",
            config.sources_file,
        ]
    )

    if config.excludes_file:
        command.extend(["--iexclude-file", config.excludes_file])

    if config.exclude_caches:
        command.append("--exclude-caches")

    if config.tag:
        command.extend(["--tag", config.tag])

    if config.dry_run:
        command.append("--dry-run")

    command.extend(config.extra_backup_args)
    return command


def build_snapshots_command(
    config: BackupConfig,
    *,
    tags: Sequence[str] = (),
    host: Optional[str] = None,
    json_output: bool = False,
    compact: bool = False,
) -> list[str]:
    command = base_restic_command(config)
    command.append("snapshots")

    for tag in tags:
        command.extend(["--tag", tag])

    if host:
        command.extend(["--host", host])

    if json_output:
        command.append("--json")

    if compact:
        command.append("--compact")

    return command


def build_ls_command(
    config: BackupConfig,
    *,
    snapshot_id: str,
    path: Optional[str] = None,
    json_output: bool = False,
) -> list[str]:
    command = base_restic_command(config)
    command.extend(["ls", snapshot_id])

    if path:
        command.append(to_restic_path(path))

    if json_output:
        command.append("--json")

    return command


def build_find_command(
    config: BackupConfig,
    *,
    patterns: Sequence[str],
    snapshot_id: Optional[str] = None,
    ignore_case: bool = False,
    json_output: bool = False,
) -> list[str]:
    if not patterns:
        raise ValueError("At least one search pattern is required.")

    command = base_restic_command(config)
    command.append("find")

    if snapshot_id:
        command.extend(["-s", snapshot_id])

    if ignore_case:
        command.append("-i")

    if json_output:
        command.append("--json")

    command.extend(patterns)
    return command


def to_restic_path(raw_value: str) -> str:
    value = raw_value.strip().strip('"').strip("'")

    if is_windows_drive_path(value):
        drive = value[0].upper()
        rest = value[2:].replace("\\", "/").lstrip("/")
        if rest:
            return f"/{drive}/{rest}".rstrip("/")
        return f"/{drive}"

    if value.startswith("/"):
        return value.replace("\\", "/").rstrip("/")

    return value.replace("\\", "/").rstrip("/")


def looks_like_path(raw_value: str) -> bool:
    value = raw_value.strip().strip('"').strip("'")
    return (
        is_windows_drive_path(value)
        or value.startswith("/")
        or value.startswith(".")
        or "\\" in value
        or "/" in value
        or "*" in value
        or "?" in value
    )


def unique_preserving_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []

    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)

    return result


def expand_restore_include_values(
    include_paths: Sequence[str],
    include_patterns: Sequence[str],
) -> list[str]:
    expanded: list[str] = []

    for raw_value in include_paths:
        value = raw_value.strip().strip('"').strip("'")
        if not value:
            continue

        if looks_like_path(value):
            restic_path = to_restic_path(value)
        else:
            restic_path = f"**/{value}"

        expanded.append(restic_path)
        expanded.append(f"{restic_path}/**")

    for raw_value in include_patterns:
        value = raw_value.strip().strip('"').strip("'")
        if not value:
            continue
        expanded.append(to_restic_path(value))

    return unique_preserving_order(expanded)


def build_restore_command(
    config: BackupConfig,
    *,
    snapshot_id: str,
    target_path: str,
    include_paths: Sequence[str] = (),
    include_patterns: Sequence[str] = (),
    exclude_patterns: Sequence[str] = (),
    ignore_case: bool = True,
) -> list[str]:
    if not target_path:
        raise ValueError("target_path is required for restore.")

    command = base_restic_command(config)
    command.extend(["restore", snapshot_id, "--target", target_path])

    include_option = "--iinclude" if ignore_case else "--include"
    exclude_option = "--iexclude" if ignore_case else "--exclude"

    for include_value in expand_restore_include_values(include_paths, include_patterns):
        command.extend([include_option, include_value])

    for exclude_value in exclude_patterns:
        command.extend([exclude_option, to_restic_path(exclude_value)])

    return command


def format_command(command: Sequence[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(list(command))
    return shlex.join(command)


def append_log_line(log_path: str | Path, line: str) -> None:
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip("\n"))
        handle.write("\n")


def run_command_streaming(
    command: Sequence[str],
    *,
    log_path: Optional[str | Path] = None,
    tee_path: Optional[str | Path] = None,
) -> int:
    started = utc_now()

    if log_path is not None:
        append_log_line(
            log_path, f"[{to_iso8601(started)}] START {format_command(command)}"
        )

    tee_handle = None
    if tee_path is not None:
        tee_target = Path(tee_path)
        tee_target.parent.mkdir(parents=True, exist_ok=True)
        tee_handle = tee_target.open("w", encoding="utf-8")

    process = subprocess.Popen(
        list(command),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    try:
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="")
            if log_path is not None:
                append_log_line(log_path, line.rstrip("\n"))
            if tee_handle is not None:
                tee_handle.write(line)
        return_code = process.wait()
    except KeyboardInterrupt:
        if log_path is not None:
            append_log_line(
                log_path,
                f"[{to_iso8601(utc_now())}] INTERRUPT received. Terminating child process.",
            )
        process.terminate()
        try:
            return_code = process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            return_code = process.wait()
        raise
    finally:
        if tee_handle is not None:
            tee_handle.close()
        finished = utc_now()
        if log_path is not None:
            append_log_line(
                log_path,
                f"[{to_iso8601(finished)}] END exit_code={process.returncode}",
            )

    return return_code


def update_status_for_skip(
    config: BackupConfig,
    previous_status: dict[str, Any],
    decision: RunDecision,
) -> dict[str, Any]:
    payload = dict(previous_status)
    payload["last_attempt_utc"] = to_iso8601(utc_now())
    payload["last_result"] = "skipped"
    payload["last_reason"] = decision.reason
    payload["last_cpu_percent"] = round(decision.cpu_percent, 2)
    payload["last_threshold_used"] = round(decision.threshold_used, 2)
    payload["last_overdue_mode"] = decision.overdue_mode
    payload["last_days_since_success"] = (
        None
        if decision.days_since_success is None
        else round(decision.days_since_success, 4)
    )
    write_status(config.status_file, payload)
    return payload


def update_status_for_run_start(
    config: BackupConfig,
    previous_status: dict[str, Any],
    decision: Optional[RunDecision],
    command: Sequence[str],
) -> dict[str, Any]:
    payload = dict(previous_status)
    payload["last_attempt_utc"] = to_iso8601(utc_now())
    payload["last_result"] = "running"
    payload["last_command"] = format_command(command)

    if decision is not None:
        payload["last_reason"] = decision.reason
        payload["last_cpu_percent"] = round(decision.cpu_percent, 2)
        payload["last_threshold_used"] = round(decision.threshold_used, 2)
        payload["last_overdue_mode"] = decision.overdue_mode
        payload["last_days_since_success"] = (
            None
            if decision.days_since_success is None
            else round(decision.days_since_success, 4)
        )

    write_status(config.status_file, payload)
    return payload


def update_status_for_run_end(
    config: BackupConfig,
    previous_status: dict[str, Any],
    return_code: int,
) -> dict[str, Any]:
    payload = dict(previous_status)
    payload["last_finish_utc"] = to_iso8601(utc_now())
    payload["last_exit_code"] = int(return_code)

    if return_code == 0:
        payload["last_result"] = "success"
        payload["last_success_utc"] = payload["last_finish_utc"]
    else:
        payload["last_result"] = "failure"

    write_status(config.status_file, payload)
    return payload


def config_to_public_dict(config: BackupConfig) -> dict[str, Any]:
    return {
        "repository": config.repository,
        "password_file": config.password_file,
        "sources_file": config.sources_file,
        "excludes_file": config.excludes_file,
        "status_file": config.status_file,
        "log_file": config.log_file,
        "lock_file": config.lock_file,
        "tag": config.tag,
        "restic_executable": config.restic_executable,
        "default_restore_root": config.default_restore_root,
        "use_fs_snapshot": config.use_fs_snapshot,
        "exclude_caches": config.exclude_caches,
        "dry_run": config.dry_run,
        "not_backup_days": config.not_backup_days,
        "min_cpu_cutoff": config.min_cpu_cutoff,
        "max_cpu_cutoff": config.max_cpu_cutoff,
        "cpu_sample_seconds": config.cpu_sample_seconds,
        "cpu_check_interval_seconds": config.cpu_check_interval_seconds,
        "max_wait_minutes": config.max_wait_minutes,
        "extra_backup_args": config.extra_backup_args,
    }


def print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=4, sort_keys=True))


def load_config_with_overrides(
    args: Any, *, require_existing_config: bool = False
) -> BackupConfig:
    raw_config_path = getattr(args, "config_path", None)
    env_config_path = os.environ.get("BACKUP_MODULE_CONFIG")
    config_path = resolve_default_config_path(raw_config_path)

    repository_override = getattr(args, "repository_path", None)
    password_override = getattr(args, "password_file", None)
    restic_override = getattr(args, "restic_executable", None)

    explicit_config_requested = bool(raw_config_path or env_config_path)

    if config_path.exists():
        config = BackupConfig.from_json_file(config_path)
    elif repository_override and password_override:
        config = BackupConfig.minimal(
            repository=repository_override,
            password_file=password_override,
            restic_executable=restic_override or DEFAULT_RESTIC_EXECUTABLE,
        )
    elif require_existing_config or explicit_config_requested:
        raise FileNotFoundError(f"Config file does not exist: {config_path}")
    else:
        config = BackupConfig()

    if repository_override:
        config.repository = repository_override
    if password_override:
        config.password_file = password_override
    if restic_override:
        config.restic_executable = restic_override

    sources_override = getattr(args, "sources_file", None)
    excludes_override = getattr(args, "excludes_file", None)
    tag_override = getattr(args, "tag", None)
    restore_root_override = getattr(args, "default_restore_root", None)

    if sources_override:
        config.sources_file = sources_override
    if excludes_override:
        config.excludes_file = excludes_override
    if tag_override:
        config.tag = tag_override
    if restore_root_override:
        config.default_restore_root = restore_root_override

    config.validate()
    return config


def exit_with_error(message: str, exit_code: int = 2) -> int:
    print(message, file=sys.stderr)
    return exit_code
