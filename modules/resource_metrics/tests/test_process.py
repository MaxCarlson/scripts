from types import SimpleNamespace

from resource_metrics.process import process_tree, process_tree_snapshot, process_io


class FakeProcess:
    def __init__(self, pid, cpu=5.0, rss=100, threads=2):
        self.pid, self.cpu, self.rss, self.threads = pid, cpu, rss, threads

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
        return SimpleNamespace(read_bytes=10)


class FakePsutil:
    Error = RuntimeError

    def Process(self, pid):
        return FakeProcess(pid)


def test_process_tree_snapshot_aggregates():
    snapshot = process_tree_snapshot(42, psutil_module=FakePsutil())
    assert snapshot["pid"] == 42
    assert snapshot["cpu_percent"] is None
    assert snapshot["cpu_time_seconds"] == 3.0
    sampled = process_tree_snapshot(42, psutil_module=FakePsutil(), previous_cpu_time_seconds=2.0,
                                    elapsed_seconds=2.0)
    assert sampled["cpu_percent"] == 50.0
    assert snapshot["rss_bytes"] > 0
    assert snapshot["threads"] > 0


def test_process_tree_allows_injected_psutil_module():
    assert process_tree(5, psutil_module=FakePsutil())[0].pid == 5
    assert process_io(FakeProcess(5)).read_bytes == 10
