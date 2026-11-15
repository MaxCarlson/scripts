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

if sys.platform == "win32":
    import msvcrt

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
_CREATE_SUSPENDED = 0x00000004
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_CREATE_NO_WINDOW = 0x08000000
_STARTF_USESHOWWINDOW = 0x00000001
_STARTF_USESTDHANDLES = 0x00000100
_HANDLE_FLAG_INHERIT = 0x00000001
_WAIT_OBJECT_0 = 0x00000000
_STD_INPUT_HANDLE = -10
_GENERIC_READ = 0x80000000
_FILE_SHARE_READ_WRITE = 0x00000003
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x00000080


if sys.platform == "win32":

    class _SECURITY_ATTRIBUTES(ctypes.Structure):
        _fields_ = [
            ("nLength", wintypes.DWORD),
            ("lpSecurityDescriptor", wintypes.LPVOID),
            ("bInheritHandle", wintypes.BOOL),
        ]

    class _STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class _PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]

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

    def assign_handle(self, proc_h: int) -> tuple[bool, str]:
        """Assign an already-opened process handle (e.g. from CreateProcessW) to this Job."""
        if sys.platform != "win32":
            return False, "not_applicable"
        if not self.handle:
            return False, self.last_error or "job_unavailable"
        ok = self._k32.AssignProcessToJobObject(self.handle, proc_h)
        if not ok:
            err = ctypes.get_last_error()
            return False, f"AssignProcessToJobObject failed (winerror={err})"
        return True, "assigned"

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
            return self.assign_handle(int(proc_h))
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


class _JobAssignmentError(RuntimeError):
    """Raised when Job Object assignment fails while the child is still suspended."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _Win32ProcessHandle:
    """Minimal Popen-compatible wrapper around a Win32 process HANDLE."""

    def __init__(
        self,
        k32: Any,
        h_process: int,
        pid: int,
        stdout: BinaryIO | None,
        stderr: BinaryIO | None,
    ) -> None:
        self._k32 = k32
        self._h_process: int | None = h_process
        self.pid = pid
        self.stdout = stdout
        self.stderr = stderr
        self._returncode: int | None = None

    def poll(self) -> int | None:
        if self._returncode is not None:
            return self._returncode
        if self._h_process is None:
            return None
        wait_res = self._k32.WaitForSingleObject(self._h_process, 0)
        if wait_res != _WAIT_OBJECT_0:
            return None
        code = wintypes.DWORD(0)
        if self._k32.GetExitCodeProcess(self._h_process, ctypes.byref(code)):
            self._returncode = int(code.value)
        else:
            self._returncode = -1
        return self._returncode

    def wait(self, timeout: float | None = None) -> int:
        if self._returncode is not None:
            return self._returncode
        if self._h_process is None:
            return -1
        ms = 0xFFFFFFFF if timeout is None else max(0, int(timeout * 1000))
        wait_res = self._k32.WaitForSingleObject(self._h_process, ms)
        if wait_res != _WAIT_OBJECT_0:
            raise subprocess.TimeoutExpired(cmd="win32_process", timeout=timeout or 0.0)
        code = wintypes.DWORD(0)
        if self._k32.GetExitCodeProcess(self._h_process, ctypes.byref(code)):
            self._returncode = int(code.value)
        else:
            self._returncode = -1
        return self._returncode

    def terminate(self) -> None:
        if self._h_process is not None and self.poll() is None:
            self._k32.TerminateProcess(self._h_process, 1)

    def kill(self) -> None:
        self.terminate()

    def close(self) -> None:
        if self._h_process is not None:
            try:
                self._k32.CloseHandle(self._h_process)
            finally:
                self._h_process = None


def _launch_win32_suspended_in_job(
    *,
    arg_list: list[str],
    resolved_exe: str,
    cwd: str,
    child_env: Mapping[str, str],
    prof: ExecutionProfile,
    creationflags: int,
    job: _Win32JobHandle,
) -> tuple[_Win32ProcessHandle, str]:
    """Create process suspended, assign to Job Object before ResumeThread, then resume.

    Guarantees zero race window between process start and Job Object containment.
    """
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreatePipe.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        ctypes.POINTER(wintypes.HANDLE),
        ctypes.POINTER(_SECURITY_ATTRIBUTES),
        wintypes.DWORD,
    ]
    k32.CreatePipe.restype = wintypes.BOOL
    k32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
    k32.SetHandleInformation.restype = wintypes.BOOL
    k32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_SECURITY_ATTRIBUTES),
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.GetStdHandle.argtypes = [wintypes.DWORD]
    k32.GetStdHandle.restype = wintypes.HANDLE
    k32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPCWSTR,
        ctypes.POINTER(_STARTUPINFOW),
        ctypes.POINTER(_PROCESS_INFORMATION),
    ]
    k32.CreateProcessW.restype = wintypes.BOOL
    k32.ResumeThread.argtypes = [wintypes.HANDLE]
    k32.ResumeThread.restype = wintypes.DWORD
    k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k32.TerminateProcess.restype = wintypes.BOOL
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.WaitForSingleObject.restype = wintypes.DWORD
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.GetExitCodeProcess.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL

    sa = _SECURITY_ATTRIBUTES()
    sa.nLength = ctypes.sizeof(_SECURITY_ATTRIBUTES)
    sa.lpSecurityDescriptor = None
    sa.bInheritHandle = True

    out_r = wintypes.HANDLE()
    out_w = wintypes.HANDLE()
    err_r = wintypes.HANDLE()
    err_w = wintypes.HANDLE()
    if not k32.CreatePipe(ctypes.byref(out_r), ctypes.byref(out_w), ctypes.byref(sa), 0):
        raise ctypes.WinError(ctypes.get_last_error())
    if not k32.CreatePipe(ctypes.byref(err_r), ctypes.byref(err_w), ctypes.byref(sa), 0):
        err = ctypes.get_last_error()
        k32.CloseHandle(out_r)
        k32.CloseHandle(out_w)
        raise ctypes.WinError(err)

    k32.SetHandleInformation(out_r, _HANDLE_FLAG_INHERIT, 0)
    k32.SetHandleInformation(err_r, _HANDLE_FLAG_INHERIT, 0)

    stdin_nul: wintypes.HANDLE | None = None
    stdin_handle: int | wintypes.HANDLE
    if prof == ExecutionProfile.HEADLESS:
        stdin_nul = k32.CreateFileW(
            "NUL",
            _GENERIC_READ,
            _FILE_SHARE_READ_WRITE,
            ctypes.byref(sa),
            _OPEN_EXISTING,
            _FILE_ATTRIBUTE_NORMAL,
            None,
        )
        stdin_handle = stdin_nul
    else:
        stdin_handle = k32.GetStdHandle(wintypes.DWORD(_STD_INPUT_HANDLE & 0xFFFFFFFF))

    si = _STARTUPINFOW()
    si.cb = ctypes.sizeof(_STARTUPINFOW)
    si.dwFlags = _STARTF_USESTDHANDLES
    if prof == ExecutionProfile.HEADLESS:
        si.dwFlags |= _STARTF_USESHOWWINDOW
        si.wShowWindow = 0
    si.hStdInput = stdin_handle
    si.hStdOutput = out_w
    si.hStdError = err_w

    env_str = "".join(
        f"{k}={v}\0" for k, v in sorted(child_env.items(), key=lambda kv: kv[0].upper())
    ) + "\0"
    env_buf = ctypes.create_unicode_buffer(env_str)
    cmdline_buf = ctypes.create_unicode_buffer(subprocess.list2cmdline(arg_list))
    app_name = resolved_exe if Path(resolved_exe).is_file() else None
    flags = creationflags | _CREATE_SUSPENDED | _CREATE_UNICODE_ENVIRONMENT

    pi = _PROCESS_INFORMATION()
    try:
        ok = k32.CreateProcessW(
            app_name,
            cmdline_buf,
            None,
            None,
            True,
            flags,
            env_buf,
            cwd,
            ctypes.byref(si),
            ctypes.byref(pi),
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
    except Exception:
        k32.CloseHandle(out_r)
        k32.CloseHandle(err_r)
        raise
    finally:
        k32.CloseHandle(out_w)
        k32.CloseHandle(err_w)
        if stdin_nul is not None and int(stdin_nul) not in (0, -1):
            k32.CloseHandle(stdin_nul)

    # Child is suspended (0 instructions executed). Assign to Job BEFORE ResumeThread.
    try:
        job_assigned, job_status = job.assign_handle(int(pi.hProcess))
        if not job_assigned:
            k32.TerminateProcess(pi.hProcess, 1)
            raise _JobAssignmentError(job_status)

        out_stream = os.fdopen(msvcrt.open_osfhandle(int(out_r.value), os.O_RDONLY), "rb")
        err_stream = os.fdopen(msvcrt.open_osfhandle(int(err_r.value), os.O_RDONLY), "rb")
    except Exception:
        k32.CloseHandle(pi.hThread)
        k32.CloseHandle(pi.hProcess)
        try:
            k32.CloseHandle(out_r)
        except Exception:
            pass
        try:
            k32.CloseHandle(err_r)
        except Exception:
            pass
        raise

    prev_suspend = k32.ResumeThread(pi.hThread)
    k32.CloseHandle(pi.hThread)
    if prev_suspend == 0xFFFFFFFF:
        err = ctypes.get_last_error()
        k32.TerminateProcess(pi.hProcess, 1)
        k32.CloseHandle(pi.hProcess)
        out_stream.close()
        err_stream.close()
        raise ctypes.WinError(err)

    proc_handle = _Win32ProcessHandle(
        k32=k32,
        h_process=int(pi.hProcess),
        pid=int(pi.dwProcessId),
        stdout=out_stream,
        stderr=err_stream,
    )
    return proc_handle, job_status


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
    proc: subprocess.Popen[bytes] | _Win32ProcessHandle | None = None
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
        if sys.platform == "win32":
            proc, job_status = _launch_win32_suspended_in_job(
                arg_list=arg_list,
                resolved_exe=resolved_exe,
                cwd=resolved_cwd,
                child_env=child_env,
                prof=prof,
                creationflags=creationflags,
                job=job,
            )
            job_assigned = True
            k_time = _read_windows_process_create_100ns(proc.pid)
            boot_id = get_boot_id()
            if k_time is not None:
                proc_key = ProcessIdentity.canonical_kernel(boot_id, proc.pid, k_time).proc_key
            else:
                proc_key = ProcessIdentity.provisional(boot_id, proc.pid, start_ns).proc_key
        else:
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
            time.sleep(0.01)
    except _JobAssignmentError as exc:
        status = RunStatus.LAUNCH_FAILED
        job_assigned = False
        job_status = exc.reason
        cleanup_outcome = "terminated_before_resume"
        err_detail = f"Job assignment failed before resume: {exc.reason}"
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
        if isinstance(proc, _Win32ProcessHandle):
            proc.close()
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
    proc: subprocess.Popen[bytes] | _Win32ProcessHandle,
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
