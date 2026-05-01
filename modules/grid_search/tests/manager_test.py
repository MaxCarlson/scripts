"""Unit tests for gsearch.manager."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from gsearch.manager import (
    AdaptiveGridOptimizer,
    AdaptiveGridStore,
    GridSpec,
    Trial,
    config_id,
    create_next_trial,
    export_trials,
    initialize_experiment,
    record_trial_result,
    stable_json,
    summarize_trials,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_GRID_PAYLOAD: dict[str, Any] = {
    "metric": {"name": "average_mbps", "direction": "maximize"},
    "parameters": {
        "concurrent_fragments": {"values": [1, 4, 8], "priority": 1},
        "buffer_size": {"values": ["1M", "4M"], "priority": 2},
        "resize_buffer": {"values": [True, False], "priority": 3},
    },
}

CONDITIONAL_GRID_PAYLOAD: dict[str, Any] = {
    "metric": {"name": "score", "direction": "maximize"},
    "parameters": {
        "downloader": {"values": ["native", "aria2c"], "priority": 1},
        "concurrent_fragments": {
            "values": [1, 4, 8],
            "active_when": {"downloader": "native"},
            "priority": 1,
        },
        "aria2c_split": {
            "values": [1, 4, 8],
            "active_when": {"downloader": "aria2c"},
            "priority": 1,
        },
    },
    "constraints": [
        {
            "type": "greater_equal",
            "left": "aria2c_split",
            "right": "aria2c_split",  # trivially satisfied — just tests the constraint machinery
            "active_when": {"downloader": "aria2c"},
        }
    ],
}


@pytest.fixture()
def minimal_grid() -> GridSpec:
    return GridSpec(MINIMAL_GRID_PAYLOAD)


@pytest.fixture()
def conditional_grid() -> GridSpec:
    return GridSpec(CONDITIONAL_GRID_PAYLOAD)


@pytest.fixture()
def store(tmp_path: Path) -> AdaptiveGridStore:
    return AdaptiveGridStore(tmp_path / "test.db")


@pytest.fixture()
def initialized_store(store: AdaptiveGridStore) -> AdaptiveGridStore:
    store.upsert_experiment("exp1", MINIMAL_GRID_PAYLOAD)
    return store


@pytest.fixture()
def grid_file(tmp_path: Path) -> Path:
    path = tmp_path / "grid.json"
    path.write_text(json.dumps(MINIMAL_GRID_PAYLOAD), encoding="utf-8")
    return path


def make_trial(
    *,
    config: dict[str, Any] | None = None,
    status: str = "ok",
    metric_value: float | None = 10.0,
    group_key: str | None = None,
    group_value: str | None = None,
    selection_reason: str = "coverage",
    created_at_unix: float = 1.0,
) -> Trial:
    cfg = config or {"concurrent_fragments": 4, "buffer_size": "1M", "resize_buffer": True}
    return Trial(
        trial_id="test-id",
        experiment_name="exp1",
        config_id=config_id(cfg),
        config=cfg,
        status=status,
        metric_name="average_mbps",
        metric_value=metric_value,
        group_key=group_key,
        group_value=group_value,
        selection_reason=selection_reason,
        created_at_unix=created_at_unix,
        completed_at_unix=None,
        metadata={},
    )


# ---------------------------------------------------------------------------
# config_id
# ---------------------------------------------------------------------------


class TestConfigId:
    def test_deterministic(self) -> None:
        cfg = {"a": 1, "b": "x"}
        assert config_id(cfg) == config_id(cfg)

    def test_order_independent(self) -> None:
        a = {"x": 1, "y": 2}
        b = {"y": 2, "x": 1}
        assert config_id(a) == config_id(b)

    def test_different_values_differ(self) -> None:
        assert config_id({"a": 1}) != config_id({"a": 2})

    def test_returns_16_char_hex(self) -> None:
        cid = config_id({"a": 1})
        assert len(cid) == 16
        int(cid, 16)  # must be valid hex


# ---------------------------------------------------------------------------
# GridSpec
# ---------------------------------------------------------------------------


class TestGridSpec:
    def test_rejects_missing_parameters(self) -> None:
        with pytest.raises(RuntimeError, match="parameters"):
            GridSpec({"metric": {}})

    def test_rejects_empty_parameters(self) -> None:
        with pytest.raises(RuntimeError, match="parameters"):
            GridSpec({"parameters": {}})

    def test_rejects_empty_values(self) -> None:
        with pytest.raises(RuntimeError, match="values"):
            GridSpec({"parameters": {"x": {"values": []}}})

    def test_parameter_names_sorted_by_priority(self, minimal_grid: GridSpec) -> None:
        names = minimal_grid.parameter_names()
        priorities = [minimal_grid.parameters[n].get("priority", 99) for n in names]
        assert priorities == sorted(priorities)

    def test_values_for(self, minimal_grid: GridSpec) -> None:
        assert minimal_grid.values_for("concurrent_fragments") == [1, 4, 8]

    def test_is_active_unconditional(self, minimal_grid: GridSpec) -> None:
        assert minimal_grid.is_active("concurrent_fragments", {})

    def test_is_active_conditional_true(self, conditional_grid: GridSpec) -> None:
        assert conditional_grid.is_active("concurrent_fragments", {"downloader": "native"})

    def test_is_active_conditional_false(self, conditional_grid: GridSpec) -> None:
        assert not conditional_grid.is_active("concurrent_fragments", {"downloader": "aria2c"})

    def test_strip_inactive_removes_conditional_params(
        self, conditional_grid: GridSpec
    ) -> None:
        config = conditional_grid.strip_inactive({"downloader": "aria2c"})
        assert "concurrent_fragments" not in config
        assert "aria2c_split" in config

    def test_normalize_config_fills_defaults(self, minimal_grid: GridSpec) -> None:
        config = minimal_grid.normalize_config({})
        assert "concurrent_fragments" in config
        assert "buffer_size" in config

    def test_is_valid_config_accepts_valid(self, minimal_grid: GridSpec) -> None:
        config = {
            "concurrent_fragments": 4,
            "buffer_size": "1M",
            "resize_buffer": True,
        }
        assert minimal_grid.is_valid_config(config)

    def test_is_valid_config_rejects_bad_value(self, minimal_grid: GridSpec) -> None:
        config = {
            "concurrent_fragments": 99,  # not in values
            "buffer_size": "1M",
            "resize_buffer": True,
        }
        assert not minimal_grid.is_valid_config(config)

    def test_constraint_greater_equal_passes(self) -> None:
        grid = GridSpec({
            "parameters": {
                "x": {"values": [1, 2, 4]},
                "y": {"values": [1, 2, 4]},
            },
            "constraints": [{"type": "greater_equal", "left": "x", "right": "y"}],
        })
        assert grid.is_valid_config({"x": 4, "y": 2})

    def test_constraint_greater_equal_fails(self) -> None:
        grid = GridSpec({
            "parameters": {
                "x": {"values": [1, 2, 4]},
                "y": {"values": [1, 2, 4]},
            },
            "constraints": [{"type": "greater_equal", "left": "x", "right": "y"}],
        })
        assert not grid.is_valid_config({"x": 1, "y": 4})

    def test_constraint_less_equal(self) -> None:
        grid = GridSpec({
            "parameters": {
                "a": {"values": [1, 2, 4]},
                "b": {"values": [1, 2, 4]},
            },
            "constraints": [{"type": "less_equal", "left": "a", "right": "b"}],
        })
        assert grid.is_valid_config({"a": 1, "b": 4})
        assert not grid.is_valid_config({"a": 4, "b": 1})

    def test_constraint_not_equal(self) -> None:
        grid = GridSpec({
            "parameters": {
                "a": {"values": [1, 2]},
                "b": {"values": [1, 2]},
            },
            "constraints": [{"type": "not_equal", "left": "a", "right": "b"}],
        })
        assert not grid.is_valid_config({"a": 1, "b": 1})
        assert grid.is_valid_config({"a": 1, "b": 2})

    def test_inactive_constraint_skipped(self) -> None:
        grid = GridSpec({
            "parameters": {
                "mode": {"values": ["fast", "slow"]},
                "x": {"values": [1, 2]},
                "y": {"values": [1, 4]},
            },
            "constraints": [
                {
                    "type": "greater_equal",
                    "left": "x",
                    "right": "y",
                    "active_when": {"mode": "fast"},
                }
            ],
        })
        # constraint applies only for mode=fast
        assert not grid.is_valid_config({"mode": "fast", "x": 1, "y": 4})  # violates
        assert grid.is_valid_config({"mode": "slow", "x": 1, "y": 4})  # inactive

    def test_metric_defaults(self) -> None:
        grid = GridSpec({"parameters": {"x": {"values": [1]}}})
        assert grid.metric_name == "score"
        assert grid.metric_direction == "maximize"

    def test_metric_from_payload(self) -> None:
        grid = GridSpec({
            "metric": {"name": "total_seconds", "direction": "minimize"},
            "parameters": {"x": {"values": [1]}},
        })
        assert grid.metric_name == "total_seconds"
        assert grid.metric_direction == "minimize"


# ---------------------------------------------------------------------------
# AdaptiveGridStore
# ---------------------------------------------------------------------------


class TestAdaptiveGridStore:
    def test_initialize_schema_idempotent(self, store: AdaptiveGridStore) -> None:
        store.initialize_schema()
        store.initialize_schema()  # should not raise

    def test_upsert_and_read_experiment(self, store: AdaptiveGridStore) -> None:
        store.upsert_experiment("exp1", MINIMAL_GRID_PAYLOAD)
        payload = store.read_experiment_grid("exp1")
        assert payload["metric"]["name"] == "average_mbps"

    def test_upsert_updates_existing(self, store: AdaptiveGridStore) -> None:
        store.upsert_experiment("exp1", MINIMAL_GRID_PAYLOAD)
        updated = dict(MINIMAL_GRID_PAYLOAD)
        updated["metric"] = {"name": "total_seconds", "direction": "minimize"}
        store.upsert_experiment("exp1", updated)
        payload = store.read_experiment_grid("exp1")
        assert payload["metric"]["name"] == "total_seconds"

    def test_read_missing_experiment_raises(self, store: AdaptiveGridStore) -> None:
        store.initialize_schema()
        with pytest.raises(RuntimeError, match="does not exist"):
            store.read_experiment_grid("nonexistent")

    def test_load_trials_empty(self, initialized_store: AdaptiveGridStore) -> None:
        trials = initialized_store.load_trials("exp1")
        assert trials == []

    def test_create_planned_trial(self, initialized_store: AdaptiveGridStore) -> None:
        cfg = {"concurrent_fragments": 4, "buffer_size": "1M", "resize_buffer": True}
        trial = initialized_store.create_planned_trial(
            experiment_name="exp1",
            metric_name="average_mbps",
            config=cfg,
            group_key="domain",
            group_value="example.com",
            selection_reason="coverage",
            metadata={"extra": "data"},
        )
        assert trial.status == "planned"
        assert trial.metric_value is None
        assert trial.group_value == "example.com"

        trials = initialized_store.load_trials("exp1")
        assert len(trials) == 1
        assert trials[0].trial_id == trial.trial_id

    def test_record_result_ok(self, initialized_store: AdaptiveGridStore) -> None:
        cfg = {"concurrent_fragments": 4, "buffer_size": "1M", "resize_buffer": True}
        trial = initialized_store.create_planned_trial(
            experiment_name="exp1",
            metric_name="average_mbps",
            config=cfg,
            group_key=None,
            group_value=None,
            selection_reason="coverage",
            metadata={},
        )
        initialized_store.record_result(
            trial_id=trial.trial_id,
            status="ok",
            metric_value=42.5,
            metadata_update={"url": "https://example.com"},
        )
        trials = initialized_store.load_trials("exp1")
        assert trials[0].status == "ok"
        assert trials[0].metric_value == pytest.approx(42.5)
        assert trials[0].metadata.get("url") == "https://example.com"

    def test_record_result_missing_trial_raises(
        self, initialized_store: AdaptiveGridStore
    ) -> None:
        with pytest.raises(RuntimeError, match="does not exist"):
            initialized_store.record_result(
                trial_id="00000000-0000-0000-0000-000000000000",
                status="ok",
                metric_value=1.0,
                metadata_update={},
            )

    def test_expire_stale_planned_trials(self, initialized_store: AdaptiveGridStore) -> None:
        import time as _time

        cfg = {"concurrent_fragments": 1, "buffer_size": "1M", "resize_buffer": True}
        initialized_store.create_planned_trial(
            experiment_name="exp1",
            metric_name="average_mbps",
            config=cfg,
            group_key=None,
            group_value=None,
            selection_reason="coverage",
            metadata={},
        )
        # TTL of 0 → everything is stale
        count = initialized_store.expire_stale_planned_trials("exp1", ttl_seconds=0)
        assert count == 1

        trials = initialized_store.load_trials("exp1")
        assert trials[0].status == "expired"

    def test_group_value_normalized_to_lowercase(
        self, initialized_store: AdaptiveGridStore
    ) -> None:
        cfg = {"concurrent_fragments": 4, "buffer_size": "1M", "resize_buffer": True}
        trial = initialized_store.create_planned_trial(
            experiment_name="exp1",
            metric_name="average_mbps",
            config=cfg,
            group_key="domain",
            group_value="Example.COM",
            selection_reason="coverage",
            metadata={},
        )
        assert trial.group_value == "example.com"


# ---------------------------------------------------------------------------
# AdaptiveGridOptimizer
# ---------------------------------------------------------------------------


class TestAdaptiveGridOptimizer:
    def test_random_config_is_valid(self, minimal_grid: GridSpec) -> None:
        opt = AdaptiveGridOptimizer(minimal_grid, [])
        for _ in range(20):
            cfg = opt.random_config()
            assert minimal_grid.is_valid_config(cfg)

    def test_coverage_config_returns_valid(self, minimal_grid: GridSpec) -> None:
        opt = AdaptiveGridOptimizer(minimal_grid, [], seed=42)
        cfg, reason = opt.coverage_config([])
        assert minimal_grid.is_valid_config(cfg)
        assert reason == "coverage"

    def test_ucb_config_returns_valid(self, minimal_grid: GridSpec) -> None:
        opt = AdaptiveGridOptimizer(minimal_grid, [], seed=42)
        cfg, reason = opt.ucb_config([])
        assert minimal_grid.is_valid_config(cfg)
        assert reason == "ucb"

    def test_neighbor_config_falls_back_to_coverage_without_best(
        self, minimal_grid: GridSpec
    ) -> None:
        opt = AdaptiveGridOptimizer(minimal_grid, [], seed=0)
        cfg, reason = opt.neighbor_config([])
        assert minimal_grid.is_valid_config(cfg)

    def test_neighbor_config_explores_around_best(self, minimal_grid: GridSpec) -> None:
        best_cfg = {"concurrent_fragments": 4, "buffer_size": "1M", "resize_buffer": True}
        trials = [make_trial(config=best_cfg, metric_value=100.0)]
        opt = AdaptiveGridOptimizer(minimal_grid, trials, seed=0)
        cfg, reason = opt.neighbor_config(trials)
        assert minimal_grid.is_valid_config(cfg)

    def test_choose_random_mode(self, minimal_grid: GridSpec) -> None:
        opt = AdaptiveGridOptimizer(minimal_grid, [], seed=7)
        cfg, meta = opt.choose(
            group_key=None, group_value=None, group_mode="global", selection_mode="random"
        )
        assert minimal_grid.is_valid_config(cfg)
        assert meta["selection_reason"] == "random"

    def test_choose_adaptive_warmup(self, minimal_grid: GridSpec) -> None:
        opt = AdaptiveGridOptimizer(minimal_grid, [], seed=0)
        cfg, meta = opt.choose(
            group_key=None, group_value=None, group_mode="global", selection_mode="adaptive"
        )
        assert minimal_grid.is_valid_config(cfg)
        assert "warmup" in str(meta["selection_reason"])

    def test_choose_adaptive_post_warmup(self, minimal_grid: GridSpec) -> None:
        # Populate with enough trials to leave warmup
        warmup = int(minimal_grid.policy.get("warmup_trials", 40))
        trials = [
            make_trial(
                config=minimal_grid.strip_inactive(minimal_grid.normalize_config({})),
                metric_value=float(i),
                created_at_unix=float(i),
            )
            for i in range(warmup + 5)
        ]
        opt = AdaptiveGridOptimizer(minimal_grid, trials, seed=0)
        cfg, meta = opt.choose(
            group_key=None, group_value=None, group_mode="global", selection_mode="adaptive"
        )
        assert minimal_grid.is_valid_config(cfg)

    def test_scoped_trials_global(self, minimal_grid: GridSpec) -> None:
        t1 = make_trial(group_key="domain", group_value="a.com")
        t2 = make_trial(group_key="domain", group_value="b.com")
        opt = AdaptiveGridOptimizer(minimal_grid, [t1, t2])
        result, scope = opt.scoped_trials("domain", "a.com", "global")
        assert len(result) == 2
        assert scope == "global"

    def test_scoped_trials_per_group(self, minimal_grid: GridSpec) -> None:
        t1 = make_trial(group_key="domain", group_value="a.com")
        t2 = make_trial(group_key="domain", group_value="b.com")
        opt = AdaptiveGridOptimizer(minimal_grid, [t1, t2])
        result, scope = opt.scoped_trials("domain", "a.com", "per-group")
        assert all(t.group_value == "a.com" for t in result)
        assert scope == "group"

    def test_scoped_trials_hybrid_falls_back_when_sparse(
        self, minimal_grid: GridSpec
    ) -> None:
        t1 = make_trial(group_key="domain", group_value="a.com")
        opt = AdaptiveGridOptimizer(minimal_grid, [t1])
        result, scope = opt.scoped_trials("domain", "a.com", "hybrid")
        # only 1 successful trial → fewer than min_group_trials → fallback to global
        assert scope == "hybrid-global-fallback"
        assert len(result) == len(opt.trials)

    def test_best_trial_returns_max_for_maximize(self, minimal_grid: GridSpec) -> None:
        t_low = make_trial(metric_value=10.0)
        t_high = make_trial(metric_value=99.0)
        opt = AdaptiveGridOptimizer(minimal_grid, [t_low, t_high])
        best = opt.best_trial([t_low, t_high])
        assert best is not None
        assert best.metric_value == pytest.approx(99.0)

    def test_best_trial_returns_min_for_minimize(self) -> None:
        grid = GridSpec({
            "metric": {"name": "latency", "direction": "minimize"},
            "parameters": {"x": {"values": [1]}},
        })
        t_low = make_trial(metric_value=10.0)
        t_high = make_trial(metric_value=99.0)
        opt = AdaptiveGridOptimizer(grid, [t_low, t_high])
        best = opt.best_trial([t_low, t_high])
        assert best is not None
        assert best.metric_value == pytest.approx(10.0)

    def test_best_trial_none_when_no_successful(self, minimal_grid: GridSpec) -> None:
        t = make_trial(status="failed", metric_value=None)
        opt = AdaptiveGridOptimizer(minimal_grid, [t])
        assert opt.best_trial([t]) is None

    def test_adjacent_values_middle(self, minimal_grid: GridSpec) -> None:
        opt = AdaptiveGridOptimizer(minimal_grid, [])
        adj = opt.adjacent_values("concurrent_fragments", 4)
        assert 1 in adj
        assert 8 in adj

    def test_adjacent_values_edge(self, minimal_grid: GridSpec) -> None:
        opt = AdaptiveGridOptimizer(minimal_grid, [])
        adj = opt.adjacent_values("concurrent_fragments", 1)
        assert adj == [4]

    def test_conditional_grid_configs_respect_active_when(
        self, conditional_grid: GridSpec
    ) -> None:
        opt = AdaptiveGridOptimizer(conditional_grid, [], seed=0)
        for _ in range(30):
            cfg = opt.random_config()
            assert conditional_grid.is_valid_config(cfg)
            if cfg.get("downloader") == "native":
                assert "concurrent_fragments" in cfg
                assert "aria2c_split" not in cfg
            else:
                assert "aria2c_split" in cfg
                assert "concurrent_fragments" not in cfg


# ---------------------------------------------------------------------------
# Public API helpers
# ---------------------------------------------------------------------------


class TestPublicAPI:
    def test_initialize_experiment(
        self, tmp_path: Path, grid_file: Path
    ) -> None:
        db = tmp_path / "db.sqlite"
        initialize_experiment(db, grid_file, "exp1")
        store = AdaptiveGridStore(db)
        payload = store.read_experiment_grid("exp1")
        assert "parameters" in payload

    def test_create_next_trial_round_trip(
        self, tmp_path: Path, grid_file: Path
    ) -> None:
        db = tmp_path / "db.sqlite"
        initialize_experiment(db, grid_file, "exp1")
        payload = create_next_trial(
            database=db,
            experiment="exp1",
            output=None,
            group_key=None,
            group_value=None,
            group_mode="global",
            selection_mode="random",
            metadata={},
            seed=0,
        )
        assert "trial_id" in payload
        assert "config" in payload
        assert payload["status"] == "planned"

    def test_create_next_trial_writes_output_file(
        self, tmp_path: Path, grid_file: Path
    ) -> None:
        db = tmp_path / "db.sqlite"
        out = tmp_path / "trial.json"
        initialize_experiment(db, grid_file, "exp1")
        create_next_trial(
            database=db,
            experiment="exp1",
            output=out,
            group_key=None,
            group_value=None,
            group_mode="global",
            selection_mode="random",
            metadata={},
            seed=0,
        )
        assert out.exists()
        assert "trial_id" in json.loads(out.read_text())

    def test_record_ok_requires_metric(
        self, tmp_path: Path, grid_file: Path
    ) -> None:
        db = tmp_path / "db.sqlite"
        initialize_experiment(db, grid_file, "exp1")
        payload = create_next_trial(
            database=db,
            experiment="exp1",
            output=None,
            group_key=None,
            group_value=None,
            group_mode="global",
            selection_mode="random",
            metadata={},
            seed=0,
        )
        with pytest.raises(RuntimeError, match="metric_value"):
            record_trial_result(
                database=db,
                trial_id=payload["trial_id"],
                status="ok",
                metric_value=None,
                metadata={},
            )

    def test_record_failed_no_metric_ok(
        self, tmp_path: Path, grid_file: Path
    ) -> None:
        db = tmp_path / "db.sqlite"
        initialize_experiment(db, grid_file, "exp1")
        payload = create_next_trial(
            database=db,
            experiment="exp1",
            output=None,
            group_key=None,
            group_value=None,
            group_mode="global",
            selection_mode="random",
            metadata={},
            seed=0,
        )
        record_trial_result(
            database=db,
            trial_id=payload["trial_id"],
            status="failed",
            metric_value=None,
            metadata={"reason": "timeout"},
        )
        store = AdaptiveGridStore(db)
        trials = store.load_trials("exp1")
        assert trials[0].status == "failed"
        assert trials[0].metadata.get("reason") == "timeout"

    def test_export_trials_jsonl(
        self, tmp_path: Path, grid_file: Path
    ) -> None:
        db = tmp_path / "db.sqlite"
        initialize_experiment(db, grid_file, "exp1")
        payload = create_next_trial(
            database=db,
            experiment="exp1",
            output=None,
            group_key=None,
            group_value=None,
            group_mode="global",
            selection_mode="random",
            metadata={},
            seed=0,
        )
        out = tmp_path / "out.jsonl"
        count = export_trials(db, "exp1", out)
        assert count == 1
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert json.loads(lines[0])["trial_id"] == payload["trial_id"]

    def test_summarize_trials_empty(
        self, tmp_path: Path, grid_file: Path
    ) -> None:
        db = tmp_path / "db.sqlite"
        initialize_experiment(db, grid_file, "exp1")
        summary = summarize_trials(db, "exp1", limit=10)
        assert summary["trial_count"] == 0
        assert summary["successful_trial_count"] == 0
        assert summary["top"] == []

    def test_summarize_trials_with_results(
        self, tmp_path: Path, grid_file: Path
    ) -> None:
        db = tmp_path / "db.sqlite"
        initialize_experiment(db, grid_file, "exp1")
        payload = create_next_trial(
            database=db,
            experiment="exp1",
            output=None,
            group_key=None,
            group_value=None,
            group_mode="global",
            selection_mode="random",
            metadata={},
            seed=0,
        )
        record_trial_result(
            database=db,
            trial_id=payload["trial_id"],
            status="ok",
            metric_value=77.0,
            metadata={},
        )
        summary = summarize_trials(db, "exp1", limit=10)
        assert summary["successful_trial_count"] == 1
        assert len(summary["top"]) == 1
        assert summary["top"][0]["mean"] == pytest.approx(77.0)
