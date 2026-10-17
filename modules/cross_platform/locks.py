"""Cross-platform read/write folder and file locking with PID and start-time verification."""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import socket
import sqlite3
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]

DEFAULT_LOCK_FILENAME = ".compress.lock"
OPERATION_LOCK_FILENAME = "operation.lock"
CREATE_TIME_TOLERANCE_SECONDS = 2.0
_READ_SEQ = itertools.count(1)


@dataclass(frozen=True, slots=True)
class ProcessStatus:
    """Live operating-system status of a lock holder process."""

    pid: int | None
    alive: bool
    state: str
    name: str | None = None
    cmdline: tuple[str, ...] = ()
    cwd: str | None = None
    cpu_seconds: float | None = None
    memory_rss_bytes: int | None = None
    create_time: float | None = None
    elapsed_seconds: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LockRecord:
    """Inspection result for one lock artifact or active folder process."""

    kind: str
    name: str
    path: str
    target: str
    engaged: bool
    stale: bool
    os_locked: bool | None
    mode: str
    operation: str
    holder: dict[str, Any] | None = None
    process: ProcessStatus | None = None
    auto_cleaned: bool = False
    unlockable: bool = False
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.process is not None:
            payload["process"] = self.process.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class FolderLockReport:
    """Aggregate lock status for a target directory and its owning library root."""

    target: str
    library_root: str
    engaged: bool
    write_locked: bool
    read_locked: bool
    stale_count: int
    auto_cleaned_count: int
    locks: tuple[LockRecord, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "library_root": self.library_root,
            "engaged": self.engaged,
            "write_locked": self.write_locked,
            "read_locked": self.read_locked,
            "stale_count": self.stale_count,
            "auto_cleaned_count": self.auto_cleaned_count,
            "locks": [lock.to_dict() for lock in self.locks],
        }


def _safe_resolve(path: Path) -> Path:
    try:
        return path.expanduser().resolve()
    except OSError:
        return path.expanduser().absolute()


def current_process_identity(
    *,
    operation: str = "",
    mode: str = "write",
    target: Path | str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a JSON-serializable identity record for the current process."""
    pid = os.getpid()
    create_time: float | None = None
    name = Path(sys.executable).name
    cmdline = list(sys.argv)
    cwd = ""
    try:
        cwd = str(Path.cwd())
    except OSError:
        pass
    if psutil is not None:
        try:
            proc = psutil.Process(pid)
            with proc.oneshot():
                create_time = round(float(proc.create_time()), 3)
                name = proc.name() or name
                proc_cmd = proc.cmdline()
                if proc_cmd:
                    cmdline = list(proc_cmd)
        except Exception:
            pass
    payload: dict[str, Any] = {
        "schema": 1,
        "pid": pid,
        "create_time": create_time,
        "name": name,
        "cmdline": cmdline,
        "cwd": cwd,
        "hostname": socket.gethostname(),
        "mode": mode,
        "operation": operation or (" ".join(cmdline[:3]).strip() if cmdline else name),
        "target": str(_safe_resolve(Path(target))) if target is not None else cwd,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        payload.update(extra)
    return payload


def inspect_process(
    pid: int | None,
    expected_create_time: float | None = None,
    expected_hostname: str | None = None,
) -> ProcessStatus:
    """Verify whether ``pid`` is alive and matches ``expected_create_time``."""
    if pid is None or pid <= 0:
        return ProcessStatus(pid=pid, alive=False, state="unknown")
    if expected_hostname and expected_hostname != socket.gethostname():
        return ProcessStatus(pid=pid, alive=False, state="remote_host")
    if psutil is not None:
        try:
            proc = psutil.Process(pid)
            with proc.oneshot():
                if not proc.is_running():
                    return ProcessStatus(pid=pid, alive=False, state="dead")
                raw_status = str(proc.status() or "running")
                if raw_status == getattr(psutil, "STATUS_ZOMBIE", "zombie"):
                    return ProcessStatus(pid=pid, alive=False, state="zombie")
                actual_create = round(float(proc.create_time()), 3)
                if (
                    expected_create_time is not None
                    and abs(actual_create - float(expected_create_time)) > CREATE_TIME_TOLERANCE_SECONDS
                ):
                    return ProcessStatus(
                        pid=pid,
                        alive=False,
                        state="pid_reused",
                        name=proc.name(),
                        create_time=actual_create,
                    )
                cpu = proc.cpu_times()
                cpu_seconds = round(float(getattr(cpu, "user", 0.0) + getattr(cpu, "system", 0.0)), 3)
                rss = int(getattr(proc.memory_info(), "rss", 0))
                try:
                    proc_cmd = tuple(proc.cmdline())
                except Exception:
                    proc_cmd = ()
                try:
                    proc_cwd = proc.cwd()
                except Exception:
                    proc_cwd = None
                return ProcessStatus(
                    pid=pid,
                    alive=True,
                    state=raw_status,
                    name=proc.name(),
                    cmdline=proc_cmd,
                    cwd=proc_cwd,
                    cpu_seconds=cpu_seconds,
                    memory_rss_bytes=rss,
                    create_time=actual_create,
                    elapsed_seconds=max(0.0, round(time.time() - actual_create, 1)),
                )
        except Exception:
            return ProcessStatus(pid=pid, alive=False, state="dead")
    try:
        os.kill(pid, 0)
        return ProcessStatus(pid=pid, alive=True, state="running")
    except PermissionError:
        return ProcessStatus(pid=pid, alive=True, state="running")
    except OSError:
        return ProcessStatus(pid=pid, alive=False, state="dead")


def _acquire_os_byte_lock(fileno: int) -> None:
    try:
        import msvcrt
    except ImportError:
        import fcntl

        fcntl.flock(fileno, fcntl.LOCK_EX | fcntl.LOCK_NB)
    else:
        msvcrt.locking(fileno, msvcrt.LK_NBLCK, 1)


def _release_os_byte_lock(fileno: int) -> None:
    try:
        import msvcrt
    except ImportError:
        import fcntl

        fcntl.flock(fileno, fcntl.LOCK_UN)
    else:
        msvcrt.locking(fileno, msvcrt.LK_UNLCK, 1)


def _read_offset_metadata(lock_path: Path) -> dict[str, Any] | None:
    try:
        with lock_path.open("rb", buffering=0) as handle:
            handle.seek(1)
            raw = handle.read(65536)
        if not raw:
            return None
        parsed = json.loads(raw.decode("utf-8", errors="replace").strip("\x00 \t\r\n"))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _write_offset_metadata(handle: Any, metadata: dict[str, Any]) -> None:
    try:
        encoded = json.dumps(metadata, sort_keys=True, default=str).encode("utf-8")
        handle.seek(1)
        handle.write(encoded)
        handle.truncate()
        handle.flush()
    except OSError:
        pass


def _clear_offset_metadata(handle: Any) -> None:
    try:
        handle.seek(1)
        handle.truncate(1)
        handle.flush()
    except OSError:
        pass


@contextmanager
def directory_lock(
    directory: Path,
    *,
    create: bool = True,
    filename: str = DEFAULT_LOCK_FILENAME,
    mode: str = "write",
    operation: str = "",
    target: Path | str | None = None,
) -> Iterator[None]:
    """Persistent lock inode with OS byte-0 ownership, released even on process death.

    Byte 0 holds the kernel lock; bytes 1..N store JSON holder metadata while
    locked and are truncated back to 1 byte before normal release.
    Never unlink a persistent write-lock inode: another process may already have opened it.
    """
    if Path(filename).name != filename or filename in {"", ".", ".."}:
        raise ValueError("Lock filename must be one local filename")
    lock = directory / filename
    if lock.is_symlink():
        raise RuntimeError(f"Refusing linked compression lock: {lock}")
    if not create and not lock.exists():
        yield
        return
    handle = lock.open("a+b" if create else "r+b", buffering=0)
    locked = False
    try:
        if handle.seek(0, os.SEEK_END) == 0 and create:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        handle.seek(0)
        try:
            _acquire_os_byte_lock(handle.fileno())
            locked = True
        except OSError as exc:
            holder = _read_offset_metadata(lock)
            holder_suffix = ""
            if holder and holder.get("pid"):
                proc = inspect_process(holder.get("pid"), holder.get("create_time"), holder.get("hostname"))
                op = holder.get("operation") or holder.get("mode") or "operation"
                holder_suffix = f" (held by PID {holder['pid']} [{proc.state}]: {op})"
            raise RuntimeError(
                f"Write directory is locked by another operation: {lock}{holder_suffix}. "
                "Not waiting; retry after it finishes. Do not delete the lock file."
            ) from exc
        if create:
            meta = current_process_identity(
                operation=operation,
                mode=mode,
                target=target if target is not None else directory,
            )
            _write_offset_metadata(handle, meta)
        yield
    finally:
        if locked:
            if create:
                _clear_offset_metadata(handle)
            handle.seek(0)
            _release_os_byte_lock(handle.fileno())
        handle.close()


def _external_lock_root(state_root: Path | None = None) -> Path:
    if state_root is not None:
        return _safe_resolve(state_root)
    env_dir = os.environ.get("CROSS_PLATFORM_LOCK_DIR") or os.environ.get("COMPRESSER_STATE_DIR")
    base = Path(env_dir) if env_dir else Path(os.environ.get("LOCALAPPDATA") or (Path.home() / ".cache"))
    return _safe_resolve(base) / "cross_platform" / "locks"


def external_target_lock_dir(target: Path, state_root: Path | None = None) -> Path:
    resolved = _safe_resolve(target)
    digest = hashlib.sha256(str(resolved).casefold().encode("utf-8")).hexdigest()[:24]
    return _external_lock_root(state_root) / digest


@contextmanager
def folder_read_lock(
    target: Path,
    *,
    operation: str = "read",
    state_root: Path | None = None,
    block_if_write_locked: bool = False,
    write_lock_path: Path | None = None,
) -> Iterator[Path]:
    """Hold shared read ownership; overlapping coordinated writers are always refused."""
    if block_if_write_locked and write_lock_path is not None and write_lock_path.exists():
        probe = probe_byte_range_lock(
            write_lock_path,
            target=target,
            auto_clean_stale_metadata=False,
        )
        if probe.engaged:
            holder_pid = probe.holder.get("pid") if probe.holder else None
            pid_note = f" (PID {holder_pid})" if holder_pid else ""
            raise RuntimeError(
                f"Target directory is write-locked by another operation: {write_lock_path}{pid_note}. "
                "Not waiting; retry after it finishes."
            )
    from .folder_coordination import coordinated_folder_lock

    with coordinated_folder_lock(target, mode="read", operation=operation, state_root=state_root) as slot:
        yield slot


@contextmanager
def folder_write_lock(
    target: Path,
    *,
    operation: str = "write",
    state_root: Path | None = None,
) -> Iterator[Path]:
    """Hold exclusive external ownership against overlapping readers and writers."""
    from .folder_coordination import coordinated_folder_lock

    with coordinated_folder_lock(target, mode="write", operation=operation, state_root=state_root) as slot:
        yield slot


def probe_byte_range_lock(
    lock_path: Path,
    *,
    name: str | None = None,
    kind: str = "write",
    mode: str = "write",
    target: Path | str | None = None,
    auto_clean_stale_metadata: bool = True,
) -> LockRecord:
    """Non-destructively test whether an OS byte-0 lock is currently held."""
    resolved_lock = _safe_resolve(lock_path)
    target_str = str(_safe_resolve(Path(target))) if target is not None else str(resolved_lock.parent)
    lock_name = name or resolved_lock.name
    if not resolved_lock.exists():
        return LockRecord(
            kind=kind,
            name=lock_name,
            path=str(resolved_lock),
            target=target_str,
            engaged=False,
            stale=False,
            os_locked=False,
            mode=mode,
            operation="",
            detail="lock file not present",
        )
    holder = _read_offset_metadata(resolved_lock)
    try:
        handle = resolved_lock.open("r+b", buffering=0)
    except OSError as exc:
        proc = (
            inspect_process(holder.get("pid"), holder.get("create_time"), holder.get("hostname"))
            if holder and holder.get("pid")
            else None
        )
        return LockRecord(
            kind=kind,
            name=lock_name,
            path=str(resolved_lock),
            target=holder.get("target", target_str) if holder else target_str,
            engaged=True,
            stale=False,
            os_locked=True,
            mode=holder.get("mode", mode) if holder else mode,
            operation=holder.get("operation", "") if holder else "",
            holder=holder,
            process=proc,
            detail=f"locked ({exc})",
        )
    try:
        handle.seek(0)
        try:
            _acquire_os_byte_lock(handle.fileno())
        except OSError:
            proc = (
                inspect_process(holder.get("pid"), holder.get("create_time"), holder.get("hostname"))
                if holder and holder.get("pid")
                else None
            )
            return LockRecord(
                kind=kind,
                name=lock_name,
                path=str(resolved_lock),
                target=holder.get("target", target_str) if holder else target_str,
                engaged=True,
                stale=False,
                os_locked=True,
                mode=holder.get("mode", mode) if holder else mode,
                operation=holder.get("operation", "") if holder else "",
                holder=holder,
                process=proc,
                detail="OS byte-range lock is actively held",
            )
        else:
            cleaned = False
            had_stale_meta = holder is not None
            if had_stale_meta and auto_clean_stale_metadata:
                _clear_offset_metadata(handle)
                cleaned = True
            handle.seek(0)
            _release_os_byte_lock(handle.fileno())
            proc = (
                inspect_process(holder.get("pid"), holder.get("create_time"), holder.get("hostname"))
                if holder and holder.get("pid")
                else None
            )
            return LockRecord(
                kind=kind,
                name=lock_name,
                path=str(resolved_lock),
                target=holder.get("target", target_str) if holder else target_str,
                engaged=False,
                stale=had_stale_meta and not cleaned,
                os_locked=False,
                mode=holder.get("mode", mode) if holder else mode,
                operation=holder.get("operation", "") if holder else "",
                holder=holder if not cleaned else None,
                process=proc,
                auto_cleaned=cleaned,
                unlockable=had_stale_meta and not cleaned,
                detail=(
                    "unlocked (cleaned stale holder metadata)"
                    if cleaned
                    else ("unlocked (stale holder metadata present)" if had_stale_meta else "unlocked (idle inode)")
                ),
            )
    finally:
        handle.close()


def _matches_target_path(candidate: Path, roots: Sequence[Path]) -> bool:
    resolved = _safe_resolve(candidate)
    for root in roots:
        if resolved == root or root in resolved.parents:
            return True
    return False


def discover_folder_processes(
    target: Path,
    *,
    extra_roots: Sequence[Path] = (),
    exclude_pids: Sequence[int] = (),
) -> list[LockRecord]:
    """Scan live OS processes to detect active mangadl/compresser runs on ``target``."""
    if psutil is None:
        return []
    roots = [_safe_resolve(target), *(_safe_resolve(r) for r in extra_roots)]
    ignored = {os.getpid(), *(int(p) for p in exclude_pids)}
    records: list[LockRecord] = []
    for proc in psutil.process_iter(["pid", "name", "cmdline", "cwd", "create_time", "status"]):
        try:
            info = proc.info
            pid = int(info.get("pid") or 0)
            if pid <= 0 or pid in ignored:
                continue
            cmdline = [str(part) for part in (info.get("cmdline") or ()) if part]
            if not cmdline:
                continue
            joined = " ".join(cmdline).lower()
            if not any(token in joined for token in ("mangadl", "compresser")):
                continue
            # Do not report a concurrent `mangadl lock` status inspection as an active worker.
            if "lock" in [part.lower() for part in cmdline[:3]]:
                continue
            cwd_str = info.get("cwd") or ""
            cwd_path = Path(cwd_str) if cwd_str else None
            matched_root: Path | None = None
            for idx, arg in enumerate(cmdline):
                if arg in {"-d", "--destination", "-i", "--input"} and idx + 1 < len(cmdline):
                    raw_arg = Path(cmdline[idx + 1])
                    candidate = (cwd_path / raw_arg) if (cwd_path and not raw_arg.is_absolute()) else raw_arg
                    if _matches_target_path(candidate, roots):
                        matched_root = _safe_resolve(candidate)
                        break
                elif arg.startswith(("--destination=", "--input=")):
                    raw_arg = Path(arg.split("=", 1)[1])
                    candidate = (cwd_path / raw_arg) if (cwd_path and not raw_arg.is_absolute()) else raw_arg
                    if _matches_target_path(candidate, roots):
                        matched_root = _safe_resolve(candidate)
                        break
            if matched_root is None and cwd_path is not None and _matches_target_path(cwd_path, roots):
                # Only treat cwd as a match when no explicit -d/-i pointing elsewhere was passed.
                has_explicit_other = any(
                    a in {"-d", "--destination", "-i", "--input"} or a.startswith(("--destination=", "--input="))
                    for a in cmdline
                )
                if not has_explicit_other:
                    matched_root = _safe_resolve(cwd_path)
            if matched_root is None:
                continue
            is_write = (
                any(flag in cmdline for flag in ("-w", "--write", "--apply", "-f", "run"))
                and "-l" not in cmdline
                and "--inventory-only" not in cmdline
                and "-n" not in cmdline
                and "--dry-run" not in cmdline
            )
            mode = "write" if is_write else "read"
            status = inspect_process(pid, info.get("create_time"))
            if not status.alive:
                continue
            # Deduplicate parent venv wrapper vs child python process on Windows if both have same cmdline
            records.append(
                LockRecord(
                    kind="active_process",
                    name="process",
                    path=str(matched_root),
                    target=str(matched_root),
                    engaged=True,
                    stale=False,
                    os_locked=None,
                    mode=mode,
                    operation=" ".join(cmdline),
                    holder={
                        "pid": pid,
                        "create_time": status.create_time,
                        "name": status.name,
                        "cmdline": list(status.cmdline),
                        "cwd": status.cwd,
                        "mode": mode,
                        "target": str(matched_root),
                    },
                    process=status,
                    detail="live process targeting folder",
                )
            )
        except Exception:
            continue
    # If Windows venv launcher spawns child python with identical arguments, keep the active child
    if len(records) > 1:
        by_cmd: dict[tuple[str, ...], LockRecord] = {}
        for rec in records:
            key = tuple(rec.process.cmdline[1:]) if rec.process and len(rec.process.cmdline) > 1 else (rec.operation,)
            prev = by_cmd.get(key)
            if prev is None or (
                rec.process and prev.process and (rec.process.cpu_seconds or 0) >= (prev.process.cpu_seconds or 0)
            ):
                by_cmd[key] = rec
        records = list(by_cmd.values())
    return records


def inspect_folder_locks(
    target: Path,
    *,
    library_root: Path | None = None,
    state_root: Path | None = None,
    auto_clean: bool = True,
    discover_processes: bool = True,
) -> FolderLockReport:
    """Inspect all write, read, repair, state-run, and process locks for ``target``."""
    resolved_target = _safe_resolve(target)
    resolved_root = _safe_resolve(library_root) if library_root is not None else resolved_target
    records: list[LockRecord] = []
    known_pids: set[int] = set()

    # 1. Library operation.lock (.mangadl/operation.lock)
    controls = resolved_root / ".mangadl"
    op_lock = controls / OPERATION_LOCK_FILENAME
    op_record: LockRecord | None = None
    if op_lock.exists():
        op_record = probe_byte_range_lock(
            op_lock,
            name="operation.lock",
            kind="write",
            mode="write",
            target=resolved_root,
            auto_clean_stale_metadata=auto_clean,
        )
        records.append(op_record)
        if op_record.holder and op_record.holder.get("pid"):
            known_pids.add(int(op_record.holder["pid"]))

    # 2. Target-local .compress.lock (if present)
    comp_lock = resolved_target / DEFAULT_LOCK_FILENAME
    if comp_lock.exists():
        comp_rec = probe_byte_range_lock(
            comp_lock,
            name=DEFAULT_LOCK_FILENAME,
            kind="write",
            mode="write",
            target=resolved_target,
            auto_clean_stale_metadata=auto_clean,
        )
        records.append(comp_rec)
        if comp_rec.holder and comp_rec.holder.get("pid"):
            known_pids.add(int(comp_rec.holder["pid"]))

    # 3. Scratch promotion lock (.promotion.lock) if present
    promo_lock = resolved_root / ".promotion.lock"
    if promo_lock.exists():
        promo_rec = probe_byte_range_lock(
            promo_lock,
            name=".promotion.lock",
            kind="write",
            mode="write",
            target=resolved_root,
            auto_clean_stale_metadata=auto_clean,
        )
        records.append(promo_rec)
        if promo_rec.holder and promo_rec.holder.get("pid"):
            known_pids.add(int(promo_rec.holder["pid"]))

    # New coordinated slots include ancestors/descendants and both access modes.
    from .folder_coordination import registry_records

    for coordinated in registry_records(resolved_target, state_root):
        records.append(coordinated)
        if coordinated.holder and coordinated.holder.get("pid"):
            known_pids.add(int(coordinated.holder["pid"]))

    # Legacy external shared reader slots remain inspectable during migration.
    seen_slots: set[Path] = set()
    for scope_path in (resolved_target, resolved_root):
        slot_dir = external_target_lock_dir(scope_path, state_root)
        if not slot_dir.is_dir():
            continue
        for slot_file in sorted(slot_dir.glob("read-*.lock")):
            resolved_slot = _safe_resolve(slot_file)
            if resolved_slot in seen_slots:
                continue
            seen_slots.add(resolved_slot)
            slot_rec = probe_byte_range_lock(
                resolved_slot,
                name=slot_file.name,
                kind="read",
                mode="read",
                target=scope_path,
                auto_clean_stale_metadata=auto_clean,
            )
            if not slot_rec.engaged and auto_clean:
                try:
                    resolved_slot.unlink(missing_ok=True)
                    slot_rec = LockRecord(
                        **{
                            **slot_rec.to_dict(),
                            "process": slot_rec.process,
                            "stale": False,
                            "auto_cleaned": True,
                            "unlockable": False,
                            "detail": "stale read lock slot removed",
                        }
                    )
                except OSError:
                    pass
            records.append(slot_rec)
            if slot_rec.engaged and slot_rec.holder and slot_rec.holder.get("pid"):
                known_pids.add(int(slot_rec.holder["pid"]))

    # 5. Live process discovery (matched before evaluating token/state locks)
    discovered = (
        discover_folder_processes(
            resolved_target,
            extra_roots=[resolved_root] if resolved_root != resolved_target else (),
            exclude_pids=tuple(known_pids),
        )
        if discover_processes
        else []
    )
    has_live_writer_process = (op_record is not None and op_record.engaged) or any(
        rec.mode == "write" and rec.engaged for rec in discovered
    )

    # 6. Guarded repair.lock (.mangadl/repair.lock)
    repair_lock = controls / "repair.lock"
    if repair_lock.exists():
        holder_proc = op_record.process if (op_record and op_record.engaged) else None
        holder_meta = op_record.holder if (op_record and op_record.engaged) else None
        is_engaged = has_live_writer_process
        records.append(
            LockRecord(
                kind="exclusive_token",
                name="repair.lock",
                path=str(repair_lock),
                target=str(resolved_root),
                engaged=is_engaged,
                stale=not is_engaged,
                os_locked=op_record.os_locked if op_record else False,
                mode="write",
                operation="mangadl repair",
                holder=holder_meta,
                process=holder_proc,
                unlockable=not is_engaged,
                detail="active guarded page repair" if is_engaged else "stale repair.lock (no active repair process)",
            )
        )

    # 7. Persisted state.sqlite3 'running' rows (.mangadl/state.sqlite3)
    state_db = controls / "state.sqlite3"
    if state_db.is_file():
        try:
            conn = sqlite3.connect(state_db.as_uri() + "?mode=ro", uri=True, timeout=2)
            try:
                has_runs = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'").fetchone()
                running_rows = (
                    conn.execute("SELECT id, started FROM runs WHERE status='running' AND finished IS NULL").fetchall()
                    if has_runs
                    else []
                )
            finally:
                conn.close()
            for run_id, started in running_rows:
                is_engaged = has_live_writer_process
                records.append(
                    LockRecord(
                        kind="state_run",
                        name=f"state.sqlite3 (run {run_id})",
                        path=str(state_db),
                        target=str(resolved_root),
                        engaged=is_engaged,
                        stale=not is_engaged,
                        os_locked=None,
                        mode="write",
                        operation=f"mangadl run {run_id}",
                        holder={"run_id": run_id, "started_at": started},
                        process=op_record.process if (op_record and op_record.engaged) else None,
                        unlockable=not is_engaged,
                        detail=(
                            f"active download run {run_id}"
                            if is_engaged
                            else f"stale running state for run {run_id} (no active writer process)"
                        ),
                    )
                )
        except sqlite3.Error:
            pass

    # If operation.lock was engaged without embedded metadata (e.g. legacy process) and we discovered one, attach it
    if op_record is not None and op_record.engaged and op_record.process is None and discovered:
        first_proc = discovered[0]
        records[0] = LockRecord(
            **{
                **op_record.to_dict(),
                "holder": first_proc.holder,
                "process": first_proc.process,
                "operation": first_proc.operation,
            }
        )
        discovered = discovered[1:]

    records.extend(discovered)

    write_locked = any(r.engaged and r.mode == "write" for r in records)
    read_locked = any(r.engaged and r.mode == "read" for r in records)
    engaged = any(r.engaged for r in records)
    stale_count = sum(1 for r in records if r.stale)
    auto_cleaned_count = sum(1 for r in records if r.auto_cleaned)
    return FolderLockReport(
        target=str(resolved_target),
        library_root=str(resolved_root),
        engaged=engaged,
        write_locked=write_locked,
        read_locked=read_locked,
        stale_count=stale_count,
        auto_cleaned_count=auto_cleaned_count,
        locks=tuple(records),
    )


def unlock_folder_locks(
    target: Path,
    *,
    library_root: Path | None = None,
    state_root: Path | None = None,
    discover_processes: bool = True,
) -> dict[str, Any]:
    """Clear stale locks for ``target`` only when no live process holds them."""
    before = inspect_folder_locks(
        target,
        library_root=library_root,
        state_root=state_root,
        auto_clean=True,
        discover_processes=discover_processes,
    )
    unlocked: list[dict[str, Any]] = []
    refused_active: list[dict[str, Any]] = []

    for rec in before.locks:
        if rec.engaged:
            refused_active.append(rec.to_dict())
            continue
        if rec.auto_cleaned:
            unlocked.append({"name": rec.name, "path": rec.path, "action": "auto_cleaned_metadata"})
            continue
        if not rec.stale and not rec.unlockable:
            continue
        if rec.kind == "exclusive_token" and Path(rec.path).exists():
            try:
                Path(rec.path).unlink()
                unlocked.append({"name": rec.name, "path": rec.path, "action": "removed_stale_token_lock"})
            except OSError as exc:
                refused_active.append({**rec.to_dict(), "error": str(exc)})
        elif rec.kind == "state_run" and rec.holder and rec.holder.get("run_id"):
            run_id = rec.holder["run_id"]
            now = datetime.now(timezone.utc).isoformat()
            try:
                conn = sqlite3.connect(rec.path, timeout=5)
                with conn:
                    conn.execute(
                        "UPDATE runs SET status='aborted', finished=? WHERE id=? AND status='running' AND finished IS NULL",
                        (now, run_id),
                    )
                conn.close()
                unlocked.append({"name": rec.name, "path": rec.path, "action": f"marked_run_{run_id}_aborted"})
            except sqlite3.Error as exc:
                refused_active.append({**rec.to_dict(), "error": str(exc)})
        elif rec.kind == "read" and Path(rec.path).exists():
            try:
                Path(rec.path).unlink()
                unlocked.append({"name": rec.name, "path": rec.path, "action": "removed_stale_read_slot"})
            except OSError as exc:
                refused_active.append({**rec.to_dict(), "error": str(exc)})
        elif rec.kind == "write" and Path(rec.path).exists():
            reprobed = probe_byte_range_lock(Path(rec.path), auto_clean_stale_metadata=True)
            if reprobed.auto_cleaned:
                unlocked.append({"name": rec.name, "path": rec.path, "action": "cleared_stale_write_metadata"})

    after = inspect_folder_locks(
        target,
        library_root=library_root,
        state_root=state_root,
        auto_clean=False,
        discover_processes=discover_processes,
    )
    return {
        "target": after.target,
        "library_root": after.library_root,
        "unlocked": unlocked,
        "refused_active": refused_active,
        "report": after.to_dict(),
    }
