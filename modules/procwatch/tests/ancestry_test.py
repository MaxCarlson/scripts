"""Unit tests for procwatch.correlator.ancestry."""

from __future__ import annotations

from procwatch.correlator.ancestry import ProcessTableCache, collapse_venv_shims
from procwatch.models import MissingMetadataReason


def test_ancestry_chain_and_missing_parent() -> None:
    cache = ProcessTableCache(boot_id="boot-test")
    p_root = cache.record_start(pid=100, ppid=999998, image_name="cmd.exe", monotonic_ns=1_000_000, enrich_live=False)
    p_child = cache.record_start(pid=200, ppid=100, image_name="python.exe", monotonic_ns=2_000_000, enrich_live=False)

    chain, complete = cache.get_ancestry(p_child.identity.proc_key)
    assert [n.identity.pid for n in chain] == [200, 100]
    # pid=999998 does not exist -> ancestry_complete is False, no fabricated parent
    assert complete is False
    assert MissingMetadataReason.EXITED_BEFORE_ENRICHMENT in p_root.missing_reasons


def test_pid_reuse_does_not_conflate_lifetimes() -> None:
    cache = ProcessTableCache(boot_id="boot-test")
    first = cache.record_start(pid=500, ppid=10, image_name="old.exe", monotonic_ns=1_000_000, enrich_live=False)
    second = cache.record_start(pid=500, ppid=20, image_name="new.exe", monotonic_ns=5_000_000, enrich_live=False)

    assert first.identity.proc_key != second.identity.proc_key
    assert first.is_alive is False
    assert first.exit_reason == "pid_reused"
    assert second.is_alive is True


def test_collapse_venv_shims_preserves_raw_nodes() -> None:
    cache = ProcessTableCache(boot_id="boot-test")
    agent = cache.record_start(pid=10, ppid=1, image_name="codex.exe", monotonic_ns=1_000_000, enrich_live=False)
    shim = cache.record_start(
        pid=20,
        ppid=10,
        image_name="python.exe",
        command_line=r"C:\repo\.venv\Scripts\python.exe worker.py",
        monotonic_ns=2_000_000,
        enrich_live=False,
    )
    base = cache.record_start(
        pid=30,
        ppid=20,
        image_name="python.exe",
        command_line=r"C:\Python312\python.exe worker.py",
        monotonic_ns=3_000_000,
        enrich_live=False,
    )

    raw_chain = [base, shim, agent]
    collapsed = collapse_venv_shims(raw_chain)
    assert [n.identity.pid for n in raw_chain] == [30, 20, 10]
    assert [n.identity.pid for n in collapsed] == [30, 10]
