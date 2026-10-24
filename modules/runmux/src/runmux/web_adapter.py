"""Read-only projection of Runmux process records and bounded output for the local browser view."""

from __future__ import annotations

import base64
import codecs
import concurrent.futures
import hashlib
import json
import re
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import psutil
from web_ui_tools.terminal import TerminalParserState, TerminalTextSanitizer

from runmux.constants import STATUS_LOST, TERMINAL_STATUSES
from runmux.ipc import IpcError, request_json
from runmux.models import RunRecord
from runmux.stats import HostTelemetry, ProcessStats, TelemetrySampler
from runmux.store import RunNotFoundError
from runmux.telemetry_store import TelemetryQueryPoint, TelemetryStore

RUN_ID_PATTERN = re.compile(r"\d{8}-\d{6}-[0-9a-f]{6}\Z")
DEFAULT_LOG_CHUNK_BYTES = 64 * 1024
MAX_LOG_CHUNK_BYTES = 64 * 1024
DEFAULT_TERMINAL_TAIL_BYTES = 128 * 1024
FINGERPRINT_BYTES = 32
CURSOR_MODES = {"text", "escape", "escape-intermediate", "csi", "osc", "string", "string-escape"}


class RegistryReadError(RuntimeError):
    """Raised when the existing Runmux registry cannot be read safely."""


@dataclass(frozen=True)
class OutputChunk:
    """Bounded decoded output and the next opaque, non-secret cursor."""

    state: str
    text: str
    cursor: str | None
    reset: bool
    truncated: bool
    message: str | None = None
    at_end: bool = False


@dataclass(frozen=True)
class TerminalChunk:
    """One bounded raw ANSI byte range for the interactive browser terminal."""

    state: str
    data: bytes
    offset: int | None
    generation: str | None
    reset: bool
    truncated: bool
    message: str | None = None
    at_end: bool = False


@dataclass(frozen=True)
class _Cursor:
    generation: str
    offset: int
    fingerprint: str
    parser: TerminalParserState


class ReadOnlyRunmux:
    """Query an existing registry using SQLite read-only mode without initialization or migration."""

    def __init__(
        self,
        state_dir: Path,
        *,
        sampler: TelemetrySampler | None = None,
        telemetry_store: TelemetryStore | None = None,
    ) -> None:
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.db_path = self.state_dir / "registry.sqlite3"
        self._telemetry_sampler = sampler or TelemetrySampler()
        self._telemetry_store = telemetry_store or TelemetryStore(self.state_dir, auto_init=False)

    def _connect(self) -> sqlite3.Connection:
        if not self.db_path.is_file():
            raise FileNotFoundError(self.db_path.name)
        try:
            connection = sqlite3.connect(self.db_path.as_uri() + "?mode=ro", uri=True, timeout=1.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA busy_timeout=1000")
            return connection
        except sqlite3.Error as error:
            raise RegistryReadError("The Runmux registry is unavailable for read-only access.") from error

    def list_runs(self) -> list[RunRecord]:
        """Return all active and completed records, newest active records first."""

        if not self.db_path.is_file():
            return []
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    "SELECT * FROM runs ORDER BY "
                    "CASE WHEN status IN ('pending', 'running', 'paused') THEN 0 ELSE 1 END, created_at DESC"
                ).fetchall()
            return [RunRecord.from_row(row) for row in rows]
        except (sqlite3.Error, OSError) as error:
            raise RegistryReadError("The Runmux registry is unavailable for read-only access.") from error

    def get_run(self, run_id: str) -> RunRecord:
        """Resolve an exact immutable full ID; numeric and abbreviated IDs are rejected."""

        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise RunNotFoundError("Run not found")
        try:
            with closing(self._connect()) as connection:
                row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        except FileNotFoundError as error:
            raise RunNotFoundError("Run not found") from error
        except (sqlite3.Error, OSError) as error:
            raise RegistryReadError("The Runmux registry is unavailable for read-only access.") from error
        if row is None:
            raise RunNotFoundError("Run not found")
        return RunRecord.from_row(row)

    def refresh_display_status(self, record: RunRecord, *, timeout: float = 0.25) -> tuple[RunRecord, str]:
        """Project supervisor status onto the response without writing it to SQLite."""

        if record.status in TERMINAL_STATUSES or record.port is None:
            return record, "not-active"
        try:
            response = request_json(record, op="status", timeout=timeout)
        except IpcError:
            if record.supervisor_pid is not None and not psutil.pid_exists(record.supervisor_pid):
                return replace(record, status=STATUS_LOST, exit_code=None), "disconnected"
            return record, "disconnected"

        updates: dict[str, Any] = {}
        status = response.get("status")
        if isinstance(status, str) and status in {"pending", "running", "paused", *TERMINAL_STATUSES}:
            updates["status"] = status
        for field in ("exit_code", "pid"):
            value = response.get(field)
            if value is None or isinstance(value, int):
                updates[field] = value
        return (replace(record, **updates) if updates else record), "connected"

    def get_run_telemetry(self, run_id: str, *, psutil_module: Any = None) -> dict[str, Any]:
        """Return verified resource telemetry for one run."""

        record = self.get_run(run_id)
        record, _ = self.refresh_display_status(record)
        stats = self._telemetry_sampler.sample_run(record, psutil_module=psutil_module)
        return serialize_process_telemetry(stats)

    def get_overview_telemetry(self, *, psutil_module: Any = None) -> dict[str, Any]:
        """Return overview resource telemetry for all active runs and host."""

        records = self.list_runs()
        active = [r for r in records if r.status not in TERMINAL_STATUSES]
        if not active:
            stats_list, host = self._telemetry_sampler.sample_active_runs([], psutil_module=psutil_module)
            return {"runs": [], "host": serialize_host_telemetry(host)}

        if len(active) == 1:
            refreshed = [self.refresh_display_status(active[0], timeout=0.1)[0]]
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(32, len(active))) as executor:
                refreshed = list(executor.map(lambda r: self.refresh_display_status(r, timeout=0.1)[0], active))

        stats_list, host = self._telemetry_sampler.sample_active_runs(refreshed, psutil_module=psutil_module)
        return {
            "runs": [serialize_process_telemetry(s) for s in stats_list],
            "host": serialize_host_telemetry(host),
        }


    def get_run_telemetry_history(
        self,
        run_id: str,
        *,
        since: float | None = None,
        until: float | None = None,
        max_points: int = 300,
        include_lineage: bool = False,
        include_events: bool = True,
    ) -> dict[str, Any]:
        """Return historical resource metrics and events for a managed run."""
        record = self.get_run(run_id)

        now = time.time()
        end_time = until if until is not None else now
        start_time = since if since is not None else (end_time - 3600.0)

        if start_time > end_time:
            raise ValueError(f"since ({start_time}) must be less than or equal to until ({end_time})")

        capped_max_points = max(10, min(max_points, 1000))

        if not include_lineage:
            points = self._telemetry_store.query_process_history(
                run_id,
                since=start_time,
                until=end_time,
                max_points=capped_max_points,
            )
            events = (
                self._telemetry_store.query_events(run_id, since=start_time, until=end_time)
                if include_events
                else []
            )
            raw_sample_count = self._telemetry_store.count_raw_samples(run_id, since=start_time, until=end_time)
        else:
            # Lineage traversal: resolve parent runs via restart_of
            chain: list[RunRecord] = [record]
            curr = record
            visited = {curr.id}
            while curr.restart_of:
                try:
                    parent = self.get_run(curr.restart_of)
                    if parent.id in visited:
                        break
                    visited.add(parent.id)
                    chain.append(parent)
                    curr = parent
                except RunNotFoundError:
                    break
            chain.reverse()

            combined_points: list[TelemetryQueryPoint] = []
            combined_events: list[dict[str, Any]] = []
            raw_sample_count = 0

            for i, run_rec in enumerate(chain):
                r_points = self._telemetry_store.query_process_history(
                    run_rec.id,
                    since=start_time,
                    until=end_time,
                    max_points=capped_max_points,
                )
                raw_sample_count += self._telemetry_store.count_raw_samples(
                    run_rec.id, since=start_time, until=end_time
                )
                if include_events:
                    combined_events.extend(
                        self._telemetry_store.query_events(run_rec.id, since=start_time, until=end_time)
                    )

                if i > 0 and combined_points and r_points:
                    prev_last = combined_points[-1]
                    curr_first = r_points[0]
                    if curr_first.epoch > prev_last.epoch:
                        gap_epoch = prev_last.epoch + 0.001
                        combined_points.append(
                            TelemetryQueryPoint(
                                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(gap_epoch)),
                                epoch=gap_epoch,
                                sample_interval_seconds=curr_first.epoch - prev_last.epoch,
                                cpu_percent=None,
                                cpu_percent_normalized=None,
                                rss_bytes=None,
                                read_bytes_per_second=None,
                                write_bytes_per_second=None,
                                process_count=0,
                                thread_count=0,
                                gpu_memory_bytes=None,
                                is_gap=True,
                                gap_reason=f"restart from {chain[i - 1].id} to {run_rec.id}",
                                run_id=chain[i - 1].id,
                            )
                        )
                        combined_events.append({
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(gap_epoch)),
                            "epoch": gap_epoch,
                            "event": "restart",
                            "old_run_id": chain[i - 1].id,
                            "new_run_id": run_rec.id,
                            "reason": f"restarted as {run_rec.id}",
                        })

                combined_points.extend(r_points)

            combined_events.sort(key=lambda e: float(e["epoch"]))
            if len(combined_points) > capped_max_points:
                points = self._telemetry_store._downsample_points(combined_points, capped_max_points)
            else:
                points = combined_points
            events = combined_events

        cores = 1
        try:
            import psutil
            cores = psutil.cpu_count(logical=True) or 1
        except Exception:
            pass

        duration = round(end_time - start_time, 3)
        provenance = {
            "cpu_scope": "process_tree",
            "cpu_unit": "percent (100% = 1 core)",
            "cpu_count": cores,
            "rss_unit": "bytes",
            "io_unit": "bytes_per_second",
            "gpu_unit": "bytes",
            "time_range": {
                "start": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start_time)),
                "end": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(end_time)),
                "duration_seconds": duration,
            },
            "resolution": "raw" if duration <= 3600.0 else "rollup",
            "raw_sample_count": raw_sample_count,
            "returned_points": len(points),
        }

        return {
            "run_id": record.id,
            "numeric_id": record.numeric_id,
            "status": record.status,
            "provenance": provenance,
            "series": [serialize_telemetry_query_point(p) for p in points],
            "events": events,
        }

    def get_overview_telemetry_history(
        self,
        *,
        since: float | None = None,
        until: float | None = None,
        max_points: int = 300,
    ) -> dict[str, Any]:
        """Return historical system-wide host telemetry."""
        now = time.time()
        end_time = until if until is not None else now
        start_time = since if since is not None else (end_time - 3600.0)

        if start_time > end_time:
            raise ValueError(f"since ({start_time}) must be less than or equal to until ({end_time})")

        capped_max_points = max(10, min(max_points, 1000))
        series = self._telemetry_store.query_host_history(
            since=start_time,
            until=end_time,
            max_points=capped_max_points,
        )

        duration = round(end_time - start_time, 3)
        return {
            "provenance": {
                "scope": "host",
                "cpu_unit": "percent (0.0 - 100.0%)",
                "memory_unit": "bytes",
                "net_unit": "bytes_per_second (host-wide aggregate)",
                "time_range": {
                    "start": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start_time)),
                    "end": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(end_time)),
                    "duration_seconds": duration,
                },
                "returned_points": len(series),
            },
            "series": series,
        }


def serialize_telemetry_query_point(point: TelemetryQueryPoint) -> dict[str, Any]:
    """Serialize a single historical telemetry point according to the API contract."""
    res: dict[str, Any] = {
        "timestamp": point.timestamp,
        "epoch": point.epoch,
        "sample_interval_seconds": point.sample_interval_seconds,
        "cpu_percent": point.cpu_percent,
        "cpu_percent_normalized": point.cpu_percent_normalized,
        "cpu_percent_min": point.cpu_percent_min,
        "cpu_percent_max": point.cpu_percent_max,
        "rss_bytes": point.rss_bytes,
        "rss_bytes_max": point.rss_bytes_max,
        "read_bytes_per_second": point.read_bytes_per_second,
        "write_bytes_per_second": point.write_bytes_per_second,
        "process_count": point.process_count,
        "thread_count": point.thread_count,
        "gpu_memory_bytes": point.gpu_memory_bytes,
    }
    if point.run_id is not None:
        res["run_id"] = point.run_id
    if point.is_gap:
        res["is_gap"] = True
        res["gap_reason"] = point.gap_reason
    return res


def serialize_process_telemetry(stats: ProcessStats) -> dict[str, Any]:
    """Serialize verified process-tree telemetry for browser views without secret leakage."""

    return {
        "id": stats.record.id,
        "numeric_id": stats.record.numeric_id,
        "status": stats.record.status,
        "pid": stats.record.pid,
        "process_count": stats.process_count,
        "thread_count": stats.thread_count,
        "cpu_percent": stats.cpu_percent,
        "cpu_percent_normalized": stats.cpu_percent_normalized,
        "cpu_count": stats.cpu_count,
        "cpu_time_seconds": stats.cpu_time_seconds,
        "rss_bytes": stats.rss_bytes,
        "read_bytes_per_second": stats.read_bytes_per_second,
        "write_bytes_per_second": stats.write_bytes_per_second,
        "total_read_bytes": stats.total_read_bytes,
        "total_write_bytes": stats.total_write_bytes,
        "gpu_memory_bytes": stats.gpu_memory_bytes,
        "unavailable": stats.unavailable,
        "sampled_at": stats.sampled_at,
        "sample_interval_seconds": stats.sample_interval_seconds,
    }


def serialize_host_telemetry(host: HostTelemetry) -> dict[str, Any]:
    """Serialize host-scoped telemetry."""

    return {
        "cpu_percent": host.cpu_percent,
        "cpu_count": host.cpu_count,
        "memory_used_bytes": host.memory_used_bytes,
        "memory_available_bytes": host.memory_available_bytes,
        "memory_total_bytes": host.memory_total_bytes,
        "memory_percent": host.memory_percent,
        "net_read_bytes_per_second": host.net_read_bytes_per_second,
        "net_write_bytes_per_second": host.net_write_bytes_per_second,
        "gpu_devices": host.gpu_devices,
        "sampled_at": host.sampled_at,
    }


def serialize_run(record: RunRecord, *, connection: str = "unchecked") -> dict[str, Any]:
    """Return the browser metadata allowlist; omit paths, arguments, environment, and IPC credentials."""

    program = record.program.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    name = TerminalTextSanitizer().feed(record.name or "")[:128]
    return {
        "id": record.id,
        "name": name,
        "command": TerminalTextSanitizer().feed(program)[:128],
        "status": record.status,
        "connection": connection,
        "pid": record.pid,
        "exit_code": record.exit_code,
        "runtime_seconds": record.runtime_seconds,
        "created_at": record.created_at,
        "started_at": record.started_at,
        "ended_at": record.ended_at,
        "restart_of": record.restart_of,
        "duplicate_of": record.duplicate_of,
    }


def read_output_chunk(
    path: Path,
    *,
    state_dir: Path,
    run_id: str,
    cursor: str | None = None,
    max_bytes: int = DEFAULT_LOG_CHUNK_BYTES,
    finished: bool = False,
) -> OutputChunk:
    """Read one bounded log chunk, detect replacement/truncation, decode UTF-8 and strip terminal controls."""

    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("Run ID must be a full immutable Runmux ID.")
    if max_bytes < 1 or max_bytes > MAX_LOG_CHUNK_BYTES:
        raise ValueError(f"max_bytes must be between 1 and {MAX_LOG_CHUNK_BYTES}.")
    root = Path(state_dir).expanduser().resolve()
    expected_path = (root / "runs" / run_id / "output.ansi").resolve()
    stored_path = Path(path).expanduser()
    if stored_path.is_absolute():
        selected_path = stored_path.resolve()
    else:
        selected_path = (root / stored_path).resolve()
        if selected_path != expected_path:
            # Older records may contain a state-dir-relative path produced while
            # Runmux was launched with a relative --state-dir.
            selected_path = stored_path.resolve()
    if selected_path != expected_path:
        raise ValueError("Output path does not belong to the selected run.")
    if not selected_path.is_file():
        return OutputChunk("missing", "", cursor, False, False, "Output is not available.")

    try:
        with selected_path.open("rb") as stream:
            stat = _file_stat(stream)
            generation = f"{stat.st_dev:x}:{stat.st_ino:x}"
            size = stat.st_size
            previous = _parse_cursor(cursor) if cursor else None
            reset = previous is None or previous.generation != generation or previous.offset > size
            if previous is not None and not reset:
                reset = not _fingerprint_matches(stream, previous)
            if reset:
                start = max(0, size - max_bytes)
                parser_state = TerminalParserState()
                truncated = start > 0
            else:
                start = previous.offset
                parser_state = previous.parser
                truncated = False

            stream.seek(start)
            data = stream.read(max_bytes)
            read_reached_eof = stream.tell() >= _file_stat(stream).st_size
            if reset and start > 0:
                line_end = data.find(b"\n")
                if line_end >= 0:
                    start += line_end + 1
                    data = data[line_end + 1 :]
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            decoded = decoder.decode(data, final=finished and read_reached_eof)
            buffered = decoder.getstate()[0]
            next_offset = start + len(data) - len(buffered)
            sanitizer = TerminalTextSanitizer(state=parser_state)
            sanitized = sanitizer.feed(decoded)
            # The ANSI parser state is carried in the cursor so split escape sequences stay hidden.
            next_cursor = _make_cursor(stream, generation, next_offset, sanitizer.state)
            return OutputChunk("available", sanitized, next_cursor, reset, truncated, at_end=next_offset >= size)
    except PermissionError:
        return OutputChunk("inaccessible", "", cursor, False, False, "Output cannot be read.")
    except FileNotFoundError:
        return OutputChunk("missing", "", cursor, False, False, "Output is not available.")
    except OSError:
        return OutputChunk("inaccessible", "", cursor, False, False, "Output cannot be read.")


def read_terminal_chunk(
    path: Path,
    *,
    state_dir: Path,
    run_id: str,
    offset: int | None = None,
    generation: str | None = None,
    max_bytes: int = MAX_LOG_CHUNK_BYTES,
    initial_tail_bytes: int = DEFAULT_TERMINAL_TAIL_BYTES,
) -> TerminalChunk:
    """Read raw ANSI bytes from the selected run's log using bounded file access."""

    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("Run ID must be a full immutable Runmux ID.")
    if max_bytes < 1 or max_bytes > MAX_LOG_CHUNK_BYTES:
        raise ValueError(f"max_bytes must be between 1 and {MAX_LOG_CHUNK_BYTES}.")
    if initial_tail_bytes < 1:
        raise ValueError("initial_tail_bytes must be greater than zero.")

    root = Path(state_dir).expanduser().resolve()
    expected_path = (root / "runs" / run_id / "output.ansi").resolve()
    stored_path = Path(path).expanduser()
    if stored_path.is_absolute():
        selected_path = stored_path.resolve()
    else:
        selected_path = (root / stored_path).resolve()
        if selected_path != expected_path:
            selected_path = stored_path.resolve()
    if selected_path != expected_path:
        raise ValueError("Output path does not belong to the selected run.")
    if not selected_path.is_file():
        return TerminalChunk("missing", b"", offset, generation, False, False, "Output is not available.")

    try:
        with selected_path.open("rb") as stream:
            stat = _file_stat(stream)
            current_generation = f"{stat.st_dev:x}:{stat.st_ino:x}"
            size = stat.st_size
            reset = offset is None or generation != current_generation or offset > size
            truncated = False
            if reset:
                start = max(0, size - initial_tail_bytes)
                truncated = start > 0
                if truncated:
                    stream.seek(start)
                    prefix = stream.read(min(4096, size - start))
                    line_end = prefix.find(b"\n")
                    if line_end >= 0:
                        start += line_end + 1
            else:
                start = offset
            stream.seek(start)
            data = stream.read(max_bytes)
            next_offset = start + len(data)
            return TerminalChunk(
                "available",
                data,
                next_offset,
                current_generation,
                reset,
                truncated,
                at_end=next_offset >= _file_stat(stream).st_size,
            )
    except PermissionError:
        return TerminalChunk("inaccessible", b"", offset, generation, False, False, "Output cannot be read.")
    except FileNotFoundError:
        return TerminalChunk("missing", b"", offset, generation, False, False, "Output is not available.")
    except OSError:
        return TerminalChunk("inaccessible", b"", offset, generation, False, False, "Output cannot be read.")


def _file_stat(stream: Any) -> Any:
    import os

    return os.fstat(stream.fileno())


def _fingerprint_matches(stream: Any, cursor: _Cursor) -> bool:
    if cursor.offset == 0:
        return cursor.fingerprint == ""
    stream.seek(max(0, cursor.offset - FINGERPRINT_BYTES))
    previous_bytes = stream.read(min(FINGERPRINT_BYTES, cursor.offset))
    return hashlib.sha256(previous_bytes).hexdigest() == cursor.fingerprint


def _make_cursor(stream: Any, generation: str, offset: int, parser: TerminalParserState) -> str:
    stream.seek(max(0, offset - FINGERPRINT_BYTES))
    previous_bytes = stream.read(min(FINGERPRINT_BYTES, offset))
    value = {
        "generation": generation,
        "offset": offset,
        "fingerprint": hashlib.sha256(previous_bytes).hexdigest() if offset else "",
        "mode": parser.mode,
        "sequence_length": parser.sequence_length,
    }
    payload = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _parse_cursor(value: str) -> _Cursor:
    if len(value) > 512:
        raise ValueError("Invalid output cursor.")
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        generation = payload["generation"]
        offset = payload["offset"]
        fingerprint = payload["fingerprint"]
        mode = payload["mode"]
        sequence_length = payload["sequence_length"]
        if (
            not isinstance(generation, str)
            or not re.fullmatch(r"[0-9a-f]+:[0-9a-f]+", generation)
            or not isinstance(offset, int)
            or offset < 0
            or not isinstance(fingerprint, str)
            or (fingerprint and not re.fullmatch(r"[0-9a-f]{64}", fingerprint))
            or mode not in CURSOR_MODES
            or not isinstance(sequence_length, int)
            or not 0 <= sequence_length <= 4096
        ):
            raise ValueError
        return _Cursor(generation, offset, fingerprint, TerminalParserState(mode, sequence_length))
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Invalid output cursor.") from error
