"""Current-run measurements must distinguish coordinator and actual worker work."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

from PIL import Image


def test_pipeline_resolves_submillisecond_work_with_high_resolution_clock(monkeypatch):
    import compresser.timing as timing

    clock = [0.0]
    monkeypatch.setattr(timing.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(timing.time, "perf_counter", lambda: clock[0])
    with timing.pipeline_scope() as metrics:
        with timing.phase("metadata_lookup"):
            clock[0] = 0.0005
    assert metrics.report()["coordinator_seconds"]["metadata_lookup"] == 0.0005


def test_pipeline_nested_scopes_are_exclusive_and_run_context_is_reset(monkeypatch):
    import compresser.timing as timing

    clock = [0.0]
    monkeypatch.setattr(timing.time, "perf_counter", lambda: clock[0])
    with timing.pipeline_scope() as metrics:
        with timing.phase("enumeration"):
            clock[0] = 2
            with timing.timing_scope():
                with timing.phase("header_read"):
                    clock[0] = 5
            clock[0] = 7
        report = metrics.report()
    assert report["coordinator_seconds"] == {"enumeration": 4, "header_read": 3}
    assert report["worker_seconds"] == {}
    assert report["wall_seconds"] == 7
    assert timing.current_pipeline() is None
    json.dumps(report)


def test_pipeline_collects_real_worker_scopes_without_shared_trace_stacks(monkeypatch):
    import compresser.timing as timing

    with timing.pipeline_scope() as metrics:
        barrier = threading.Barrier(2)

        def work():
            with timing.execution_role("worker"), timing.phase("encoding"):
                barrier.wait(timeout=2)
                metrics.increment("encoded_images")

        with ThreadPoolExecutor(2) as pool:
            jobs = [pool.submit(copy_context().run, work) for _ in range(2)]
            for job in jobs:
                job.result(timeout=3)
        report = metrics.report()
    assert report["counters"]["encoded_images"] == 2
    assert report["worker_seconds"]["encoding"] >= 0
    assert report["coordinator_seconds"] == {}


def test_inventory_json_contains_current_scan_counters_and_warm_reuse(tmp_path, capsys):
    from compresser.cli import main

    root = tmp_path / "library"
    root.mkdir()
    Image.new("RGB", (40, 40)).save(root / "01.png")
    args = ["-i", str(root), "-l", "-I", str(tmp_path / "inventory.sqlite3"), "-J"]
    assert main(args) == 0
    cold = json.loads(capsys.readouterr().out)["pipeline"]
    assert cold["counters"]["headers_inspected"] == 1
    assert cold["counters"].get("unreadable_images", 0) == 0
    assert cold["counters"]["inventory_connections"] >= 1
    assert cold["counters"]["inventory_queries"] >= 1
    assert cold["counters"]["inventory_commits"] >= 1
    assert cold["settings"]["requested_workers"] >= 1
    assert cold["settings"]["inventory_effective_workers"] == 1
    assert cold["settings"]["memory_budget_mib"] == 512
    assert {"enumeration", "metadata_lookup", "header_read", "publication"} <= cold["coordinator_seconds"].keys()
    assert main(args) == 0
    warm = json.loads(capsys.readouterr().out)["pipeline"]
    assert warm["counters"]["headers_reused"] == 1
    assert warm["counters"].get("headers_inspected", 0) == 0
    assert warm["coordinator_seconds"].get("header_read", 0) == 0


def test_compression_json_reports_actual_worker_phases_not_old_cache_timings(tmp_path, capsys):
    from compresser.cli import main

    source = tmp_path / "01.png"
    Image.new("RGB", (40, 40)).save(source)
    args = ["-i", str(source), "-f", "webp", "-e", "0", "-J"]
    assert main(args) == 0
    cold = json.loads(capsys.readouterr().out)["pipeline"]
    assert cold["worker_seconds"]["encoding"] >= 0
    assert main(args) == 0
    warm = json.loads(capsys.readouterr().out)["pipeline"]
    assert warm["worker_seconds"].get("encoding", 0) == 0
    assert warm["coordinator_seconds"]["cache"] >= 0


def test_file_only_pipeline_reports_stats_without_header_reads(tmp_path, capsys):
    from compresser.cli import main

    root = tmp_path / "library"
    root.mkdir()
    (root / "01.jpg").write_bytes(b"not decoded")
    assert main(["-i", str(root), "-l", "-D", "files", "-J"]) == 0
    report = json.loads(capsys.readouterr().out)["pipeline"]
    assert report["counters"]["scanned_candidates"] == 1
    assert report["counters"].get("headers_inspected", 0) == 0
    assert {"enumeration", "filesystem_metadata", "publication"} <= report["coordinator_seconds"].keys()


def test_failed_phase_is_measured_and_iterator_does_not_charge_consumer(monkeypatch):
    import pytest
    import compresser.timing as timing

    clock = [0.0]
    monkeypatch.setattr(timing.time, "perf_counter", lambda: clock[0])

    def source():
        clock[0] += 2
        yield 1

    with timing.pipeline_scope() as metrics:
        for _ in timing.phase_iter(source(), "enumeration"):
            clock[0] += 10
        with pytest.raises(ValueError):
            with timing.phase("validation"):
                clock[0] += 3
                raise ValueError("fixture invalid source")
    assert metrics.report()["coordinator_seconds"] == {"enumeration": 2, "validation": 3}
