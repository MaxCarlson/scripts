"""Observable headless subprocess supervisor with Windows Job Object tree containment."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, BinaryIO, Mapping, Sequence
import uuid

from procwatch.correlator.ancestry import _read_windows_process_create_100ns, get_boot_id
from procwatch.models import (
    ExecutionProfile,
    ProcessIdentity,
    RunResult,
    RunStatus,
    utc_now_iso,
)
from procwatch.redactor import redact_text
from procwatch.runner.context_hook import build_instrumented_env
from procwatch.storage import FlightRecorderStorage

logger = logging.getLogger(__name__)

_JOB_OBJECT_EXTENDED_LIMIT_INFO_CLASS = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_PROCESS_ALL_ACCESS = 0x001F0FFF
_DEFAULT_MAX_OUTPUT_BYTES = 262_144


if sys.platform == "win32":

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]


class _Win32JobHandle:
    """RAII wrapper for a Windows Job Object with KILL_ON_JOB_CLOSE."""

    def __init__(self) -> None:
        self.handle: int | None = None
        self.last_error: str | None = None
        if sys.platform != "win32":
            return

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        k32.SetInformationJobObject.restype = wintypes.BOOL
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.AssignProcessToJobObject.restype = wintypes.BOOL
        k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k32.TerminateJobObject.restype = wintypes.BOOL
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.CloseHandle.restype = wintypes.BOOL
        self._k32 = k32

        job = k32.CreateJobObjectW(None, None)
        if not job:
            err = ctypes.get_last_error()
            self.last_error = f"CreateJobObjectW failed (winerror={err})"
            return

        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = k32.SetInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFO_CLASS,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            err = ctypes.get_last_error()
            k32.CloseHandle(job)
            self.last_error = f"SetInformationJobObject failed (winerror={err})"
            return
        self.handle = int(job)

    def assign_pid(self, pid: int) -> tuple[bool, str]:
        if sys.platform != "win32":
            return False, "not_applicable"
        if not self.handle:
            return False, self.last_error or "job_unavailable"

        proc_h = self._k32.OpenProcess(_PROCESS_ALL_ACCESS, False, pid)
        if not proc_h:
            err = ctypes.get_last_error()
            return False, f"OpenProcess failed (winerror={err})"
        try:
            ok = self._k32.AssignProcessToJobObject(self.handle, proc_h)
            if not ok:
                err = ctypes.get_last_error()
                return False, f"AssignProcessToJobObject failed (winerror={err})"
            return True, "assigned"
        finally:
            self._k32.CloseHandle(proc_h)

    def terminate(self, exit_code: int = 1) -> tuple[bool, str]:
        if sys.platform != "win32" or not self.handle:
            return False, "job_unavailable"
        ok = self._k32.TerminateJobObject(self.handle, exit_code)
        if not ok:
            err = ctypes.get_last_error()
            return False, f"TerminateJobObject failed (winerror={err})"
        return True, "job_terminated"

    def close(self) -> None:
        if sys.platform == "win32" and self.handle:
            try:
                self._k32.CloseHandle(self.handle)
            finally:
                self.handle = None


class _BoundedStreamReader:
    """Concurrent non-blocking pipe reader enforcing byte cap and truncation accounting."""

    def __init__(self, stream: BinaryIO | None, max_bytes: int) -> None:
        self._stream = stream
        self._max_bytes = max(0, max_bytes)
        self._chunks: list[bytes] = []
        self._kept_bytes = 0
        self.total_bytes = 0
        self.truncated = False
        self.dropped_bytes = 0
        self._thread: threading.Thread | None = None

    def start(self, name: str) -> None:
        if self._stream is None:
            return
        self._thread = threading.Thread(target=self._drain, name=name, daemon=True)
        self._thread.start()

    def _drain(self) -> None:
        assert self._stream is not None
        try:
            while True:
                data = self._stream.read(8192)
                if not data:
                    break
                n = len(data)
                self.total_bytes += n
                if self._kept_bytes < self._max_bytes:
                    room = self._max_bytes - self._kept_bytes
                    if n <= room:
                        self._chunks.append(data)
                        self._kept_bytes += n
                    else:
                        self._chunks.append(data[:room])
                        self._kept_bytes += room
                        self.truncated = True
                        self.dropped_bytes += n - room
                else:
                    self.truncated = True
                    self.dropped_bytes += n
        except Exception:
            pass
        finally:
            try:
                self._stream.close()
            except Exception:
                pass

    def join(self, timeout: float = 2.0) -> str:
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        text = b"".join(self._chunks).decode("utf-8", errors="replace")
        if self.truncated:
            text += f"\n...[truncated {self.dropped_bytes} bytes]..."
        return text


def execute(
    argv: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env_overrides: Mapping[str, str] | None = None,
    profile: ExecutionProfile | str = ExecutionProfile.HEADLESS,
    timeout_seconds: float | None = None,
    max_output_bytes: int = _DEFAULT_MAX_OUTPUT_BYTES,
    context: Mapping[str, Any] | None = None,
    storage: FlightRecorderStorage | None = None,
    keep_console_on_error: bool = False,
    cancel_event: threading.Event | None = None,
) -> RunResult:
    """Execute a command under Windows Job Object supervision with bounded redacted capture."""
    prof = ExecutionProfile(profile) if isinstance(profile, str) else profile
    exec_id = str((context or {}).get("execution_id") or uuid.uuid4())
    arg_list = [str(a) for a in argv]
    resolved_cwd = str(Path(cwd).expanduser().resolve()) if cwd is not None else os.getcwd()
    start_ts = utc_now_iso()
    start_ns = time.monotonic_ns()

    base_env = dict(os.environ)
    if env_overrides:
        base_env.update({str(k): str(v) for k, v in env_overrides.items()})

    child_env, ctx_payload = build_instrumented_env(
        base_env,
        execution_id=exec_id,
        agent_kind=(context or {}).get("agent_kind"),
        agent_session=(context or {}).get("agent_session"),
        phase=(context or {}).get("phase"),
        cwd=resolved_cwd,
        producer=str((context or {}).get("producer") or "procwatch_exec"),
        parent_execution_id=(context or {}).get("parent_execution_id"),
    )

    if not arg_list:
        return _finalize_failure(
            execution_id=exec_id,
            executable="",
            argv_list=[],
            cwd=resolved_cwd,
            profile=prof,
            start_ts=start_ts,
            start_ns=start_ns,
            error_detail="Empty command argv.",
            ctx_payload=ctx_payload,
            storage=storage,
        )

    executable = arg_list[0]
    if not Path(resolved_cwd).is_dir():
        return _finalize_failure(
            execution_id=exec_id,
            executable=executable,
            argv_list=arg_list,
            cwd=resolved_cwd,
            profile=prof,
            start_ts=start_ts,
            start_ns=start_ns,
            error_detail=f"Working directory does not exist: {resolved_cwd}",
            ctx_payload=ctx_payload,
            storage=storage,
        )

    resolved_exe = shutil.which(executable, path=child_env.get("PATH")) or executable
    if not Path(resolved_exe).exists() and shutil.which(executable) is None:
        return _finalize_failure(
            execution_id=exec_id,
            executable=executable,
            argv_list=arg_list,
            cwd=resolved_cwd,
            profile=prof,
            start_ts=start_ts,
            start_ns=start_ns,
            error_detail=f"Executable not found: {executable}",
            ctx_payload=ctx_payload,
            storage=storage,
        )

    if storage is not None:
        try:
            storage.record_supervised_run_start(
                execution_id=exec_id,
                executable=executable,
                argv=arg_list,
                cwd=resolved_cwd,
                profile=prof.value,
                start_ts_utc=start_ts,
                agent_context=ctx_payload,
            )
        except Exception as exc:
            logger.debug("Failed to record run start: %s", exc)

    creationflags = 0
    if sys.platform == "win32" and prof == ExecutionProfile.HEADLESS:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    job = _Win32JobHandle()
    proc: subprocess.Popen[bytes] | None = None
    job_assigned = False
    job_status = "not_applicable" if sys.platform != "win32" else (job.last_error or "created")
    cleanup_outcome = "not_needed"
    status = RunStatus.UNKNOWN
    exit_code: int | None = None
    proc_key: str | None = None
    err_detail: str | None = None

    stdout_reader = _BoundedStreamReader(None, max_output_bytes)
    stderr_reader = _BoundedStreamReader(None, max_output_bytes)

    try:
        proc = subprocess.Popen(
            arg_list,
            cwd=resolved_cwd,
            env=child_env,
            stdin=subprocess.DEVNULL if prof == ExecutionProfile.HEADLESS else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            creationflags=creationflags,
        )
        if sys.platform == "win32":
            job_assigned, job_status = job.assign_pid(proc.pid)
            k_time = _read_windows_process_create_100ns(proc.pid)
            boot_id = get_boot_id()
            if k_time is not None:
                proc_key = ProcessIdentity.canonical_kernel(boot_id, proc.pid, k_time).proc_key
            else:
                proc_key = ProcessIdentity.provisional(boot_id, proc.pid, start_ns).proc_key

        stdout_reader = _BoundedStreamReader(proc.stdout, max_output_bytes)
        stderr_reader = _BoundedStreamReader(proc.stderr, max_output_bytes)
        stdout_reader.start(f"procwatch-out-{proc.pid}")
        stderr_reader.start(f"procwatch-err-{proc.pid}")

        deadline = (time.monotonic() + timeout_seconds) if timeout_seconds is not None else None
        while True:
            rc = proc.poll()
            if rc is not None:
                exit_code = int(rc)
                status = RunStatus.SUCCESS if exit_code == 0 else RunStatus.NONZERO_EXIT
                break
            if cancel_event is not None and cancel_event.is_set():
                status = RunStatus.CANCELLED
                cleanup_outcome = _terminate_owned_tree(proc, job, job_assigned)
                exit_code = proc.poll()
                break
            if deadline is not None and time.monotonic() >= deadline:
                status = RunStatus.TIMEOUT
                err_detail = f"Command timed out after {timeout_seconds}s"
                cleanup_outcome = _terminate_owned_tree(proc, job, job_assigned)
                exit_code = proc.poll()
                break
            time.sleep(0.02)
    except KeyboardInterrupt:
        status = RunStatus.CANCELLED
        err_detail = "Interrupted by KeyboardInterrupt"
        if proc is not None:
            cleanup_outcome = _terminate_owned_tree(proc, job, job_assigned)
            exit_code = proc.poll()
    except OSError as exc:
        status = RunStatus.LAUNCH_FAILED
        err_detail = str(exc)
    finally:
        out_text = stdout_reader.join()
        err_text = stderr_reader.join()
        job.close()

    duration_ms = round((time.monotonic_ns() - start_ns) / 1_000_000.0, 3)
    red_out = redact_text(out_text, escape_controls=False) or ""
    red_err = redact_text(err_text, escape_controls=False) or ""

    if keep_console_on_error and status != RunStatus.SUCCESS:
        # Non-intrusive stderr diagnostic; never spawns a popup console window.
        print(
            f"[procwatch exec] {executable} failed (status={status.value}, exit={exit_code}, "
            f"duration={duration_ms}ms)",
            file=sys.stderr,
        )

    result = RunResult(
        execution_id=exec_id,
        executable=executable,
        argv_redacted=[redact_text(a, escape_controls=True) or "" for a in arg_list],
        cwd=resolved_cwd,
        profile=prof,
        start_ts_utc=start_ts,
        end_ts_utc=utc_now_iso(),
        duration_ms=duration_ms,
        exit_code=exit_code,
        status=status,
        pid=proc.pid if proc is not None else None,
        proc_key=proc_key,
        job_assigned=job_assigned,
        job_status=job_status,
        job_cleanup_outcome=cleanup_outcome,
        stdout_redacted=red_out,
        stderr_redacted=red_err,
        stdout_bytes=stdout_reader.total_bytes,
        stderr_bytes=stderr_reader.total_bytes,
        stdout_truncated=stdout_reader.truncated,
        stderr_truncated=stderr_reader.truncated,
        dropped_bytes=stdout_reader.dropped_bytes + stderr_reader.dropped_bytes,
        agent_context=ctx_payload,
        error_detail=err_detail,
        db_persisted=False,
    )

    if storage is not None:
        try:
            storage.record_supervised_run(result)
            result.db_persisted = True
        except Exception as exc:
            logger.debug("Failed to persist supervised run: %s", exc)
    return result


def _terminate_owned_tree(
    proc: subprocess.Popen[bytes],
    job: _Win32JobHandle,
    job_assigned: bool,
) -> str:
    """Terminate only the owned Job Object or owned Popen child (never unrelated PIDs)."""
    if job_assigned:
        ok, msg = job.terminate(1)
        try:
            proc.wait(timeout=2.0)
        except Exception:
            pass
        return msg if ok else f"job_terminate_failed:{msg}"

    try:
        proc.terminate()
        proc.wait(timeout=1.5)
        return "popen_terminated"
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=1.5)
            return "popen_killed"
        except Exception as exc:
            return f"cleanup_failed:{exc}"


def _finalize_failure(
    *,
    execution_id: str,
    executable: str,
    argv_list: list[str],
    cwd: str,
    profile: ExecutionProfile,
    start_ts: str,
    start_ns: int,
    error_detail: str,
    ctx_payload: dict[str, Any],
    storage: FlightRecorderStorage | None,
) -> RunResult:
    result = RunResult(
        execution_id=execution_id,
        executable=executable,
        argv_redacted=[redact_text(a, escape_controls=True) or "" for a in argv_list],
        cwd=cwd,
        profile=profile,
        start_ts_utc=start_ts,
        end_ts_utc=utc_now_iso(),
        duration_ms=round((time.monotonic_ns() - start_ns) / 1_000_000.0, 3),
        exit_code=None,
        status=RunStatus.LAUNCH_FAILED,
        agent_context=ctx_payload,
        error_detail=error_detail,
        db_persisted=False,
    )
    if storage is not None:
        try:
            storage.record_supervised_run(result)
            result.db_persisted = True
        except Exception:
            pass
    return result
