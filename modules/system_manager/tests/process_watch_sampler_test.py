"""Unit tests for system_manager.process_watch sampling, filtering, sorting, topology, and export."""

from __future__ import annotations

import json
from types import SimpleNamespace

import psutil
import pytest

from system_manager.process_watch.exporter import render_csv, render_json, render_rich_table, write_export_file
from system_manager.process_watch.filters import ProcessFilter, filter_processes, group_processes, sort_processes
from system_manager.process_watch.models import redact_sensitive_text
from system_manager.process_watch.sampler import ProcessSampler, get_ancestry_chain


class FakeProc:
    def __init__(
        self,
        pid: int,
        *,
        ppid: int = 0,
        name: str = "proc.exe",
        create_time: float = 100.0,
        cpu_user: float = 1.0,
        cpu_system: float = 0.5,
        rss: int = 1024 * 1024,
        read_bytes: int = 1000,
        write_bytes: int = 500,
        cmdline: list[str] | None = None,
        exe: str = "",
        deny_io: bool = False,
        deny_all: bool = False,
    ) -> None:
        self.pid = pid
        self._ppid = ppid
        self._name = name
        self._create_time = create_time
        self._cpu_user = cpu_user
        self._cpu_system = cpu_system
        self._rss = rss
        self._read_bytes = read_bytes
        self._write_bytes = write_bytes
        self._cmdline = cmdline or [name]
        self._exe = exe or f"/usr/bin/{name}"
        self._deny_io = deny_io
        self._deny_all = deny_all

    @property
    def info(self):
        if self._deny_all:
            raise psutil.AccessDenied(self.pid)
        return {
            "pid": self.pid,
            "ppid": self._ppid,
            "name": self._name,
            "exe": self._exe,
            "cmdline": self._cmdline,
            "username": "tester",
            "status": "running",
            "create_time": self._create_time,
            "cpu_times": SimpleNamespace(user=self._cpu_user, system=self._cpu_system),
            "memory_info": SimpleNamespace(rss=self._rss, vms=self._rss * 2, private=self._rss // 2),
            "num_threads": 2,
        }

    def io_counters(self):
        if self._deny_io:
            raise psutil.AccessDenied(self.pid)
        return SimpleNamespace(read_bytes=self._read_bytes, write_bytes=self._write_bytes)

    def num_handles(self):
        return 10


class FakePsutil:
    NoSuchProcess = psutil.NoSuchProcess
    AccessDenied = psutil.AccessDenied
    ZombieProcess = psutil.ZombieProcess
    Error = psutil.Error

    def __init__(self, procs: list[FakeProc], *, logical_cpus: int = 4) -> None:
        self.procs = procs
        self.logical_cpus = logical_cpus

    def process_iter(self, attrs, ad_value=None):
        return list(self.procs)

    def cpu_count(self, logical=True):
        return self.logical_cpus

    def cpu_percent(self, interval=None):
        return 12.5

    def virtual_memory(self):
        return SimpleNamespace(used=4 * 1024**3, total=16 * 1024**3, percent=25.0)

    def disk_io_counters(self):
        return SimpleNamespace(read_bytes=10000, write_bytes=20000)


class FakeGpuMonitor:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    def snapshot(self, *, force: bool = False) -> dict:
        self.calls += 1
        return dict(self.payload)


def test_sampler_cpu_io_deltas_normalization_and_counter_reset():
    clock = [100.0]
    p1 = FakeProc(10, name="alpha.exe", create_time=50.0, cpu_user=1.0, cpu_system=0.0, read_bytes=1000, write_bytes=500)
    fps = FakePsutil([p1], logical_cpus=4)
    sampler = ProcessSampler(psutil_module=fps, monotonic_clock=lambda: clock[0], wall_clock=lambda: 1000.0)

    snap1 = sampler.sample()
    assert len(snap1.processes) == 1
    assert snap1.processes[0].cpu_percent is None
    assert snap1.processes[0].io_read_rate is None

    # Advance 2 seconds; cpu_time +1.0s -> 50% raw, 12.5% normalized on 4 cores
    clock[0] = 102.0
    p1._cpu_user = 2.0
    p1._read_bytes = 3000
    p1._write_bytes = 1500
    snap2 = sampler.sample()
    s2 = snap2.processes[0]
    assert s2.cpu_percent == pytest.approx(50.0)
    assert s2.cpu_percent_normalized == pytest.approx(12.5)
    assert s2.io_read_rate == pytest.approx(1000.0)
    assert s2.io_write_rate == pytest.approx(500.0)
    assert s2.io_total_rate == pytest.approx(1500.0)

    # Counter reset on read_bytes should yield None instead of negative rate
    clock[0] = 103.0
    p1._cpu_user = 2.5
    p1._read_bytes = 100
    p1._write_bytes = 2500
    snap3 = sampler.sample()
    s3 = snap3.processes[0]
    assert s3.io_read_rate is None
    assert s3.io_write_rate == pytest.approx(1000.0)


def test_sampler_pid_reuse_and_exited_grace():
    clock = [10.0]
    p_old = FakeProc(42, name="old.exe", create_time=1.0, cpu_user=5.0, read_bytes=5000)
    fps = FakePsutil([p_old])
    sampler = ProcessSampler(
        psutil_module=fps,
        monotonic_clock=lambda: clock[0],
        wall_clock=lambda: 1000.0,
        exited_grace_seconds=3.0,
    )
    sampler.sample()

    # Replace PID 42 with a new process (different create_time)
    clock[0] = 11.0
    p_new = FakeProc(42, name="new.exe", create_time=9.5, cpu_user=0.1, read_bytes=10)
    fps.procs = [p_new]
    snap2 = sampler.sample()

    live = [p for p in snap2.processes if not p.is_exited]
    exited = [p for p in snap2.processes if p.is_exited]
    assert len(live) == 1
    assert live[0].name == "new.exe"
    assert live[0].cpu_percent is None  # Must not compute delta against old PID's counters
    assert live[0].io_read_rate is None
    assert len(exited) == 1
    assert exited[0].name == "old.exe"

    # After grace expires, exited process is pruned
    clock[0] = 16.0
    snap3 = sampler.sample()
    assert all(not p.is_exited for p in snap3.processes)


def test_sampler_permission_errors_and_gpu_unavailable():
    clock = [10.0]
    p_ok = FakeProc(1, name="ok.exe", deny_io=True)
    p_denied = FakeProc(2, name="secret.exe", deny_all=True)
    fps = FakePsutil([p_ok, p_denied])
    gpu_mon = FakeGpuMonitor({"backend": "unavailable", "available": False, "devices": [], "process_memory": {}})
    sampler = ProcessSampler(
        enable_gpu=True,
        gpu_monitor=gpu_mon,
        psutil_module=fps,
        monotonic_clock=lambda: clock[0],
    )
    snap = sampler.sample()
    assert len(snap.processes) == 1
    assert snap.processes[0].pid == 1
    assert snap.processes[0].io_read_rate is None
    assert snap.processes[0].gpu_memory_bytes is None
    assert snap.host.gpu_backend == "unavailable"


def test_topology_and_subtree_aggregation_no_double_count():
    clock = [10.0]
    root = FakeProc(100, ppid=1, name="root.exe", cpu_user=1.0, rss=1000)
    child1 = FakeProc(101, ppid=100, name="child1.exe", cpu_user=2.0, rss=2000)
    child2 = FakeProc(102, ppid=100, name="child2.exe", cpu_user=3.0, rss=3000)
    grand = FakeProc(103, ppid=101, name="grand.exe", cpu_user=4.0, rss=4000)
    fps = FakePsutil([root, child1, child2, grand])
    sampler = ProcessSampler(psutil_module=fps, monotonic_clock=lambda: clock[0])
    sampler.sample()

    clock[0] = 11.0
    root._cpu_user += 0.1
    child1._cpu_user += 0.2
    child2._cpu_user += 0.3
    grand._cpu_user += 0.4
    snap = sampler.sample()

    by_pid = {p.pid: p for p in snap.processes}
    assert by_pid[100].child_count == 2
    assert by_pid[100].descendant_count == 3
    assert by_pid[100].subtree_rss_bytes == 10000
    assert by_pid[100].subtree_cpu_percent == pytest.approx(100.0)
    assert by_pid[101].subtree_rss_bytes == 6000
    assert [p.pid for p in get_ancestry_chain(by_pid[103], by_pid)] == [100, 101, 103]


def test_filtering_sorting_and_grouping():
    clock = [10.0]
    p1 = FakeProc(10, ppid=1, name="python.exe", rss=500, cmdline=["python.exe", "--token=secret123"])
    p2 = FakeProc(20, ppid=10, name="node.exe", rss=300, cmdline=["node.exe", "worker.js"])
    p3 = FakeProc(30, ppid=10, name="python.exe", rss=None if False else 100, cmdline=["python.exe", "helper.py"])
    fps = FakePsutil([p1, p2, p3])
    sampler = ProcessSampler(psutil_module=fps, monotonic_clock=lambda: clock[0])
    snap = sampler.sample()

    # Include OR + exclude
    flt = ProcessFilter(include_globs=["*python*", "node*"], exclude_globs=["*node*"])
    filtered = filter_processes(snap.processes, flt, snap.children_map)
    assert [p.pid for p in filtered] == [10, 30]

    # PID recursive
    flt_pid = ProcessFilter(pids=[10], recursive=True)
    assert {p.pid for p in filter_processes(snap.processes, flt_pid, snap.children_map)} == {10, 20, 30}

    # Cmdline opt-in
    assert filter_processes(snap.processes, ProcessFilter(include_globs=["*worker*"]), snap.children_map) == []
    assert [
        p.pid
        for p in filter_processes(
            snap.processes, ProcessFilter(include_globs=["*worker*"], match_cmdline=True), snap.children_map
        )
    ] == [20]

    # Missing values sort last regardless of direction
    snap.processes[0].cpu_percent = 10.0
    snap.processes[1].cpu_percent = None
    snap.processes[2].cpu_percent = 50.0
    desc = sort_processes(snap.processes, "cpu", descending=True)
    asc = sort_processes(snap.processes, "cpu", descending=False)
    assert [p.pid for p in desc] == [30, 10, 20]
    assert [p.pid for p in asc] == [10, 30, 20]

    # Grouping
    groups = group_processes(snap.processes, "name")
    assert len(groups) == 2
    assert groups[0].member_count in (1, 2)


def test_redaction_and_exports(tmp_path):
    assert redact_sensitive_text("app --token=abc123 https://user:pw@host/api") == "app --token=*** https://user:***@host/api"
    assert redact_sensitive_text('app --password="my secret" --api-key=\'k 1\'') == "app --password=*** --api-key=***"
    assert redact_sensitive_text("app --access-token tok999 postgres://u:p@db:5432/app") == "app --access-token *** postgres://u:***@db:5432/app"
    assert redact_sensitive_text("curl -H 'Authorization: Bearer secret.jwt.tok'") == "curl -H 'Authorization: Bearer ***'"
    assert redact_sensitive_text("DB_PASSWORD=topsecret MY_API_KEY=\"val 2\" app") == "DB_PASSWORD=*** MY_API_KEY=*** app"

    clock = [10.0]
    p1 = FakeProc(10, name="app.exe", cmdline=["app.exe", "--api-key=supersecret"])
    fps = FakePsutil([p1])
    sampler = ProcessSampler(psutil_module=fps, monotonic_clock=lambda: clock[0])
    snap = sampler.sample()

    j_text = render_json(snap, snap.processes)
    payload = json.loads(j_text)
    assert payload["processes"][0]["cmdline_redacted"] == "app.exe --api-key=***"
    assert "supersecret" not in j_text

    csv_text = render_csv(snap.processes)
    assert "app.exe --api-key=***" in csv_text
    assert "supersecret" not in csv_text

    rich_text = render_rich_table(snap, snap.processes)
    assert "app.exe" in rich_text

    out_file = tmp_path / "out.json"
    write_export_file(out_file, j_text, force=False)
    with pytest.raises(FileExistsError):
        write_export_file(out_file, j_text, force=False)
    write_export_file(out_file, j_text, force=True)


def test_large_process_list_performance():
    clock = [10.0]
    procs = [FakeProc(1000 + i, ppid=1000 if i > 0 else 0, name=f"worker_{i % 10}.exe") for i in range(500)]
    fps = FakePsutil(procs)
    sampler = ProcessSampler(psutil_module=fps, monotonic_clock=lambda: clock[0])
    snap1 = sampler.sample()
    clock[0] = 11.0
    snap2 = sampler.sample()
    assert len(snap2.processes) == 500
    assert snap1.host.sample_duration_ms < 2000.0
    assert snap2.host.sample_duration_ms < 2000.0


def test_deep_and_shallow_tree_aggregation_complexity():
    clock = [10.0]
    # Deep chain of 1000 processes: 1000 -> 1001 -> ... -> 1999
    deep_procs = [FakeProc(1000 + i, ppid=(999 + i if i > 0 else 0), rss=100) for i in range(1000)]
    fps_deep = FakePsutil(deep_procs)
    sampler_deep = ProcessSampler(psutil_module=fps_deep, monotonic_clock=lambda: clock[0])
    snap_deep = sampler_deep.sample()
    by_pid_deep = {p.pid: p for p in snap_deep.processes}
    assert by_pid_deep[1000].descendant_count == 999
    assert by_pid_deep[1000].subtree_rss_bytes == 100_000
    assert by_pid_deep[1999].descendant_count == 0
    assert by_pid_deep[1999].depth == 999
    assert snap_deep.host.sample_duration_ms < 2000.0

    # Shallow wide tree: 1 root + 999 direct children
    shallow_procs = [FakeProc(2000, ppid=0, rss=100)] + [
        FakeProc(2001 + i, ppid=2000, rss=100) for i in range(999)
    ]
    fps_shallow = FakePsutil(shallow_procs)
    sampler_shallow = ProcessSampler(psutil_module=fps_shallow, monotonic_clock=lambda: clock[0])
    snap_shallow = sampler_shallow.sample()
    by_pid_shallow = {p.pid: p for p in snap_shallow.processes}
    assert by_pid_shallow[2000].child_count == 999
    assert by_pid_shallow[2000].descendant_count == 999
    assert by_pid_shallow[2000].subtree_rss_bytes == 100_000
