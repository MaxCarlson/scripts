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


@dataclass(frozen=True)
class ProcessInfo:
    """Snapshot of a process's state and ownership."""

    name: str
    state: ProcessState
    pid: Optional[int] = None
    create_time: Optional[float] = None
    executable: Optional[str] = None
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
            "is_coordinator_owned": self.is_coordinator_owned,
            "last_stopped_at": self.last_stopped_at,
            "last_started_at": self.last_started_at,
        }


class ProcessBackend(Protocol):
    """Protocol for managed process backends."""

    name: str

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
    ) -> None:
        self.name = name
        self.executable = executable
        self.running = running
        self.is_coordinator_owned = not external if running else False
        self.fail_start = fail_start
        self.fail_stop = fail_stop
        self.stop_delay = stop_delay
        self.start_delay = start_delay
        self.pid = 12345 if running else None
        self.create_time = time.time() if running else None
        self.last_stopped_at: Optional[float] = None
        self.last_started_at: Optional[float] = time.time() if running else None

    async def status(self) -> ProcessInfo:
        if not self.running:
            state = ProcessState.STOPPED
        elif not self.is_coordinator_owned:
            state = ProcessState.EXTERNAL_RUNNING
        else:
            state = ProcessState.RUNNING

        return ProcessInfo(
            name=self.name,
            state=state,
            pid=self.pid,
            create_time=self.create_time,
            executable=self.executable,
            is_coordinator_owned=self.is_coordinator_owned,
            last_stopped_at=self.last_stopped_at,
            last_started_at=self.last_started_at,
        )

    async def start(self) -> bool:
        if self.start_delay > 0:
            await asyncio.sleep(self.start_delay)
        if self.fail_start:
            return False
        self.running = True
        self.is_coordinator_owned = True
        self.pid = 12345
        self.create_time = time.time()
        self.last_started_at = time.time()
        return True

    async def stop(self, timeout: float = 10.0) -> bool:
        if self.stop_delay > 0:
            await asyncio.sleep(self.stop_delay)
        if self.fail_stop:
            return False
        self.running = False
        self.pid = None
        self.create_time = None
        self.last_stopped_at = time.time()
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
    """

    def __init__(
        self,
        name: str,
        executable: str,
        arguments: Optional[Sequence[str]] = None,
        working_directory: Optional[str] = None,
        new_console: bool = False,
        adopt_external: bool = False,
    ) -> None:
        self.name = name
        self.executable = executable
        self.arguments = list(arguments or [])
        self.working_directory = working_directory
        self.new_console = new_console
        self.adopt_external = adopt_external

        self._proc: Optional[subprocess.Popen] = None
        self._owned_pid: Optional[int] = None
        self._owned_create_time: Optional[float] = None
        self._last_started_at: Optional[float] = None
        self._last_stopped_at: Optional[float] = None

    def _same_executable(self, process: psutil.Process) -> bool:
        try:
            exe = process.exe()
            expected = os.path.normcase(os.path.realpath(self.executable))
            actual = os.path.normcase(os.path.realpath(exe))
            if actual == expected:
                return True
            if not os.path.isabs(self.executable):
                return process.name().casefold() == Path(self.executable).name.casefold()
            return False
        except (psutil.Error, OSError):
            return False

    def _find_owned_process(self) -> Optional[psutil.Process]:
        if self._owned_pid is None:
            return None
        try:
            p = psutil.Process(self._owned_pid)
            if self._owned_create_time is not None:
                if abs(p.create_time() - self._owned_create_time) > 0.05:
                    return None
            if not self._same_executable(p):
                return None
            return p
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    def _find_external_process(self) -> Optional[psutil.Process]:
        for p in psutil.process_iter(["name", "exe"]):
            if self._same_executable(p):
                return p
        return None

    async def status(self) -> ProcessInfo:
        owned = self._find_owned_process()
        if owned is not None and owned.is_running():
            return ProcessInfo(
                name=self.name,
                state=ProcessState.RUNNING,
                pid=owned.pid,
                create_time=owned.create_time(),
                executable=self.executable,
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
            is_coordinator_owned=False,
            last_stopped_at=self._last_stopped_at,
            last_started_at=self._last_started_at,
        )

    async def start(self) -> bool:
        st = await self.status()
        if st.state == ProcessState.RUNNING:
            logger.info("Process '%s' is already running (owned)", self.name)
            return True
        if st.state == ProcessState.EXTERNAL_RUNNING and not self.adopt_external:
            logger.warning("Process '%s' is running externally and not adopted; refusing start", self.name)
            return False

        launch_kwargs: Dict[str, Any] = {
            "cwd": self.working_directory or None,
            "shell": False,
        }
        if self.new_console and os.name == "nt":
            launch_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x10)
        else:
            launch_kwargs.update(
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        cmd = [self.executable, *self.arguments]
        try:
            self._proc = subprocess.Popen(cmd, **launch_kwargs)
            self._owned_pid = self._proc.pid
            p = psutil.Process(self._proc.pid)
            self._owned_create_time = p.create_time()
            self._last_started_at = time.time()
            logger.info("Started process '%s' (PID %d)", self.name, self._owned_pid)
            return True
        except Exception as exc:
            logger.error("Failed to start process '%s': %s", self.name, exc)
            return False

    async def stop(self, timeout: float = 10.0) -> bool:
        st = await self.status()
        if st.state == ProcessState.STOPPED:
            return True

        if st.state == ProcessState.EXTERNAL_RUNNING and not self.adopt_external:
            logger.warning("Process '%s' is running externally and cannot be stopped", self.name)
            return False

        p = self._find_owned_process()
        if p is None and self.adopt_external:
            p = self._find_external_process()

        if p is None:
            self._proc = None
            self._owned_pid = None
            self._owned_create_time = None
            return True

        try:
            p.terminate()
            stopped = await self.wait_stopped(timeout=timeout)
            if not stopped:
                logger.warning("Process '%s' did not terminate in time; killing", self.name)
                p.kill()
                stopped = await self.wait_stopped(timeout=3.0)
            if stopped:
                self._last_stopped_at = time.time()
                self._proc = None
                self._owned_pid = None
                self._owned_create_time = None
            return stopped
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            self._proc = None
            self._owned_pid = None
            self._owned_create_time = None
            return True
        except Exception as exc:
            logger.error("Error stopping process '%s': %s", self.name, exc)
            return False

    async def wait_stopped(self, timeout: float = 10.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            st = await self.status()
            if st.state == ProcessState.STOPPED:
                return True
            await asyncio.sleep(0.1)
        return False


class ProcessSupervisor:
    """
    Supervises a managed process via a pluggable backend.

    Maintains:
    - Coordinator pause ownership (`was_stopped_by_coordinator`).
    - Manual user override (`is_manual_override`).
    - Event publishing (`process.stop_requested`, `process.stopped`, etc.).
    """

    def __init__(
        self,
        backend: ProcessBackend,
        event_dispatcher: Optional[EventDispatcher] = None,
    ) -> None:
        self.backend = backend
        self.dispatcher = event_dispatcher or EventDispatcher()
        self.was_stopped_by_coordinator = False
        self.is_manual_override = False
        self._lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return self.backend.name

    async def status(self) -> ProcessInfo:
        return await self.backend.status()

    def set_manual_override(self, paused: bool) -> None:
        """Set or clear manual pause override."""
        self.is_manual_override = paused
        logger.info("Process '%s' manual override set to %s", self.name, paused)

    async def stop(self, timeout: float = 10.0, origin: str = "coordinator") -> bool:
        """Stop the process and track coordinator ownership."""
        async with self._lock:
            info = await self.backend.status()
            if info.state == ProcessState.STOPPED:
                return True

            await self.dispatcher.emit(
                "process.stop_requested",
                {"name": self.name, "origin": origin, "timeout": timeout},
            )

            success = await self.backend.stop(timeout=timeout)
            if success:
                if origin == "coordinator":
                    self.was_stopped_by_coordinator = True
                await self.dispatcher.emit(
                    "process.stopped",
                    {
                        "name": self.name,
                        "origin": origin,
                        "was_stopped_by_coordinator": self.was_stopped_by_coordinator,
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

        Respects manual override and coordinator ownership policies.
        """
        async with self._lock:
            if self.is_manual_override:
                logger.info("Process '%s' start skipped due to manual override", self.name)
                return False

            if only_if_stopped_by_coordinator and not self.was_stopped_by_coordinator:
                logger.info("Process '%s' start skipped: not stopped by coordinator", self.name)
                return False

            info = await self.backend.status()
            if info.state == ProcessState.RUNNING:
                return True

            await self.dispatcher.emit(
                "process.start_requested",
                {"name": self.name, "origin": origin},
            )

            success = await self.backend.start()
            if success:
                self.was_stopped_by_coordinator = False
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
