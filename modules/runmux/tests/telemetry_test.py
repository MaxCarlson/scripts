"""Comprehensive unit and integration tests for verified live resource telemetry."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psutil
from fastapi.testclient import TestClient

from runmux.models import RunRecord, parse_iso_datetime
from runmux.stats import ProcessStats, TelemetrySampler, verify_run_process
from runmux.store import RunStore
from runmux.web import create_runmux_web_app
from runmux.web_adapter import serialize_process_telemetry


def make_test_record(
    run_id: str = "20261024-010101-abcdef",
    status: str = "running",
    pid: int = 12345,
    started_at: str = "2026-10-24T00:00:00+00:00",
) -> RunRecord:
    return RunRecord(
        id=run_id,
        numeric_id=1,
        name="test-worker",
        status=status,
        created_at="2026-10-24T00:00:00+00:00",
        updated_at="2026-10-24T00:00:00+00:00",
        started_at=started_at,
        ended_at=None,
        exit_code=None,
        pid=pid,
        supervisor_pid=9999,
        program=sys.executable,
        argv_json="[]",
        cwd="C:\\work",
        env_overrides_json="{}",
        port=8080,
        auth_token="secret-token",
        log_path="C:\\work\\output.ansi",
        command_line="python worker.py",
        restart_of=None,
        duplicate_of=None,
        rows=24,
        columns=80,
    )


class MockLiveProcess:
    def __init__(
        self,
        pid: int,
        *,
        user_time: float = 1.0,
        system_time: float = 0.5,
        rss: int = 10 * 1024 * 1024,
        read_bytes: int = 50000,
        write_bytes: int = 25000,
        threads: int = 4,
        created_at: float | None = None,
    ) -> None:
        self.pid = pid
        self._user = user_time
        self._system = system_time
        self._rss = rss
        self._read = read_bytes
        self._write = write_bytes
        self._threads = threads
        self._created_at = created_at if created_at is not None else 1792800000.0

    def is_running(self) -> bool:
        return True

    def create_time(self) -> float:
        return self._created_at

    def num_threads(self) -> int:
        return self._threads

    def cpu_times(self) -> SimpleNamespace:
        return SimpleNamespace(user=self._user, system=self._system)

    def memory_info(self) -> SimpleNamespace:
        return SimpleNamespace(rss=self._rss)

    def io_counters(self) -> SimpleNamespace:
        return SimpleNamespace(read_bytes=self._read, write_bytes=self._write)

    def children(self, recursive: bool = True) -> list[Any]:
        return []


class MockPsutilHarness:
    class NoSuchProcess(Exception):
        pass

    class AccessDenied(Exception):
        pass

    class ZombieProcess(Exception):
        pass

    Error = Exception

    def __init__(
        self,
        processes: dict[int, Any] | None = None,
        *,
        cpu_count: int = 4,
        denied_pids: set[int] | None = None,
    ) -> None:
        self.processes = processes or {}
        self._cpu_count = cpu_count
        self.denied_pids = denied_pids or set()

    def Process(self, pid: int) -> Any:
        if pid in self.denied_pids:
            raise self.AccessDenied(f"Access denied for PID {pid}")
        if pid not in self.processes:
            raise self.NoSuchProcess(f"PID {pid} does not exist")
        return self.processes[pid]

    def cpu_count(self, logical: bool = True) -> int:
        return self._cpu_count

    def cpu_percent(self, interval: Any = None) -> float:
        return 15.5


def test_verify_run_process_states() -> None:
    # 1. Terminal run: unavailable
    finished_run = make_test_record(status="finished")
    root, reason = verify_run_process(MockPsutilHarness(), finished_run)
    assert root is None
    assert reason == "run is finished"

    # 2. Lost run: unavailable
    lost_run = make_test_record(status="lost")
    root, reason = verify_run_process(MockPsutilHarness(), lost_run)
    assert root is None
    assert reason == "run is lost"

    # 3. Missing PID: unavailable
    missing_run = make_test_record(pid=99999)
    root, reason = verify_run_process(MockPsutilHarness(), missing_run)
    assert root is None
    assert reason == "process exited"

    # 4. Permission denied PID: unavailable
    denied_run = make_test_record(pid=100)
    root, reason = verify_run_process(MockPsutilHarness(denied_pids={100}), denied_run)
    assert root is None
    assert reason == "permission denied"


def test_verify_run_process_detects_reused_pid() -> None:
    record = make_test_record(started_at="2026-10-24T00:00:00+00:00")
    dt = parse_iso_datetime(record.started_at)
    assert dt is not None
    started_epoch = dt.timestamp()

    # Process created 1 hour after run started => PID reuse
    reused_proc = MockLiveProcess(12345, created_at=started_epoch + 3600.0)
    harness = MockPsutilHarness(processes={12345: reused_proc})

    root, reason = verify_run_process(harness, record)
    assert root is None
    assert reason == "pid reused by another process"


def test_telemetry_sampler_cpu_multi_core_and_normalization() -> None:
    clock_time = 100.0
    sampler = TelemetrySampler(clock=lambda: clock_time)

    # Initial sample at clock_time = 100.0
    proc1 = MockLiveProcess(12345, user_time=2.0, system_time=1.0)  # total 3.0s CPU time
    harness1 = MockPsutilHarness(processes={12345: proc1}, cpu_count=4)
    record = make_test_record()

    first_sample = sampler.sample_run(record, psutil_module=harness1)
    assert first_sample.process_count == 1
    assert first_sample.thread_count == 4
    assert first_sample.rss_bytes == 10 * 1024 * 1024
    assert first_sample.cpu_percent is None  # Baseline establishing
    assert first_sample.cpu_percent_normalized is None
    assert first_sample.cpu_count == 4
    assert first_sample.read_bytes_per_second is None

    # Advance clock by 2.0s; process consumed 2.0s more user and 1.0s more system (total 3.0s CPU in 2s wall time)
    clock_time = 102.0
    proc2 = MockLiveProcess(12345, user_time=4.0, system_time=2.0, read_bytes=90000, write_bytes=45000)
    harness2 = MockPsutilHarness(processes={12345: proc2}, cpu_count=4)

    second_sample = sampler.sample_run(record, psutil_module=harness2)
    # CPU delta: (6.0 - 3.0) / 2.0s = 1.5s/s = 150.0% raw multi-core CPU
    assert second_sample.cpu_percent == 150.0
    # Normalized against 4 cores: 150.0% / 4 = 37.5%
    assert second_sample.cpu_percent_normalized == 37.5
    assert second_sample.cpu_count == 4
    # I/O delta: (90000 - 50000) / 2.0s = 20000 B/s read, (45000 - 25000) / 2.0s = 10000 B/s write
    assert second_sample.read_bytes_per_second == 20000.0
    assert second_sample.write_bytes_per_second == 10000.0
    assert second_sample.sample_interval_seconds == 2.0


def test_telemetry_sampler_aggregates_child_processes() -> None:
    clock_time = 50.0
    sampler = TelemetrySampler(clock=lambda: clock_time)

    root_proc = MockLiveProcess(
        100, user_time=1.0, system_time=0.5, rss=1000, read_bytes=500, write_bytes=200, threads=2
    )
    child_proc = MockLiveProcess(
        101, user_time=2.0, system_time=1.0, rss=2000, read_bytes=700, write_bytes=300, threads=3
    )
    root_proc.children = lambda recursive=True: [child_proc]

    harness = MockPsutilHarness(processes={100: root_proc, 101: child_proc}, cpu_count=8)
    record = make_test_record(pid=100)

    sample = sampler.sample_run(record, psutil_module=harness)
    assert sample.process_count == 2
    assert sample.thread_count == 5
    assert sample.rss_bytes == 3000
    assert sample.total_read_bytes == 1200
    assert sample.total_write_bytes == 500


def test_telemetry_network_isolation_and_provenance() -> None:
    # Verifies that host-level network is never put on process records
    sampler = TelemetrySampler()
    record = make_test_record()
    proc = MockLiveProcess(12345)
    harness = MockPsutilHarness(processes={12345: proc})

    sample = sampler.sample_run(record, psutil_module=harness)
    serialized = serialize_process_telemetry(sample)

    assert "net_read_bytes_per_second" not in serialized or serialized.get("net_read_bytes_per_second") is None
    assert "net_write_bytes_per_second" not in serialized or serialized.get("net_write_bytes_per_second") is None


def test_authenticated_api_telemetry_endpoints(tmp_path: Path) -> None:

    state_dir = tmp_path / "state"
    store = RunStore(state_dir)
    run_id = "20261024-123456-112233"
    run_dir = state_dir / "runs" / run_id
    run_dir.mkdir(parents=True)
    log_path = run_dir / "output.ansi"
    log_path.write_bytes(b"")

    # Use current test runner PID as a real living process
    current_pid = os.getpid()
    proc_create = psutil.Process(current_pid).create_time()
    started_iso = datetime.fromtimestamp(proc_create, tz=timezone.utc).isoformat()

    # Insert a managed run record in SQLite store
    store.create_run(
        run_id=run_id,
        name="test-worker",
        status="running",
        program="python",
        argv_json=json.dumps(["python", "worker.py"]),
        cwd=str(tmp_path),
        env_overrides_json="{}",
        auth_token="secret",
        log_path=log_path,
        command_line="python worker.py",
    )
    # Using existing current PID keeps status running and allows real process sampling
    store.update_run(run_id, pid=current_pid, supervisor_pid=current_pid, port=9000, started_at=started_iso)

    app = create_runmux_web_app(state_dir, login_code="test-login")

    with TestClient(app, base_url="http://localhost") as client:
        # 1. Unauthenticated request must return 401 or 403
        unauth = client.get(f"/api/runs/{run_id}/telemetry", headers={"Origin": "http://localhost"})
        assert unauth.status_code in {401, 403}

        # 2. Login to obtain session cookie
        login_res = client.post("/auth/login", json={"code": "test-login"}, headers={"Origin": "http://localhost"})
        assert login_res.status_code == 204

        # 3. Read single run telemetry
        res = client.get(f"/api/runs/{run_id}/telemetry", headers={"Origin": "http://localhost"})
        assert res.status_code == 200
        data = res.json()
        assert data["id"] == run_id
        assert data["status"] == "running"
        assert data["pid"] == current_pid
        assert data["process_count"] >= 1
        assert data["cpu_count"] >= 1
        assert data["rss_bytes"] is not None and data["rss_bytes"] > 0
        assert data["unavailable"] is None

        # 4. Read overview telemetry
        overview_res = client.get("/api/telemetry", headers={"Origin": "http://localhost"})
        assert overview_res.status_code == 200
        overview_data = overview_res.json()
        assert "runs" in overview_data
        assert "host" in overview_data
        assert isinstance(overview_data["runs"], list)
        assert isinstance(overview_data["host"], dict)
        assert len(overview_data["runs"]) == 1
        assert overview_data["runs"][0]["id"] == run_id
        assert "cpu_percent" in overview_data["host"]
        assert "memory_used_bytes" in overview_data["host"]

        # 5. Non-existent run returns 404
        missing_res = client.get("/api/runs/20261024-999999-000000/telemetry", headers={"Origin": "http://localhost"})
        assert missing_res.status_code == 404


def test_sampling_latency_is_non_blocking() -> None:
    # Verify that telemetry collection completes in single-digit milliseconds without blocking
    sampler = TelemetrySampler()
    record = make_test_record()
    proc = MockLiveProcess(12345)
    harness = MockPsutilHarness(processes={12345: proc})

    start = time.perf_counter()
    for _ in range(50):
        sampler.sample_run(record, psutil_module=harness)
    total_elapsed = time.perf_counter() - start

    # 50 samples should execute well under 100ms total (< 2ms per sample), never sleeping 1000ms!
    assert total_elapsed < 0.2


def test_verify_run_process_tight_pid_creation_bounds() -> None:
    record = make_test_record(started_at="2026-10-24T00:00:00+00:00")
    dt = parse_iso_datetime(record.started_at)
    assert dt is not None
    started_epoch = dt.timestamp()

    # 1. Process created 1.0s after start => normal spawn, accepted
    valid_proc = MockLiveProcess(12345, created_at=started_epoch + 1.0)
    harness = MockPsutilHarness(processes={12345: valid_proc})
    root, reason = verify_run_process(harness, record)
    assert root is not None
    assert reason is None

    # 2. Process created 10.0s after start => beyond 5.0s tolerance, rejected as recycled PID
    recycled_proc = MockLiveProcess(12345, created_at=started_epoch + 10.0)
    harness = MockPsutilHarness(processes={12345: recycled_proc})
    root, reason = verify_run_process(harness, record)
    assert root is None
    assert reason == "pid reused by another process"

    # 3. Process created 10.0s before start => pre-existing unrelated process, rejected
    older_proc = MockLiveProcess(12345, created_at=started_epoch - 10.0)
    harness = MockPsutilHarness(processes={12345: older_proc})
    root, reason = verify_run_process(harness, record)
    assert root is None
    assert reason == "pid reused by another process"


def test_overview_telemetry_latency_with_numerous_disconnected_runs(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    store = RunStore(state_dir)
    app = create_runmux_web_app(state_dir, login_code="test-login")

    # Create 25 synthetic runs with non-existent supervisor PIDs
    for i in range(25):
        run_id = f"20261024-000000-{i:06d}"
        run_dir = state_dir / "runs" / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "output.ansi").write_bytes(b"")
        store.create_run(
            run_id=run_id,
            name=f"worker-{i}",
            status="running",
            program="python",
            argv_json="[]",
            cwd=str(tmp_path),
            env_overrides_json="{}",
            auth_token="secret",
            log_path=run_dir / "output.ansi",
            command_line="python worker.py",
        )
        # supervisor_pid 999900+i does not exist in OS
        store.update_run(run_id, pid=999900 + i, supervisor_pid=999900 + i, port=40000 + i)

    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"code": "test-login"}, headers={"Origin": "http://localhost"})

        start = time.perf_counter()
        res = client.get("/api/telemetry", headers={"Origin": "http://localhost"})
        elapsed = time.perf_counter() - start

        assert res.status_code == 200
        payload = res.json()
        assert len(payload["runs"]) == 25
        # All 25 runs should be identified as lost / unavailable immediately without waiting 25 * 0.25s = 6.25s!
        assert elapsed < 1.0
        for run_item in payload["runs"]:
            assert run_item["status"] == "lost"
            assert run_item["unavailable"] == "run is lost"
            assert run_item["cpu_percent"] is None
            assert run_item["rss_bytes"] is None


def test_gpu_devices_caching_in_sampler(monkeypatch) -> None:
    import runmux.stats as stats_mod

    call_count = 0

    def mock_gpu_devices(timeout: float = 1.0):
        nonlocal call_count
        call_count += 1
        return [{"name": "MockGPU", "id": 0, "load": 25.0}]

    monkeypatch.setattr(stats_mod, "gpu_devices", mock_gpu_devices)

    clock_time = 500.0
    sampler = stats_mod.TelemetrySampler(clock=lambda: clock_time)

    # First call: invokes mock_gpu_devices
    devs1 = sampler._get_gpu_devices()
    assert len(devs1) == 1
    assert devs1[0]["name"] == "MockGPU"
    assert call_count == 1

    # Second call 0.5s later: returns cached data without calling mock_gpu_devices again
    clock_time = 500.5
    devs2 = sampler._get_gpu_devices()
    assert devs2 == devs1
    assert call_count == 1

    # Third call after 2.0s: cache expired, re-queries
    clock_time = 502.5
    devs3 = sampler._get_gpu_devices()
    assert devs3 == devs1
    assert call_count == 2


def test_unavailable_versus_zero_behavior() -> None:
    from runmux.stats import format_stats_table, stats_to_json

    record = make_test_record()

    # Case A: Active process genuinely using 0.0% CPU and 0 B/s I/O
    active_zero = ProcessStats(
        record=record,
        process_count=1,
        thread_count=1,
        cpu_percent=0.0,
        rss_bytes=1024,
        read_bytes_per_second=0.0,
        write_bytes_per_second=0.0,
        unavailable=None,
    )
    table_zero = format_stats_table([active_zero], width=120, color=False)
    json_zero = stats_to_json(active_zero)

    assert "  0.0%" in table_zero
    assert "R        0 B/s W        0 B/s" in table_zero
    assert json_zero["cpu_percent"] == 0.0
    assert json_zero["read_bytes_per_second"] == 0.0
    assert json_zero["unavailable"] is None

    # Case B: Unavailable process (e.g. exited or dead)
    unavailable_proc = ProcessStats(
        record=record,
        process_count=0,
        thread_count=0,
        cpu_percent=None,
        rss_bytes=None,
        read_bytes_per_second=None,
        write_bytes_per_second=None,
        unavailable="process exited",
    )
    table_unavail = format_stats_table([unavailable_proc], width=120, color=False)
    json_unavail = stats_to_json(unavailable_proc)

    # In table, unavailable metrics show placeholders '--'
    assert "--" in table_unavail
    assert "process exited" in table_unavail
    # In JSON, unavailable metrics are strictly null (None), not 0.0
    assert json_unavail["cpu_percent"] is None
    assert json_unavail["rss_bytes"] is None
    assert json_unavail["read_bytes_per_second"] is None
    assert json_unavail["unavailable"] == "process exited"
