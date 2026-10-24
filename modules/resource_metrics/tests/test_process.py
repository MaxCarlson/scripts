from types import SimpleNamespace

from resource_metrics.process import process_io, process_tree, process_tree_snapshot


class FakeProcess:
    def __init__(self, pid, cpu=5.0, rss=100, threads=2, read_bytes=10, write_bytes=20, is_alive=True):
        self.pid = pid
        self.cpu = cpu
        self.rss = rss
        self.threads = threads
        self.read_bytes = read_bytes
        self.write_bytes = write_bytes
        self._alive = is_alive

    def is_running(self):
        return self._alive

    def children(self, recursive=False):
        return []

    def cpu_percent(self, interval=None):
        return self.cpu

    def cpu_times(self):
        return SimpleNamespace(user=2.0, system=1.0)

    def memory_info(self):
        return SimpleNamespace(rss=self.rss)

    def num_threads(self):
        return self.threads

    def io_counters(self):
        if self.read_bytes is None:
            raise AttributeError("io_counters not supported")
        return SimpleNamespace(read_bytes=self.read_bytes, write_bytes=self.write_bytes)

    def create_time(self):
        return 1700000000.0


class FakePsutil:
    Error = RuntimeError

    def __init__(self, fail_pids=None, logical_cpu_count=4):
        self.fail_pids = fail_pids or set()
        self._cpu_count = logical_cpu_count

    def Process(self, pid):
        if pid in self.fail_pids:
            raise FakePsutil.Error(f"PID {pid} access denied or missing")
        return FakeProcess(pid)

    def cpu_count(self, logical=True):
        return self._cpu_count


def test_process_tree_snapshot_aggregates():
    fake = FakePsutil()
    snapshot = process_tree_snapshot(42, psutil_module=fake)
    assert snapshot["pid"] == 42
    assert snapshot["cpu_percent"] is None
    assert snapshot["cpu_percent_normalized"] is None
    assert snapshot["cpu_time_seconds"] == 3.0
    assert snapshot["cpu_count"] == 4
    sampled = process_tree_snapshot(
        42,
        psutil_module=fake,
        previous_cpu_time_seconds=2.0,
        elapsed_seconds=2.0,
    )
    assert sampled["cpu_percent"] == 50.0
    assert sampled["cpu_percent_normalized"] == 12.5
    assert snapshot["rss_bytes"] > 0
    assert snapshot["threads"] > 0
    assert snapshot["read_bytes"] == 10
    assert snapshot["write_bytes"] == 20
    assert snapshot["io_supported"] is True


def test_process_tree_snapshot_multicore_normalized():
    # 4-core machine: if 2 cores are maxed out, cpu_percent=200%, normalized=50%
    fake = FakePsutil(logical_cpu_count=4)
    sampled = process_tree_snapshot(
        100,
        psutil_module=fake,
        previous_cpu_time_seconds=0.0,
        elapsed_seconds=1.0,
    )
    # user=2.0 + system=1.0 = 3.0s CPU time in 1.0s elapsed => 300% raw, 75% normalized
    assert sampled["cpu_percent"] == 300.0
    assert sampled["cpu_percent_normalized"] == 75.0
    assert sampled["cpu_count"] == 4


def test_process_tree_allows_injected_psutil_module():
    assert process_tree(5, psutil_module=FakePsutil())[0].pid == 5
    assert process_io(FakeProcess(5)).read_bytes == 10


def test_process_tree_handles_invalid_pid_and_errors():
    fake = FakePsutil(fail_pids={999})
    assert process_tree(None, psutil_module=fake) == []
    assert process_tree(0, psutil_module=fake) == []
    assert process_tree(-1, psutil_module=fake) == []
    assert process_tree(999, psutil_module=fake) == []
    assert process_tree_snapshot(999, psutil_module=fake) is None


def test_process_tree_filters_dead_children():
    root = FakeProcess(10)
    dead_child = FakeProcess(11, is_alive=False)
    live_child = FakeProcess(12, is_alive=True)
    root.children = lambda recursive=False: [dead_child, live_child]

    fake = FakePsutil()
    fake.Process = lambda pid: root

    tree = process_tree(10, psutil_module=fake)
    assert [p.pid for p in tree] == [10, 12]


def test_process_tree_io_unsupported_fallback():
    p = FakeProcess(20, read_bytes=None)
    assert process_io(p) is None

    fake = FakePsutil()
    fake.Process = lambda pid: p
    snapshot = process_tree_snapshot(20, psutil_module=fake)
    assert snapshot["io_supported"] is False
    assert snapshot["read_bytes"] is None
    assert snapshot["write_bytes"] is None
