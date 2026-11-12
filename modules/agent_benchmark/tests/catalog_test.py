"""Tests for the unified benchmark, dataset, and cohort catalog."""

from __future__ import annotations

import pytest

from agent_benchmark.benchmarks import (
    BenchmarkCatalog,
    BenchmarkDescriptor,
    DatasetDescriptor,
    get_default_catalog,
    get_unified_discovery,
    select_tasks,
)
from agent_benchmark.harbor.datasets import (
    DATASETS,
    resolve_dataset,
    select_tasks as harbor_select_tasks,
)
from agent_benchmark.suite import COHORTS, load_cohort


def test_default_catalog_contains_harbor_and_direct_benchmarks():
    catalog = get_default_catalog()
    benchmarks = {b.id: b for b in catalog.list_benchmarks()}
    assert "aider" in benchmarks
    assert "terminal-bench" in benchmarks
    assert "ifeval" in benchmarks
    assert "livecodebench" in benchmarks

    # Check backends
    backends = {b.id for b in catalog.list_backends()}
    assert "harbor" in backends
    assert "direct_chat" in backends

    # Check scorers
    scorers = {s.id for s in catalog.list_scorers()}
    assert "harbor_verifier" in scorers
    assert "ifeval_official" in scorers
    assert "lcb_official" in scorers


def test_default_catalog_datasets():
    catalog = get_default_catalog()
    datasets = {d.id: d for d in catalog.list_datasets()}
    assert "aider/aider-polyglot" in datasets
    assert "terminal-bench/terminal-bench@4.0.0" in datasets
    assert "terminal-bench/terminal-bench-2" in datasets
    assert "ifeval/google-2023" in datasets
    assert "livecodebench/release_v6" in datasets

    # Uninstalled benchmarks are flagged registered
    assert datasets["ifeval/google-2023"].install_state == "registered"
    assert datasets["livecodebench/release_v6"].install_state == "registered"
    assert datasets["aider/aider-polyglot"].install_state == "installed"


def test_alias_resolution_and_collision_rejection():
    catalog = BenchmarkCatalog()
    desc = DatasetDescriptor(
        id="test/ds1",
        name="Test DS 1",
        version="1.0.0",
        description="Test dataset",
        supported_languages=("python",),
        all_tasks=("t1", "t2"),
        default_scoring_protocol="single-attempt-v1",
    )
    catalog.register_dataset(desc, aliases=["ds1-alias", "ds1-alias2"])

    assert catalog.resolve_dataset("test/ds1").id == "test/ds1"
    assert catalog.resolve_dataset("ds1-alias").id == "test/ds1"
    assert catalog.resolve_dataset("ds1-alias2").id == "test/ds1"

    # Collision rejection for duplicate ID
    with pytest.raises(ValueError, match="already registered"):
        catalog.register_dataset(desc)

    # Collision rejection for duplicate alias
    desc2 = DatasetDescriptor(
        id="test/ds2",
        name="Test DS 2",
        version="1.0.0",
        description="Test dataset 2",
        supported_languages=("python",),
        all_tasks=("t3",),
        default_scoring_protocol="single-attempt-v1",
    )
    with pytest.raises(ValueError, match="collides with existing"):
        catalog.register_dataset(desc2, aliases=["ds1-alias"])


def test_unknown_dataset_resolution_lists_valid_options():
    catalog = get_default_catalog()
    with pytest.raises(KeyError) as exc_info:
        catalog.resolve_dataset("unknown-ds-999")
    assert "aider/aider-polyglot" in str(exc_info.value)


def test_harbor_facade_parity():
    # resolve_dataset facade
    d1 = resolve_dataset("aider/aider-polyglot")
    assert d1.id == "aider/aider-polyglot"
    assert len(d1.all_tasks) == 225

    # DATASETS dict access
    assert "aider-polyglot" in DATASETS
    assert DATASETS["terminal-bench-2"].id == "terminal-bench/terminal-bench-2"

    # Terminal-Bench 2.0 has 89 tasks
    assert len(DATASETS["terminal-bench-2"].all_tasks) == 89


def test_suite_cohorts_facade_parity():
    assert "aider-python-10" in COHORTS
    cohort = COHORTS["aider-python-10"]
    assert cohort["dataset"] == "aider/aider-polyglot"
    assert len(cohort["tasks"]) == 10
    assert cohort["revision"] == "f30b14415dd733c83627204bad0af69a89ceb46f"

    loaded = load_cohort("aider-python-10")
    assert loaded["id"] == "aider-python-10"
    assert loaded["revision"] == cohort["revision"]


def test_select_tasks_deterministic():
    catalog = get_default_catalog()
    desc = catalog.resolve_dataset("aider/aider-polyglot")

    # Filter language
    py_tasks = select_tasks(desc, language="python")
    assert len(py_tasks) == 34
    assert all(t.startswith("polyglot_python_") for t in py_tasks)

    # Sampling with seed is deterministic
    s1 = select_tasks(desc, language="python", count=10, seed=42)
    s2 = select_tasks(desc, language="python", count=10, seed=42)
    assert s1 == s2
    assert len(s1) == 10

    # Harbor select_tasks facade matches
    s3 = harbor_select_tasks(desc, language="python", count=10, seed=42)
    assert s1 == s3


def test_unified_discovery_payload_contract():
    disc = get_unified_discovery(include_readiness=True)
    assert "cohorts" in disc
    assert "datasets" in disc
    assert "benchmarks" in disc
    assert "backends" in disc
    assert "readiness" in disc

    # Check that aider-python-10 is present in cohorts
    assert any(c["id"] == "aider-python-10" and c["tasks"] == 10 for c in disc["cohorts"])

    # Check that Terminal-Bench datasets are in datasets
    dataset_ids = [d["id"] for d in disc["datasets"]]
    assert "terminal-bench/terminal-bench@4.0.0" in dataset_ids
    assert "terminal-bench/terminal-bench-2" in dataset_ids
    assert "ifeval/google-2023" in dataset_ids
    assert "livecodebench/release_v6" in dataset_ids


def test_synthetic_third_party_benchmark_registration():
    """Verify that a synthetic benchmark registers cleanly without changing catalog classes."""
    catalog = BenchmarkCatalog()
    synthetic_bm = BenchmarkDescriptor(
        id="synthetic-bench",
        name="Synthetic Benchmark Suite",
        version="1.0.0",
        description="Testing third-party benchmark extensibility",
        implementation_type="synthetic",
        trusted_adapter_id="synthetic",
        supported_backends=("direct_chat",),
        default_dataset="synthetic/ds-1",
    )
    catalog.register_benchmark(synthetic_bm)

    synthetic_ds = DatasetDescriptor(
        id="synthetic/ds-1",
        benchmark_id="synthetic-bench",
        name="Synthetic Dataset 1",
        version="1.0.0",
        description="Deterministic synthetic dataset",
        supported_languages=("python",),
        all_tasks=("synth-t1", "synth-t2", "synth-t3"),
        default_scoring_protocol="single-attempt-v1",
    )
    catalog.register_dataset(synthetic_ds, aliases=["synth-ds"])

    assert catalog.get_benchmark("synthetic-bench").name == "Synthetic Benchmark Suite"
    assert catalog.resolve_dataset("synth-ds").id == "synthetic/ds-1"
    assert catalog.resolve_dataset("synthetic/ds-1").all_tasks == ("synth-t1", "synth-t2", "synth-t3")
