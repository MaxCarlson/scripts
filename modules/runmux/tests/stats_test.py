from __future__ import annotations

from types import SimpleNamespace

from runmux.cli import build_parser, handle_stats
from runmux.models import RunRecord
from runmux.stats import (
    ProcessStats,
    build_process_stats,
    confirm_quit,
    format_stats_table,
    net_delta,
    stats_to_json,
)


class FakePsutil:
    Error = RuntimeError


class FakeProcess:
    def __init__(
        self,
        *,
        pid: int,
        threads: int,
        cpu: float,
        rss: int,
        read_bytes: int,
        write_bytes: int,
    ) -> None:
        self.pid = pid
        self._threads = threads
        self._cpu = cpu
        self._rss = rss
        self._read_bytes = read_bytes
        self._write_bytes = write_bytes

    def num_threads(self) -> int:
        return self._threads

    def cpu_percent(self, interval=None) -> float:
        return self._cpu

    def memory_info(self):
        return SimpleNamespace(rss=self._rss)

    def io_counters(self):
        return SimpleNamespace(read_bytes=self._read_bytes, write_bytes=self._write_bytes)


def make_record() -> RunRecord:
    return RunRecord(
        id="20260611-010101-abcdef",
        numeric_id=2,
        name=None,
        status="running",
        created_at="2026-06-11T00:00:00+00:00",
        updated_at="2026-06-11T00:00:00+00:00",
        started_at="2026-06-11T00:00:00+00:00",
        ended_at=None,
        exit_code=None,
        pid=123,
        supervisor_pid=456,
        program="python",
        argv_json="[]",
        cwd="C:\\work",
        env_overrides_json="{}",
        port=999,
        auth_token="token",
        log_path="C:\\work\\output.ansi",
        command_line="python busy.py",
        restart_of=None,
        duplicate_of=None,
        rows=24,
        columns=80,
    )


def test_stats_command_parses_once_json(tmp_path) -> None:
    args = build_parser().parse_args(["--state-dir", str(tmp_path), "stats", "--once", "--json", "--refresh", "0.2"])

    assert args.func is handle_stats
    assert args.once is True
    assert args.json is True
    assert args.refresh == 0.2


def test_build_process_stats_aggregates_process_tree(monkeypatch) -> None:
    record = make_record()
    processes = [
        FakeProcess(
            pid=123,
            threads=4,
            cpu=12.5,
            rss=1000,
            read_bytes=5000,
            write_bytes=2000,
        ),
        FakeProcess(
            pid=124,
            threads=2,
            cpu=3.5,
            rss=500,
            read_bytes=9000,
            write_bytes=3000,
        ),
    ]

    monkeypatch.setattr("runmux.stats.get_process_tree", lambda psutil, pid: processes)

    stats = build_process_stats(FakePsutil, record, previous_io=(1000, 1000), interval_seconds=2.0)

    assert stats.process_count == 2
    assert stats.thread_count == 6
    assert stats.cpu_percent == 16.0
    assert stats.rss_bytes == 1500
    assert stats.read_bytes_per_second == 6500.0
    assert stats.write_bytes_per_second == 2000.0


def test_stats_table_and_json_include_resource_fields() -> None:
    record = make_record()
    stats = ProcessStats(
        record,
        process_count=1,
        thread_count=4,
        cpu_percent=12.5,
        rss_bytes=1024,
        read_bytes_per_second=2048,
        write_bytes_per_second=4096,
    )

    table = format_stats_table([stats], width=120)
    payload = stats_to_json(stats)

    assert "CPU" in table
    assert "DISK I/O" in table
    assert "net(system)" in table
    assert "GPU" in table
    assert "python busy.py" in table
    assert payload["numeric_id"] == 2
    assert "thread_count" in payload
    assert "net_read_bytes_per_second" in payload


def test_stats_table_cells_share_header_columns_without_ansi_padding() -> None:
    record = make_record()
    stats = ProcessStats(
        record,
        process_count=1,
        thread_count=4,
        cpu_percent=12.5,
        rss_bytes=1024,
        read_bytes_per_second=2048,
        write_bytes_per_second=4096,
    )

    lines = format_stats_table([stats], width=120, color=False).splitlines()
    header = lines[2]
    row = lines[4]

    assert header.index("GPU") == row.index("--")
    assert header.index("P/T") == row.index("1/4")


def test_stats_table_can_colorize_status_and_metrics() -> None:
    record = make_record()
    stats = ProcessStats(
        record,
        process_count=1,
        thread_count=4,
        cpu_percent=82.0,
        rss_bytes=1024,
        read_bytes_per_second=2048,
        write_bytes_per_second=4096,
    )

    table = format_stats_table([stats], width=120, title="runmux stats", color=True)

    assert "\x1b[1;36mrunmux stats\x1b[0m" in table
    assert "\x1b[32mrunning " in table
    assert "\x1b[31m  82.0%\x1b[0m" in table


def test_net_delta_formats_rates() -> None:
    assert net_delta((100, 50), (1100, 1050), 2.0) == (500.0, 500.0)


def test_confirm_quit_accepts_y(monkeypatch) -> None:
    monkeypatch.setattr("runmux.stats.sys.platform", "linux")
    fake_input = type("Input", (), {"read": lambda self, n: "y"})()
    monkeypatch.setattr("runmux.stats.sys.stdin", fake_input)

    assert confirm_quit() is True


def test_network_delta_placed_in_host_not_process(monkeypatch) -> None:
    record = make_record()
    processes = [FakeProcess(pid=123, threads=1, cpu=5.0, rss=100, read_bytes=100, write_bytes=100)]
    monkeypatch.setattr("runmux.stats.get_process_tree", lambda psutil, pid: processes)

    stats = build_process_stats(
        FakePsutil,
        record,
        previous_io=(50, 50),
        interval_seconds=1.0,
        system_net_delta=(1000.0, 2000.0),
    )

    # Truth in attribution: process net stats must NOT claim host network traffic
    assert stats.net_read_bytes_per_second is None
    assert stats.net_write_bytes_per_second is None
    assert stats.host_net_read_bytes_per_second == 1000.0
    assert stats.host_net_write_bytes_per_second == 2000.0


def test_verify_run_process_detects_terminal_and_missing() -> None:
    from runmux.stats import verify_run_process

    finished_record = make_record()
    object.__setattr__(finished_record, "status", "finished")

    root, reason = verify_run_process(FakePsutil, finished_record)
    assert root is None
    assert reason == "run is finished"

    class MockPsutil:
        class NoSuchProcess(Exception):
            pass

        Error = Exception

        def Process(self, pid):
            raise self.NoSuchProcess("No such process")

    active_record = make_record()
    root, reason = verify_run_process(MockPsutil(), active_record)
    assert root is None
    assert reason == "process exited"


def test_verify_run_process_detects_pid_reuse() -> None:
    from runmux.stats import verify_run_process

    class MockReusedProcess:
        def is_running(self):
            return True

        def create_time(self):
            # Created at 2026-06-11T01:00:00 (1 hour after run start 00:00:00)
            return 1781139600.0

    class MockPsutil:
        Error = Exception

        def Process(self, pid):
            return MockReusedProcess()

    record = make_record()
    root, reason = verify_run_process(MockPsutil(), record)
    assert root is None
    assert reason == "pid reused by another process"


def test_telemetry_sampler_monotonic_deltas() -> None:
    from runmux.stats import TelemetrySampler

    simulated_time = 1000.0

    class FakeTreeProcess:
        def __init__(self, pid, user_time, read_b):
            self.pid = pid
            self.user_time = user_time
            self.read_b = read_b

        def is_running(self):
            return True

        def num_threads(self):
            return 2

        def cpu_times(self):
            return SimpleNamespace(user=self.user_time, system=0.0)

        def memory_info(self):
            return SimpleNamespace(rss=4096)

        def io_counters(self):
            return SimpleNamespace(read_bytes=self.read_b, write_bytes=500)

        def create_time(self):
            return 1781136000.0

    class MockPsutil:
        Error = Exception

        def __init__(self, user_time=1.0, read_b=1000):
            self.user_time = user_time
            self.read_b = read_b

        def Process(self, pid):
            return FakeTreeProcess(pid, self.user_time, self.read_b)

        def cpu_count(self, logical=True):
            return 2

    sampler = TelemetrySampler(clock=lambda: simulated_time)
    record = make_record()

    # First sample: baseline established, rates are None (no sleeping!)
    mock1 = MockPsutil(user_time=1.0, read_b=1000)
    first = sampler.sample_run(record, psutil_module=mock1)
    assert first.process_count == 1
    assert first.rss_bytes == 4096
    assert first.cpu_percent is None
    assert first.read_bytes_per_second is None
    assert first.cpu_count == 2

    # Second sample: 2.0 seconds elapsed, 1.0s more CPU time, 2000 bytes read
    simulated_time = 1002.0
    mock2 = MockPsutil(user_time=2.0, read_b=3000)
    second = sampler.sample_run(record, psutil_module=mock2)
    # (2.0 - 1.0) / 2.0 = 50% CPU raw; normalized = 25% on 2 cores
    assert second.cpu_percent == 50.0
    assert second.cpu_percent_normalized == 25.0
    # (3000 - 1000) / 2.0 = 1000 B/s
    assert second.read_bytes_per_second == 1000.0
    assert second.sample_interval_seconds == 2.0
