"""
Process supervisor abstractions, safe PID/create-time verified lifecycle management, and backends.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Protocol, Sequence

import psutil

from .events import EventDispatcher

logger = logging.getLogger(__name__)


class ProcessState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    EXTERNAL_RUNNING = "external_running"
    UNKNOWN = "unknown"


class ProcessLifecycleOwner(str, Enum):
    """Identifies the entity managing the lifecycle of a process."""

    COORDINATOR = "coordinator"  # Launched directly by coordinator
    EXTERNAL = "external"  # Discovered running under external launcher/supervisor
    UNMANAGED = "unmanaged"  # Stopped or unmanaged


@dataclass(frozen=True)
class ProcessInfo:
    """Snapshot of a process's state and ownership."""

    name: str
    state: ProcessState
    pid: Optional[int] = None
    create_time: Optional[float] = None
    executable: Optional[str] = None
    lifecycle_owner: ProcessLifecycleOwner = ProcessLifecycleOwner.UNMANAGED
    is_coordinator_owned: bool = False
    last_stopped_at: Optional[float] = None
    last_started_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state.value,
            "pid": self.pid,
            "create_time": self.create_time,
            "executable": self.executable,
            "lifecycle_owner": self.lifecycle_owner.value,
            "is_coordinator_owned": self.is_coordinator_owned,
            "last_stopped_at": self.last_stopped_at,
            "last_started_at": self.last_started_at,
        }


class ProcessBackend(Protocol):
    """Protocol for managed process backends."""

    name: str
    allow_external_stop: bool
    allow_external_restart: bool

    async def status(self) -> ProcessInfo: ...
    async def start(self) -> bool: ...
    async def stop(self, timeout: float = 10.0) -> bool: ...
    async def wait_stopped(self, timeout: float = 10.0) -> bool: ...


class FakeProcessBackend:
    """In-memory fake process backend for deterministic offline testing."""

    def __init__(
        self,
        name: str = "fake_process",
        running: bool = False,
        executable: str = "/bin/fake",
        fail_start: bool = False,
        fail_stop: bool = False,
        stop_delay: float = 0.0,
        start_delay: float = 0.0,
        external: bool = False,
        allow_external_stop: bool = False,
        allow_external_restart: bool = False,
        relaunch_delay: Optional[float] = None,
    ) -> None:
        self.name = name
        self.executable = executable
        self.running = running
        self.lifecycle_owner = (
            ProcessLifecycleOwner.EXTERNAL
            if (running and external)
            else (ProcessLifecycleOwner.COORDINATOR if running else ProcessLifecycleOwner.UNMANAGED)
        )
        self.is_coordinator_owned = self.lifecycle_owner == ProcessLifecycleOwner.COORDINATOR
        self.fail_start = fail_start
        self.fail_stop = fail_stop
        self.stop_delay = stop_delay
        self.start_delay = start_delay
        self.allow_external_stop = allow_external_stop or not external
        self.allow_external_restart = allow_external_restart or not external
        self.relaunch_delay = relaunch_delay
        self.pid = 12345 if running else None
        self.create_time = time.time() if running else None
        self.last_stopped_at: Optional[float] = None
        self.last_started_at: Optional[float] = time.time() if running else None
        self._relaunch_task: Optional[asyncio.Task] = None
        self.generation = 1 if running else 0
        self.last_launch_log_offset = 0

    async def status(self) -> ProcessInfo:
        if not self.running:
            state = ProcessState.STOPPED
        elif self.lifecycle_owner == ProcessLifecycleOwner.EXTERNAL:
            state = ProcessState.EXTERNAL_RUNNING
        else:
            state = ProcessState.RUNNING

        return ProcessInfo(
            name=self.name,
            state=state,
            pid=self.pid,
            create_time=self.create_time,
            executable=self.executable,
            lifecycle_owner=self.lifecycle_owner,
            is_coordinator_owned=self.lifecycle_owner == ProcessLifecycleOwner.COORDINATOR,
            last_stopped_at=self.last_stopped_at,
            last_started_at=self.last_started_at,
        )

    async def start(self) -> bool:
        if self.start_delay > 0:
            await asyncio.sleep(self.start_delay)
        if self.fail_start:
            return False
        if self.running:
            return True
        if self.lifecycle_owner == ProcessLifecycleOwner.EXTERNAL and not self.allow_external_restart:
            logger.warning(
                "Process '%s' is externally owned and allow_external_restart is False; refusing start",
                self.name,
            )
            return False

        self.running = True
        self.lifecycle_owner = ProcessLifecycleOwner.COORDINATOR
        self.is_coordinator_owned = True
        self.pid = 12345
        self.create_time = time.time()
        self.last_started_at = time.time()
        self.generation += 1
        return True

    async def stop(self, timeout: float = 10.0) -> bool:
        if not self.running:
            return True
        if self.lifecycle_owner == ProcessLifecycleOwner.EXTERNAL and not self.allow_external_stop:
            logger.warning(
                "Process '%s' is running externally and allow_external_stop is False; refusing stop",
                self.name,
            )
            return False

        if self.stop_delay > 0:
            await asyncio.sleep(self.stop_delay)
        if self.fail_stop:
            return False
        self.running = False
        self.pid = None
        self.create_time = None
        self.last_stopped_at = time.time()

        if self.relaunch_delay is not None and self.relaunch_delay > 0:
            delay = self.relaunch_delay

            async def _auto_relaunch() -> None:
                await asyncio.sleep(delay)
                self.running = True
                self.lifecycle_owner = ProcessLifecycleOwner.EXTERNAL
                self.is_coordinator_owned = False
                self.pid = 12346
                self.create_time = time.time()
                logger.warning("External supervisor automatically relaunched process '%s'", self.name)

            self._relaunch_task = asyncio.create_task(_auto_relaunch())

        return True

    async def wait_stopped(self, timeout: float = 10.0) -> bool:
        deadline = time.time() + timeout
        while self.running:
            if time.time() > deadline:
                return False
            await asyncio.sleep(0.01)
        return True


class WindowsProcessBackend:
    """
    Windows process management backend with PID and creation-time verification.

    Prevents PID recycling hazards and verifies process ownership.
    Supports separate permissions for external stop and external restart.
    """

    def __init__(
        self,
        name: str,
        executable: str,
        arguments: Optional[Sequence[str]] = None,
        working_directory: Optional[str] = None,
        new_console: bool = False,
        allow_external_stop: bool = False,
        allow_external_restart: bool = False,
        adopt_external: bool = False,
        allow_force_termination: bool = False,
        stdout_log_path: Optional[str] = None,
    ) -> None:
        self.name = name
        self.executable = executable
        self.arguments = list(arguments or [])
        self.working_directory = working_directory
        self.new_console = new_console
        self.allow_force_termination = allow_force_termination
        self.stdout_log_path = stdout_log_path
        self._console_group_pid: Optional[int] = None
        self.allow_external_stop = allow_external_stop or adopt_external
        self.allow_external_restart = allow_external_restart or adopt_external
        self.adopt_external = adopt_external or (self.allow_external_stop and self.allow_external_restart)

        self._proc: Optional[subprocess.Popen] = None
        self._owned_pid: Optional[int] = None
        self._owned_create_time: Optional[float] = None
        self._last_started_at: Optional[float] = None
        self._last_stopped_at: Optional[float] = None
        self._log_file_handle: Optional[Any] = None
        self._generation: int = 0
        self._last_launch_log_offset: int = 0

    def _close_log_file(self) -> None:
        if self._log_file_handle is not None:
            try:
                self._log_file_handle.flush()
                self._log_file_handle.close()
            except Exception:
                pass
            self._log_file_handle = None

    def __del__(self) -> None:
        self._close_log_file()

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def last_launch_log_offset(self) -> int:
        return self._last_launch_log_offset

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _same_executable(self, process: psutil.Process) -> bool:
        try:
            # Ignore inaccessible unrelated processes, but fail closed for a matching name.
            if process.name().casefold() != Path(self.executable).name.casefold():
                return False
            exe = process.exe()
            expected = os.path.normcase(os.path.realpath(self.executable))
            actual = os.path.normcase(os.path.realpath(exe))
            return actual == expected
        except psutil.NoSuchProcess:
            return False

    def _find_owned_process(self) -> Optional[psutil.Process]:
        if self._owned_pid is None or self._owned_create_time is None:
            return None
        try:
            p = psutil.Process(self._owned_pid)
            if p.create_time() != self._owned_create_time:
                return None
            if not self._same_executable(p):
                return None
            return p
        except psutil.NoSuchProcess:
            return None

    def _find_external_process(self) -> Optional[psutil.Process]:
        for p in psutil.process_iter(["name", "exe"]):
            if self._same_executable(p):
                return p
        return None

    async def status(self) -> ProcessInfo:
        try:
            return await self._status()
        except (psutil.Error, OSError):
            logger.warning("Cannot verify process '%s' state", self.name)
            return ProcessInfo(self.name, ProcessState.UNKNOWN, executable=self.executable)

    async def _status(self) -> ProcessInfo:
        owned = self._find_owned_process()
        if owned is not None and owned.is_running():
            return ProcessInfo(
                name=self.name,
                state=ProcessState.RUNNING,
                pid=owned.pid,
                create_time=owned.create_time(),
                executable=self.executable,
                lifecycle_owner=ProcessLifecycleOwner.COORDINATOR,
                is_coordinator_owned=True,
                last_stopped_at=self._last_stopped_at,
                last_started_at=self._last_started_at,
            )

        external = self._find_external_process()
        if external is not None and external.is_running():
            return ProcessInfo(
                name=self.name,
                state=ProcessState.EXTERNAL_RUNNING,
                pid=external.pid,
                create_time=external.create_time(),
                executable=self.executable,
                lifecycle_owner=ProcessLifecycleOwner.EXTERNAL,
                is_coordinator_owned=False,
                last_stopped_at=self._last_stopped_at,
                last_started_at=self._last_started_at,
            )

        return ProcessInfo(
            name=self.name,
            state=ProcessState.STOPPED,
            pid=None,
            create_time=None,
            executable=self.executable,
            lifecycle_owner=ProcessLifecycleOwner.UNMANAGED,
            is_coordinator_owned=False,
            last_stopped_at=self._last_stopped_at,
            last_started_at=self._last_started_at,
        )

    async def start(self) -> bool:
        st = await self.status()
        if st.state == ProcessState.RUNNING:
            logger.info("Process '%s' is already running (owned)", self.name)
            return True
        if st.state == ProcessState.UNKNOWN:
            return False
        if st.state == ProcessState.EXTERNAL_RUNNING:
            return True
        if st.state != ProcessState.STOPPED:
            return False
        launch_kwargs: Dict[str, Any] = {
            "cwd": self.working_directory or None,
            "shell": False,
        }
        if self.new_console and os.name == "nt":
            # Windows ignores NEW_PROCESS_GROUP when NEW_CONSOLE is present.
            launch_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x10)
        else:
            launch_kwargs.update(
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        if os.name == "nt" and not self.new_console:
            launch_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)

        if self.stdout_log_path:
            self._close_log_file()
            log_dir = Path(self.stdout_log_path).parent
            log_dir.mkdir(parents=True, exist_ok=True)
            self._log_file_handle = open(self.stdout_log_path, "a", encoding="utf-8", buffering=1)
            launch_kwargs["stdout"] = self._log_file_handle
            launch_kwargs["stderr"] = subprocess.STDOUT

        cmd = [self.executable, *self.arguments]
        try:
            self._proc = subprocess.Popen(cmd, **launch_kwargs)
            self._owned_pid = self._proc.pid
            p = psutil.Process(self._proc.pid)
            self._owned_create_time = p.create_time()
            self._console_group_pid = self._proc.pid if os.name == "nt" and not self.new_console else None
            self._last_started_at = time.time()
            self._generation += 1
            if self._log_file_handle is not None:
                from datetime import datetime, timezone

                iso_ts = datetime.now(timezone.utc).isoformat()
                header = f"\n--- [COORDINATOR GENERATION {self._generation} PID {self._owned_pid} STARTED AT {iso_ts}] ---\n"
                self._log_file_handle.write(header)
                self._log_file_handle.flush()
                try:
                    self._last_launch_log_offset = Path(self.stdout_log_path).stat().st_size
                except OSError:
                    self._last_launch_log_offset = 0
            else:
                self._last_launch_log_offset = 0
            logger.info(
                "Started process '%s' (PID %d, Generation %d)",
                self.name,
                self._owned_pid,
                self._generation,
            )
            return True
        except Exception as exc:
            self._close_log_file()
            logger.error("Failed to start process '%s': %s", self.name, exc)
            return False

    async def stop(self, timeout: float = 10.0) -> bool:
        st = await self.status()
        if st.state == ProcessState.STOPPED:
            return True
        if st.state not in {ProcessState.RUNNING, ProcessState.EXTERNAL_RUNNING}:
            return False
        if st.state == ProcessState.EXTERNAL_RUNNING and not self.allow_external_stop:
            return False
        children: Optional[list[psutil.Process]] = None

        def children_stopped() -> bool:
            if children is None:
                return False
            try:
                return all(not child.is_running() for child in children)
            except psutil.Error:
                return False

        try:
            p = self._find_owned_process()
            if p is None and self.allow_external_stop:
                p = self._find_external_process()
            # Never switch targets between discovery and action.
            if p is None or p.pid != st.pid or st.create_time is None or p.create_time() != st.create_time:
                return False
            children = p.children(recursive=True)
            graceful_sent = False
            if os.name == "nt" and st.is_coordinator_owned and p.pid == self._console_group_pid:
                import ctypes

                graceful_sent = bool(ctypes.windll.kernel32.GenerateConsoleCtrlEvent(1, p.pid))
            if not graceful_sent:
                if not self.allow_force_termination:
                    logger.warning("No verified console group for '%s'; forceful termination is disabled", self.name)
                    return False
                logger.warning("Forcefully terminating '%s'; Windows terminate is not graceful", self.name)
                p.terminate()

            if self.allow_force_termination and children:
                for child in children:
                    try:
                        if child.is_running():
                            child.terminate()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

            stopped = await self.wait_stopped(timeout=timeout)
            if not stopped and self.allow_force_termination:
                # psutil's Process methods check PID reuse before signalling.
                if p.is_running() and p.create_time() == st.create_time:
                    p.kill()
                if children:
                    for child in children:
                        try:
                            if child.is_running():
                                child.kill()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                stopped = await self.wait_stopped(timeout=3.0)
            if not children_stopped():
                logger.error("Descendant processes remain for '%s'; stop is unverified", self.name)
                return False
            if stopped:
                self._last_stopped_at = time.time()
                self._proc = None
                self._owned_pid = None
                self._owned_create_time = None
                self._console_group_pid = None
                self._close_log_file()
            return stopped
        except psutil.AccessDenied:
            logger.error("Access denied stopping '%s'; stop is unverified", self.name)
            return False
        except psutil.NoSuchProcess:
            return children_stopped() and await self.wait_stopped(timeout=timeout)
        except (psutil.Error, OSError) as exc:
            logger.error("Error stopping process '%s': %s", self.name, exc)
            return False

    async def wait_stopped(self, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        absent_since: Optional[float] = None
        while time.monotonic() < deadline:
            st = await self.status()
            if st.state == ProcessState.STOPPED:
                if absent_since is None:
                    absent_since = time.monotonic()
                if time.monotonic() - absent_since >= 0.3:
                    return True
            else:
                absent_since = None
            await asyncio.sleep(0.1)
        return False


class ProcessSupervisor:
    """
    Supervises a managed process via a pluggable backend.

    Maintains:
    - Coordinator pause ownership (`was_stopped_by_coordinator`).
    - Manual user override (`is_manual_override`).
    - Event publishing (`process.stop_requested`, `process.stopped`, etc.).
    - Fine-grained permission delegation (`allow_external_stop`, `allow_external_restart`).
    """

    def __init__(
        self,
        backend: ProcessBackend,
        event_dispatcher: Optional[EventDispatcher] = None,
        allow_external_stop: Optional[bool] = None,
        allow_external_restart: Optional[bool] = None,
        state_persistence_path: str = "",
    ) -> None:
        self.backend = backend
        self.dispatcher = event_dispatcher or EventDispatcher()
        self.state_persistence_path = state_persistence_path
        self.was_stopped_by_coordinator = False
        self._stopped_external = False
        self.is_manual_override = False
        self.manual_override_until: Optional[float] = None
        self.consecutive_unexpected_exits = 0
        self._has_started = bool(getattr(backend, "running", False))
        self._lock = asyncio.Lock()

        if allow_external_stop is not None:
            self.backend.allow_external_stop = allow_external_stop
        if allow_external_restart is not None:
            self.backend.allow_external_restart = allow_external_restart

    def _persist_state(self, info: Optional[ProcessInfo] = None) -> None:
        if not self.state_persistence_path:
            return
        try:
            from resource_coordinator.core.durable_state import StateCodec

            if info is not None:
                is_running = info.state in {ProcessState.RUNNING, ProcessState.EXTERNAL_RUNNING}
                pid = info.pid if is_running else None
                create_time = info.create_time if is_running else None
                owner = info.lifecycle_owner.value
            else:
                state = StateCodec.load(self.state_persistence_path)
                existing = state.processes.get(self.name)
                pid = existing.pid if existing else None
                create_time = existing.create_time if existing else None
                owner = existing.lifecycle_owner if existing else ProcessLifecycleOwner.UNMANAGED.value

            StateCodec.record_process_state(
                self.state_persistence_path,
                self.name,
                pid=pid,
                create_time=create_time,
                lifecycle_owner=owner,
                was_stopped_by_coordinator=self.was_stopped_by_coordinator,
                is_manual_override=self.is_manual_override,
                manual_override_until=self.manual_override_until,
            )
        except Exception as exc:
            logger.error("Failed persisting process state for '%s': %s", self.name, exc)

    @property
    def name(self) -> str:
        return self.backend.name

    @property
    def allow_external_stop(self) -> bool:
        return getattr(self.backend, "allow_external_stop", False)

    @property
    def allow_external_restart(self) -> bool:
        return getattr(self.backend, "allow_external_restart", False)

    @property
    def generation(self) -> int:
        return getattr(self.backend, "generation", 0)

    @property
    def last_launch_log_offset(self) -> int:
        return getattr(self.backend, "last_launch_log_offset", 0)

    async def status(self) -> ProcessInfo:
        info = await self.backend.status()
        if info.state == ProcessState.RUNNING or info.last_started_at is not None:
            self._has_started = True
        return info

    def set_manual_override(
        self,
        paused: bool,
        *,
        persist: bool = True,
        until: Optional[float] = None,
    ) -> None:
        """Set an indefinite or deadline-bound manual pause override."""
        self.is_manual_override = paused
        self.manual_override_until = until if paused else None
        if paused:
            self.consecutive_unexpected_exits = 0
        if persist:
            self._persist_state()
        logger.info("Process '%s' manual override set to %s", self.name, paused)

    async def stop(self, timeout: float = 10.0, origin: str = "coordinator") -> bool:
        """Stop the process and track coordinator ownership."""
        async with self._lock:
            info = await self.backend.status()
            if info.state == ProcessState.STOPPED:
                if self.state_persistence_path:
                    self._persist_state(info)
                return True

            if info.lifecycle_owner == ProcessLifecycleOwner.EXTERNAL and not self.allow_external_stop:
                logger.warning(
                    "Process '%s' is externally owned and allow_external_stop is False; refusing stop",
                    self.name,
                )
                return False

            await self.dispatcher.emit(
                "process.stop_requested",
                {"name": self.name, "origin": origin, "timeout": timeout},
            )

            success = await self.backend.stop(timeout=timeout)
            if success:
                if origin == "coordinator":
                    self.was_stopped_by_coordinator = True
                    self.consecutive_unexpected_exits = 0
                    self._stopped_external = info.lifecycle_owner == ProcessLifecycleOwner.EXTERNAL
                elif origin == "shutdown":
                    self.was_stopped_by_coordinator = False
                if self.state_persistence_path:
                    self._persist_state(await self.backend.status())
                await self.dispatcher.emit(
                    "process.stopped",
                    {
                        "name": self.name,
                        "origin": origin,
                        "was_stopped_by_coordinator": self.was_stopped_by_coordinator,
                        "lifecycle_owner": info.lifecycle_owner.value,
                    },
                )
            else:
                await self.dispatcher.emit(
                    "process.failed",
                    {"name": self.name, "action": "stop", "origin": origin},
                )
            return success

    async def start(self, origin: str = "coordinator", only_if_stopped_by_coordinator: bool = True) -> bool:
        """
        Start the process.

        Respects manual override, coordinator ownership, and external restart permissions.
        """
        async with self._lock:
            if self.is_manual_override:
                logger.info("Process '%s' start skipped due to manual override", self.name)
                return False

            if only_if_stopped_by_coordinator and not self.was_stopped_by_coordinator:
                logger.info("Process '%s' start skipped: not stopped by coordinator", self.name)
                return False

            info = await self.backend.status()
            if info.state in {ProcessState.RUNNING, ProcessState.EXTERNAL_RUNNING}:
                self._has_started = True
                return True
            if info.state != ProcessState.STOPPED:
                return False

            if (
                self._stopped_external or info.lifecycle_owner == ProcessLifecycleOwner.EXTERNAL
            ) and not self.allow_external_restart:
                logger.warning(
                    "Process '%s' was externally launched and allow_external_restart is False; skipping start",
                    self.name,
                )
                return False

            await self.dispatcher.emit(
                "process.start_requested",
                {"name": self.name, "origin": origin},
            )

            success = await self.backend.start()
            if success:
                self._has_started = True
                self.was_stopped_by_coordinator = False
                if self.state_persistence_path:
                    self._persist_state(await self.backend.status())
                await self.dispatcher.emit(
                    "process.started",
                    {"name": self.name, "origin": origin},
                )
            else:
                await self.dispatcher.emit(
                    "process.failed",
                    {"name": self.name, "action": "start", "origin": origin},
                )
            return success

    async def wait_stopped(self, timeout: float = 10.0) -> bool:
        return await self.backend.wait_stopped(timeout=timeout)

    async def handle_unexpected_exit_backoff(
        self,
        lease_manager: Any,
        resource: str = "gpu.inference",
        max_retries: int = 3,
        base_backoff_seconds: float = 1.0,
    ) -> bool:
        """
        Inspect process status. If coordinator-owned process exited unexpectedly while
        system is safe idle, attempt bounded backoff restart or inhibit further attempts.
        """
        exhausted_count: Optional[int] = None
        async with self._lock:
            if self.is_manual_override or self.was_stopped_by_coordinator:
                return False

            # Check if resource is safe idle (including active cooldown or global restart block)
            if (
                lease_manager.active_count(resource) > 0
                or lease_manager.pending_count(resource) > 0
                or lease_manager.is_restart_inhibited(resource)
                or ( hasattr(lease_manager, "is_cooling_down") and lease_manager.is_cooling_down(resource) )
                or getattr(lease_manager, "restarts_blocked", False)
            ):
                return False

            info = await self.backend.status()
            if info.state != ProcessState.STOPPED:
                return False

            # Process unexpectedly exited while safe idle!
            self.consecutive_unexpected_exits += 1
            if self.consecutive_unexpected_exits > max_retries:
                exhausted_count = self.consecutive_unexpected_exits
            else:
                backoff = base_backoff_seconds * (2 ** (self.consecutive_unexpected_exits - 1))
                logger.warning(
                    "Process '%s' exited unexpectedly (crash #%d); waiting %.1fs backoff before restart",
                    self.name,
                    self.consecutive_unexpected_exits,
                    backoff,
                )
                await self.dispatcher.emit(
                    "process.crashed_restarting",
                    {"name": self.name, "attempt": self.consecutive_unexpected_exits, "backoff": backoff},
                )

        if exhausted_count is not None:
            # Release self._lock before acquiring lease_manager._lock to preserve canonical lock order
            logger.error(
                "Process '%s' exceeded maximum consecutive unexpected exits (%d); inhibiting restart",
                self.name,
                max_retries,
            )
            await lease_manager.inhibit_restart(
                resource=resource,
                reason=f"process_crash_loop_exhausted:{self.name}",
                holder_id=f"watchdog:{self.name}",
                details={"consecutive_exits": exhausted_count, "process": self.name},
            )
            await self.dispatcher.emit(
                "process.crash_loop_inhibited",
                {"name": self.name, "consecutive_exits": exhausted_count},
            )
            return False

        # Release lock during backoff sleep so incoming reservations or stop() are not blocked
        await asyncio.sleep(backoff)

        # Serialize final safety check and restart under lease_manager.run_if_idle -> self._lock
        started_result = False
        cancelled_by_override_or_stop = False

        async def _restart_if_still_stopped() -> None:
            nonlocal started_result, cancelled_by_override_or_stop
            async with self._lock:
                if self.is_manual_override or self.was_stopped_by_coordinator:
                    cancelled_by_override_or_stop = True
                    return
                info_now = await self.backend.status()
                if info_now.state != ProcessState.STOPPED:
                    return
                started_result = await self.backend.start()
                if started_result:
                    self._has_started = True
                    self.was_stopped_by_coordinator = False
                    if self.state_persistence_path:
                        self._persist_state(await self.backend.status())
                    await self.dispatcher.emit(
                        "process.started", {"name": self.name, "origin": "crash_recovery"}
                    )

        ran_idle = await lease_manager.run_if_idle(
            resource, _restart_if_still_stopped, check_self_cooldown=True
        )
        if not ran_idle or cancelled_by_override_or_stop:
            async with self._lock:
                self.consecutive_unexpected_exits = max(0, self.consecutive_unexpected_exits - 1)
            logger.info(
                "Process '%s' restart cancelled after backoff: resource '%s' busy/cooling/inhibited or override active",
                self.name,
                resource,
            )
            return False

        return started_result
