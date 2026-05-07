"""Unit tests for gsearch.reporting."""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from gsearch.manager import (
    create_next_trial,
    initialize_experiment,
    record_trial_result,
)
from gsearch.reporting import (
    Experiment,
    Trial,
    build_markdown_report,
    build_summary,
    flatten_trial_for_csv,
    generate_report,
    load_experiment,
    load_trials,
    metric_direction_from_grid,
    metric_name_from_grid,
    plot_counter,
    plot_cumulative_best,
    plot_metric_over_time,
    plot_parameter_effect,
    stable_json,
    summarize_parameter_effects,
    summarize_top_configs,
    write_trials_csv,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_GRID: dict[str, Any] = {
    "metric": {"name": "average_mbps", "direction": "maximize"},
    "parameters": {
        "concurrent_fragments": {"values": [1, 4, 8], "priority": 1},
        "buffer_size": {"values": ["1M", "4M"], "priority": 2},
    },
}


def _make_trial(
    *,
    trial_id: str = "tid-1",
    experiment_name: str = "exp1",
    config_id: str = "abcd1234abcd1234",
    config: dict[str, Any] | None = None,
    status: str = "ok",
    metric_value: float | None = 10.0,
    group_key: str | None = None,
    group_value: str | None = None,
    selection_reason: str | None = "coverage",
    created_at_unix: float = 1.0,
    metadata: dict[str, Any] | None = None,
) -> Trial:
    return Trial(
        trial_id=trial_id,
        experiment_name=experiment_name,
        config_id=config_id,
        config=config or {"concurrent_fragments": 4, "buffer_size": "1M"},
        status=status,
        metric_name="average_mbps",
        metric_value=metric_value,
        group_key=group_key,
        group_value=group_value,
        selection_reason=selection_reason,
        created_at_unix=created_at_unix,
        completed_at_unix=None,
        metadata=metadata or {},
    )


@pytest.fixture()
def grid_file(tmp_path: Path) -> Path:
    path = tmp_path / "grid.json"
    path.write_text(json.dumps(MINIMAL_GRID), encoding="utf-8")
    return path


@pytest.fixture()
def seeded_db(tmp_path: Path, grid_file: Path) -> Path:
    """DB with one successful trial and one failed trial."""
    db = tmp_path / "db.sqlite"
    initialize_experiment(db, grid_file, "exp1")

    p1 = create_next_trial(
        database=db, experiment="exp1", output=None,
        group_key=None, group_value=None, group_mode="global",
        selection_mode="random", metadata={}, seed=0,
    )
    record_trial_result(db, p1["trial_id"], "ok", 55.0, {})

    p2 = create_next_trial(
        database=db, experiment="exp1", output=None,
        group_key=None, group_value=None, group_mode="global",
        selection_mode="random", metadata={}, seed=1,
    )
    record_trial_result(db, p2["trial_id"], "failed", None, {})

    return db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestStableJson:
    def test_deterministic(self) -> None:
        assert stable_json({"b": 2, "a": 1}) == stable_json({"a": 1, "b": 2})

    def test_no_extra_whitespace(self) -> None:
        result = stable_json({"a": 1})
        assert "  " not in result


class TestMetricHelpers:
    def test_direction_from_grid_maximize(self) -> None:
        assert metric_direction_from_grid(MINIMAL_GRID) == "maximize"

    def test_direction_from_grid_minimize(self) -> None:
        g = {"metric": {"direction": "minimize"}}
        assert metric_direction_from_grid(g) == "minimize"

    def test_direction_defaults_to_maximize(self) -> None:
        assert metric_direction_from_grid({}) == "maximize"

    def test_name_from_grid(self) -> None:
        assert metric_name_from_grid(MINIMAL_GRID) == "average_mbps"

    def test_name_defaults_to_score(self) -> None:
        assert metric_name_from_grid({}) == "score"


# ---------------------------------------------------------------------------
# flatten_trial_for_csv
# ---------------------------------------------------------------------------


class TestFlattenTrialForCsv:
    def test_contains_required_keys(self) -> None:
        trial = _make_trial()
        row = flatten_trial_for_csv(trial)
        assert "trial_id" in row
        assert "status" in row
        assert "metric_value" in row
        assert "created_at_unix" in row

    def test_config_keys_prefixed(self) -> None:
        trial = _make_trial(config={"concurrent_fragments": 4, "buffer_size": "1M"})
        row = flatten_trial_for_csv(trial)
        assert "config.concurrent_fragments" in row
        assert row["config.concurrent_fragments"] == 4

    def test_metadata_scalar_keys_prefixed(self) -> None:
        trial = _make_trial(metadata={"url": "https://example.com", "retry": 2})
        row = flatten_trial_for_csv(trial)
        assert row["metadata.url"] == "https://example.com"
        assert row["metadata.retry"] == 2

    def test_metadata_nested_json_stringified(self) -> None:
        trial = _make_trial(metadata={"tags": ["a", "b"]})
        row = flatten_trial_for_csv(trial)
        assert isinstance(row["metadata.tags"], str)
        assert json.loads(row["metadata.tags"]) == ["a", "b"]


# ---------------------------------------------------------------------------
# write_trials_csv
# ---------------------------------------------------------------------------


class TestWriteTrialsCsv:
    def test_empty_writes_empty_file(self, tmp_path: Path) -> None:
        path = tmp_path / "out.csv"
        write_trials_csv(path, [])
        assert path.exists()
        assert path.read_text() == ""

    def test_single_trial_csv(self, tmp_path: Path) -> None:
        path = tmp_path / "out.csv"
        trial = _make_trial()
        write_trials_csv(path, [trial])
        rows = list(csv.DictReader(path.open(encoding="utf-8")))
        assert len(rows) == 1
        assert rows[0]["trial_id"] == "tid-1"

    def test_fieldnames_sorted(self, tmp_path: Path) -> None:
        path = tmp_path / "out.csv"
        t1 = _make_trial(config={"z": 1, "a": 2})
        write_trials_csv(path, [t1])
        reader = csv.DictReader(path.open(encoding="utf-8"))
        names = reader.fieldnames or []
        assert names == sorted(names)

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        path = tmp_path / "deep" / "dir" / "out.csv"
        write_trials_csv(path, [])
        assert path.exists()


# ---------------------------------------------------------------------------
# summarize_top_configs
# ---------------------------------------------------------------------------


class TestSummarizeTopConfigs:
    def test_maximize_orders_descending(self) -> None:
        t1 = _make_trial(config_id="aaa", metric_value=10.0)
        t2 = _make_trial(config_id="bbb", metric_value=99.0)
        top = summarize_top_configs([t1, t2], "maximize", 10)
        assert top[0]["config_id"] == "bbb"
        assert top[1]["config_id"] == "aaa"

    def test_minimize_orders_ascending(self) -> None:
        t1 = _make_trial(config_id="aaa", metric_value=10.0)
        t2 = _make_trial(config_id="bbb", metric_value=99.0)
        top = summarize_top_configs([t1, t2], "minimize", 10)
        assert top[0]["config_id"] == "aaa"

    def test_limit_respected(self) -> None:
        trials = [_make_trial(config_id=f"id{i}", metric_value=float(i)) for i in range(10)]
        top = summarize_top_configs(trials, "maximize", 3)
        assert len(top) == 3

    def test_excludes_failed_trials(self) -> None:
        t = _make_trial(status="failed", metric_value=None)
        top = summarize_top_configs([t], "maximize", 10)
        assert top == []

    def test_same_config_id_aggregated(self) -> None:
        t1 = _make_trial(config_id="same", metric_value=10.0, trial_id="t1")
        t2 = _make_trial(config_id="same", metric_value=20.0, trial_id="t2")
        top = summarize_top_configs([t1, t2], "maximize", 10)
        assert len(top) == 1
        assert top[0]["count"] == 2
        assert top[0]["mean"] == pytest.approx(15.0)

    def test_contains_expected_keys(self) -> None:
        t = _make_trial()
        top = summarize_top_configs([t], "maximize", 10)
        assert "config_id" in top[0]
        assert "mean" in top[0]
        assert "median" in top[0]
        assert "best" in top[0]
        assert "config" in top[0]


# ---------------------------------------------------------------------------
# summarize_parameter_effects
# ---------------------------------------------------------------------------


class TestSummarizeParameterEffects:
    def test_single_param(self) -> None:
        t = _make_trial(config={"x": 1}, metric_value=10.0)
        effects = summarize_parameter_effects([t])
        assert "x" in effects
        assert effects["x"][0]["count"] == 1

    def test_excludes_failed(self) -> None:
        t = _make_trial(config={"x": 1}, status="failed", metric_value=None)
        effects = summarize_parameter_effects([t])
        assert effects == {}

    def test_values_ordered_by_mean_descending(self) -> None:
        t1 = _make_trial(config={"x": 1}, metric_value=10.0, trial_id="t1")
        t2 = _make_trial(config={"x": 5}, metric_value=90.0, trial_id="t2")
        effects = summarize_parameter_effects([t1, t2])
        assert effects["x"][0]["mean"] == pytest.approx(90.0)


# ---------------------------------------------------------------------------
# build_summary
# ---------------------------------------------------------------------------


class TestBuildSummary:
    def test_keys_present(self) -> None:
        exp = Experiment("exp1", MINIMAL_GRID)
        trials = [_make_trial()]
        summary = build_summary(exp, trials, top_limit=10)
        required = [
            "experiment_name",
            "metric_name",
            "metric_direction",
            "trial_count",
            "successful_trial_count",
            "status_counts",
            "selection_reason_counts",
            "metric_summary",
            "top_configs",
            "parameter_effects",
        ]
        for key in required:
            assert key in summary, f"Missing key: {key}"

    def test_empty_trials(self) -> None:
        exp = Experiment("exp1", MINIMAL_GRID)
        summary = build_summary(exp, [], top_limit=10)
        assert summary["trial_count"] == 0
        assert summary["successful_trial_count"] == 0
        assert summary["metric_summary"]["mean"] is None
        assert summary["top_configs"] == []

    def test_status_counts(self) -> None:
        exp = Experiment("exp1", MINIMAL_GRID)
        trials = [
            _make_trial(trial_id="t1", status="ok"),
            _make_trial(trial_id="t2", status="failed", metric_value=None),
        ]
        summary = build_summary(exp, trials, top_limit=10)
        assert summary["status_counts"]["ok"] == 1
        assert summary["status_counts"]["failed"] == 1

    def test_metric_summary_values(self) -> None:
        exp = Experiment("exp1", MINIMAL_GRID)
        trials = [
            _make_trial(trial_id="t1", metric_value=10.0),
            _make_trial(trial_id="t2", metric_value=20.0),
        ]
        summary = build_summary(exp, trials, top_limit=10)
        ms = summary["metric_summary"]
        assert ms["min"] == pytest.approx(10.0)
        assert ms["max"] == pytest.approx(20.0)
        assert ms["mean"] == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# build_markdown_report
# ---------------------------------------------------------------------------


class TestBuildMarkdownReport:
    def test_contains_experiment_name(self) -> None:
        summary = {
            "experiment_name": "my_exp",
            "metric_name": "score",
            "metric_direction": "maximize",
            "trial_count": 5,
            "successful_trial_count": 4,
            "top_configs": [],
        }
        md = build_markdown_report(summary, ["file1.csv"])
        assert "my_exp" in md

    def test_top_configs_rendered(self) -> None:
        summary = {
            "experiment_name": "exp1",
            "metric_name": "score",
            "metric_direction": "maximize",
            "trial_count": 1,
            "successful_trial_count": 1,
            "top_configs": [
                {
                    "config_id": "abc123",
                    "count": 1,
                    "mean": 55.0,
                    "median": 55.0,
                    "config": {"x": 1},
                }
            ],
        }
        md = build_markdown_report(summary, [])
        assert "abc123" in md

    def test_generated_files_listed(self) -> None:
        summary = {
            "experiment_name": "exp1",
            "metric_name": "score",
            "metric_direction": "maximize",
            "trial_count": 0,
            "successful_trial_count": 0,
            "top_configs": [],
        }
        md = build_markdown_report(summary, ["trials.csv", "summary.json"])
        assert "trials.csv" in md
        assert "summary.json" in md


# ---------------------------------------------------------------------------
# Plot functions (smoke tests — just verify no crash and file written)
# ---------------------------------------------------------------------------


class TestPlotFunctions:
    def test_plot_metric_over_time_empty(self, tmp_path: Path) -> None:
        # Should return without writing anything
        path = tmp_path / "plot.png"
        plot_metric_over_time(path, [], "score")
        assert not path.exists()

    def test_plot_metric_over_time_with_data(self, tmp_path: Path) -> None:
        path = tmp_path / "plot.png"
        trials = [_make_trial(metric_value=float(i), trial_id=f"t{i}") for i in range(5)]
        plot_metric_over_time(path, trials, "score")
        assert path.exists()
        assert path.stat().st_size > 0

    def test_plot_cumulative_best_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "plot.png"
        plot_cumulative_best(path, [], "score", "maximize")
        assert not path.exists()

    def test_plot_cumulative_best_maximize(self, tmp_path: Path) -> None:
        path = tmp_path / "plot.png"
        trials = [_make_trial(metric_value=float(i), trial_id=f"t{i}") for i in range(3)]
        plot_cumulative_best(path, trials, "score", "maximize")
        assert path.exists()

    def test_plot_cumulative_best_minimize(self, tmp_path: Path) -> None:
        path = tmp_path / "plot.png"
        trials = [_make_trial(metric_value=float(i), trial_id=f"t{i}") for i in range(3)]
        plot_cumulative_best(path, trials, "latency", "minimize")
        assert path.exists()

    def test_plot_counter_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "plot.png"
        plot_counter(path, "empty", Counter())
        assert not path.exists()

    def test_plot_counter_with_data(self, tmp_path: Path) -> None:
        path = tmp_path / "plot.png"
        plot_counter(path, "statuses", Counter({"ok": 5, "failed": 2}))
        assert path.exists()

    def test_plot_parameter_effect_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "plot.png"
        plot_parameter_effect(path, "x", [], "score")
        assert not path.exists()

    def test_plot_parameter_effect_with_data(self, tmp_path: Path) -> None:
        path = tmp_path / "plot.png"
        rows = [
            {"value": "1", "mean": 10.0},
            {"value": "4", "mean": 20.0},
        ]
        plot_parameter_effect(path, "x", rows, "score")
        assert path.exists()


# ---------------------------------------------------------------------------
# load_experiment / load_trials via real SQLite
# ---------------------------------------------------------------------------


class TestLoadFromDb:
    def test_load_experiment(self, seeded_db: Path) -> None:
        exp = load_experiment(seeded_db, "exp1")
        assert exp.experiment_name == "exp1"
        assert "parameters" in exp.grid

    def test_load_experiment_missing_raises(self, seeded_db: Path) -> None:
        with pytest.raises(RuntimeError, match="Experiment not found"):
            load_experiment(seeded_db, "nonexistent")

    def test_load_trials_count(self, seeded_db: Path) -> None:
        trials = load_trials(seeded_db, "exp1")
        assert len(trials) == 2

    def test_load_trials_statuses(self, seeded_db: Path) -> None:
        trials = load_trials(seeded_db, "exp1")
        statuses = {t.status for t in trials}
        assert "ok" in statuses
        assert "failed" in statuses

    def test_load_trials_metric_value(self, seeded_db: Path) -> None:
        trials = load_trials(seeded_db, "exp1")
        ok = next(t for t in trials if t.status == "ok")
        assert ok.metric_value == pytest.approx(55.0)


# ---------------------------------------------------------------------------
# generate_report integration test
# ---------------------------------------------------------------------------


class TestGenerateReport:
    def test_report_writes_required_files(self, seeded_db: Path, tmp_path: Path) -> None:
        out_dir = tmp_path / "report"
        manifest = generate_report(seeded_db, "exp1", out_dir)

        assert (out_dir / "trials.csv").exists()
        assert (out_dir / "summary.json").exists()
        assert (out_dir / "summary.md").exists()
        assert (out_dir / "report_manifest.json").exists()

    def test_manifest_keys(self, seeded_db: Path, tmp_path: Path) -> None:
        out_dir = tmp_path / "report"
        manifest = generate_report(seeded_db, "exp1", out_dir)
        assert "experiment_name" in manifest
        assert "generated_files" in manifest
        assert "output_dir" in manifest

    def test_trials_csv_has_data(self, seeded_db: Path, tmp_path: Path) -> None:
        out_dir = tmp_path / "report"
        generate_report(seeded_db, "exp1", out_dir)
        rows = list(csv.DictReader((out_dir / "trials.csv").open(encoding="utf-8")))
        assert len(rows) == 2

    def test_summary_json_structure(self, seeded_db: Path, tmp_path: Path) -> None:
        out_dir = tmp_path / "report"
        generate_report(seeded_db, "exp1", out_dir)
        summary = json.loads((out_dir / "summary.json").read_text())
        assert summary["experiment_name"] == "exp1"
        assert summary["successful_trial_count"] == 1

    def test_plots_written(self, seeded_db: Path, tmp_path: Path) -> None:
        out_dir = tmp_path / "report"
        generate_report(seeded_db, "exp1", out_dir)
        plots = list((out_dir / "plots").glob("*.png"))
        assert len(plots) > 0

    def test_empty_db_report_no_crash(self, tmp_path: Path, grid_file: Path) -> None:
        db = tmp_path / "empty.db"
        initialize_experiment(db, grid_file, "exp1")
        out_dir = tmp_path / "report"
        manifest = generate_report(db, "exp1", out_dir)
        assert (out_dir / "summary.json").exists()
        assert (out_dir / "trials.csv").exists()
