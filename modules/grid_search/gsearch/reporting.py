from __future__ import annotations

import csv
import dataclasses
import json
import math
import sqlite3
import statistics
from collections import Counter
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any, Literal

import matplotlib.pyplot as plt

MetricDirection = Literal["maximize", "minimize"]


@dataclasses.dataclass(frozen=True)
class Experiment:
    experiment_name: str
    grid: dict[str, Any]


@dataclasses.dataclass(frozen=True)
class Trial:
    trial_id: str
    experiment_name: str
    config_id: str
    config: dict[str, Any]
    status: str
    metric_name: str
    metric_value: float | None
    group_key: str | None
    group_value: str | None
    selection_reason: str | None
    created_at_unix: float
    completed_at_unix: float | None
    metadata: dict[str, Any]


def read_json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except Exception:
        return {}

    return parsed if isinstance(parsed, dict) else {}


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def display_value(value: Any) -> str:
    if isinstance(value, str):
        return value

    return stable_json(value)


def metric_direction_from_grid(grid: dict[str, Any]) -> MetricDirection:
    metric = grid.get("metric")
    if isinstance(metric, dict) and metric.get("direction") in {"maximize", "minimize"}:
        return metric["direction"]

    return "maximize"


def metric_name_from_grid(grid: dict[str, Any]) -> str:
    metric = grid.get("metric")
    if isinstance(metric, dict) and isinstance(metric.get("name"), str):
        return metric["name"]

    return "score"


def grid_parameter_values(grid: dict[str, Any]) -> dict[str, list[Any]]:
    parameters = grid.get("parameters")
    if not isinstance(parameters, dict):
        return {}

    output: dict[str, list[Any]] = {}
    for name, spec in parameters.items():
        if not isinstance(name, str) or not isinstance(spec, dict):
            continue

        values = spec.get("values")
        if isinstance(values, list):
            output[name] = values

    return output


def objective_value(metric_value: float, direction: MetricDirection) -> float:
    if direction == "maximize":
        return metric_value

    return -metric_value


def raw_metric_value(objective: float, direction: MetricDirection) -> float:
    if direction == "maximize":
        return objective

    return -objective


def safe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None

    if isinstance(value, int | float):
        return float(value)

    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None

    return None


def pearson_correlation(x_values: list[float], y_values: list[float]) -> float | None:
    if len(x_values) != len(y_values) or len(x_values) < 2:
        return None

    x_mean = statistics.fmean(x_values)
    y_mean = statistics.fmean(y_values)

    x_centered = [value - x_mean for value in x_values]
    y_centered = [value - y_mean for value in y_values]

    x_ss = sum(value * value for value in x_centered)
    y_ss = sum(value * value for value in y_centered)

    if x_ss <= 0 or y_ss <= 0:
        return None

    numerator = sum(
        x_value * y_value
        for x_value, y_value in zip(x_centered, y_centered, strict=True)
    )
    return numerator / math.sqrt(x_ss * y_ss)


def eta_squared(groups: dict[str, list[float]]) -> float | None:
    values = [value for group_values in groups.values() for value in group_values]
    if len(values) < 2:
        return None

    grand_mean = statistics.fmean(values)
    total_ss = sum((value - grand_mean) ** 2 for value in values)
    if total_ss <= 0:
        return 0.0

    between_ss = 0.0
    for group_values in groups.values():
        if not group_values:
            continue

        group_mean = statistics.fmean(group_values)
        between_ss += len(group_values) * ((group_mean - grand_mean) ** 2)

    return max(0.0, min(1.0, between_ss / total_ss))


def load_experiment(database_path: Path, experiment_name: str) -> Experiment:
    with sqlite3.connect(str(database_path)) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT experiment_name, grid_json
            FROM experiments
            WHERE experiment_name = ?
            """,
            (experiment_name,),
        ).fetchone()

    if row is None:
        raise RuntimeError(f"Experiment not found: {experiment_name}")

    return Experiment(
        experiment_name=row["experiment_name"],
        grid=read_json_object(row["grid_json"]),
    )


def load_trials(database_path: Path, experiment_name: str) -> list[Trial]:
    with sqlite3.connect(str(database_path)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT *
            FROM trials
            WHERE experiment_name = ?
            ORDER BY created_at_unix ASC
            """,
            (experiment_name,),
        ).fetchall()

    trials: list[Trial] = []

    for row in rows:
        trials.append(
            Trial(
                trial_id=row["trial_id"],
                experiment_name=row["experiment_name"],
                config_id=row["config_id"],
                config=read_json_object(row["config_json"]),
                status=row["status"],
                metric_name=row["metric_name"],
                metric_value=(
                    None if row["metric_value"] is None else float(row["metric_value"])
                ),
                group_key=row["group_key"],
                group_value=row["group_value"],
                selection_reason=row["selection_reason"],
                created_at_unix=float(row["created_at_unix"]),
                completed_at_unix=(
                    None
                    if row["completed_at_unix"] is None
                    else float(row["completed_at_unix"])
                ),
                metadata=read_json_object(row["metadata_json"]),
            )
        )

    return trials


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=4, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def flatten_trial_for_csv(trial: Trial) -> dict[str, Any]:
    row: dict[str, Any] = {
        "trial_id": trial.trial_id,
        "experiment_name": trial.experiment_name,
        "config_id": trial.config_id,
        "status": trial.status,
        "metric_name": trial.metric_name,
        "metric_value": trial.metric_value,
        "group_key": trial.group_key,
        "group_value": trial.group_value,
        "selection_reason": trial.selection_reason,
        "created_at_unix": trial.created_at_unix,
        "completed_at_unix": trial.completed_at_unix,
    }

    for key, value in sorted(trial.config.items()):
        row[f"config.{key}"] = value

    for key, value in sorted(trial.metadata.items()):
        if isinstance(value, str | int | float | bool) or value is None:
            row[f"metadata.{key}"] = value
        else:
            row[f"metadata.{key}"] = stable_json(value)

    return row


def write_trials_csv(path: Path, trials: list[Trial]) -> None:
    rows = [flatten_trial_for_csv(trial) for trial in trials]
    path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fieldnames = sorted({key for row in rows for key in row.keys()})

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def successful_trials(trials: list[Trial]) -> list[Trial]:
    return [
        trial
        for trial in trials
        if trial.status == "ok" and trial.metric_value is not None
    ]


def successful_metric_values(trials: list[Trial]) -> list[float]:
    return [
        float(trial.metric_value)
        for trial in successful_trials(trials)
        if trial.metric_value is not None
    ]


def summarize_top_configs(
    trials: list[Trial],
    direction: MetricDirection,
    limit: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[Trial]] = defaultdict(list)

    for trial in successful_trials(trials):
        grouped[trial.config_id].append(trial)

    rows: list[dict[str, Any]] = []

    for config_id, config_trials in grouped.items():
        values = [
            float(trial.metric_value)
            for trial in config_trials
            if trial.metric_value is not None
        ]
        if not values:
            continue

        rows.append(
            {
                "config_id": config_id,
                "count": len(values),
                "mean": statistics.fmean(values),
                "median": statistics.median(values),
                "best": max(values) if direction == "maximize" else min(values),
                "stdev": statistics.pstdev(values) if len(values) > 1 else 0.0,
                "config": config_trials[0].config,
            }
        )

    reverse = direction == "maximize"
    rows.sort(key=lambda item: item["mean"], reverse=reverse)
    return rows[:limit]


def summarize_parameter_effects(
    trials: list[Trial],
    direction: MetricDirection,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    for trial in successful_trials(trials):
        if trial.metric_value is None:
            continue

        for name, value in trial.config.items():
            grouped[name][stable_json(value)].append(float(trial.metric_value))

    output: dict[str, list[dict[str, Any]]] = {}

    for parameter, values_by_parameter in grouped.items():
        rows = []
        for value, values in values_by_parameter.items():
            rows.append(
                {
                    "parameter": parameter,
                    "value": value,
                    "count": len(values),
                    "mean": statistics.fmean(values),
                    "median": statistics.median(values),
                    "min": min(values),
                    "max": max(values),
                    "stdev": statistics.pstdev(values) if len(values) > 1 else 0.0,
                }
            )

        rows.sort(key=lambda item: item["mean"], reverse=(direction == "maximize"))
        output[parameter] = rows

    return output


def summarize_group_performance(
    trials: list[Trial],
    direction: MetricDirection,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[float]] = defaultdict(list)

    for trial in successful_trials(trials):
        if trial.metric_value is None:
            continue

        group = trial.group_value or "ungrouped"
        grouped[group].append(float(trial.metric_value))

    rows: list[dict[str, Any]] = []
    for group, values in grouped.items():
        rows.append(
            {
                "group": group,
                "count": len(values),
                "mean": statistics.fmean(values),
                "median": statistics.median(values),
                "min": min(values),
                "max": max(values),
                "stdev": statistics.pstdev(values) if len(values) > 1 else 0.0,
            }
        )

    rows.sort(key=lambda item: item["mean"], reverse=(direction == "maximize"))
    return rows


def parameter_index_maps(grid: dict[str, Any]) -> dict[str, dict[str, int]]:
    maps: dict[str, dict[str, int]] = {}

    for parameter, values in grid_parameter_values(grid).items():
        maps[parameter] = {
            stable_json(value): index for index, value in enumerate(values)
        }

    return maps


def summarize_parameter_importance(
    experiment: Experiment,
    trials: list[Trial],
) -> list[dict[str, Any]]:
    direction = metric_direction_from_grid(experiment.grid)
    index_maps = parameter_index_maps(experiment.grid)
    objective_groups: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    raw_groups: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    index_values: dict[str, list[float]] = defaultdict(list)
    objective_values: dict[str, list[float]] = defaultdict(list)

    for trial in successful_trials(trials):
        if trial.metric_value is None:
            continue

        raw_metric = float(trial.metric_value)
        objective = objective_value(raw_metric, direction)

        for parameter, value in trial.config.items():
            value_key = stable_json(value)
            objective_groups[parameter][value_key].append(objective)
            raw_groups[parameter][value_key].append(raw_metric)

            parameter_indexes = index_maps.get(parameter)
            if parameter_indexes and value_key in parameter_indexes:
                index_values[parameter].append(float(parameter_indexes[value_key]))
                objective_values[parameter].append(objective)

    rows: list[dict[str, Any]] = []

    for parameter, groups in objective_groups.items():
        eta = eta_squared(groups)
        value_rows: list[dict[str, Any]] = []

        for value_key, values in groups.items():
            raw_values = raw_groups[parameter][value_key]
            value_rows.append(
                {
                    "value": value_key,
                    "count": len(values),
                    "objective_mean": statistics.fmean(values),
                    "metric_mean": statistics.fmean(raw_values),
                    "metric_median": statistics.median(raw_values),
                }
            )

        value_rows.sort(key=lambda item: item["objective_mean"], reverse=True)

        directional_correlation = pearson_correlation(
            index_values.get(parameter, []),
            objective_values.get(parameter, []),
        )

        best = value_rows[0] if value_rows else None
        worst = value_rows[-1] if value_rows else None

        rows.append(
            {
                "parameter": parameter,
                "count": sum(len(values) for values in groups.values()),
                "unique_values": len(groups),
                "eta_squared": eta,
                "directional_correlation": directional_correlation,
                "best_value": None if best is None else best["value"],
                "worst_value": None if worst is None else worst["value"],
                "best_metric_mean": None if best is None else best["metric_mean"],
                "worst_metric_mean": None if worst is None else worst["metric_mean"],
                "metric_mean_spread": (
                    None
                    if best is None or worst is None
                    else abs(float(best["metric_mean"]) - float(worst["metric_mean"]))
                ),
                "value_summaries": value_rows,
            }
        )

    rows.sort(key=lambda item: item["eta_squared"] or 0.0, reverse=True)
    return rows


def summarize_pairwise_interactions(
    experiment: Experiment,
    trials: list[Trial],
    parameter_importance: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    direction = metric_direction_from_grid(experiment.grid)
    single_importance = {
        row["parameter"]: float(row["eta_squared"] or 0.0)
        for row in parameter_importance
    }
    all_parameters = sorted(single_importance.keys())
    rows: list[dict[str, Any]] = []

    for left, right in combinations(all_parameters, 2):
        groups: dict[str, list[float]] = defaultdict(list)

        for trial in successful_trials(trials):
            if trial.metric_value is None:
                continue

            if left not in trial.config or right not in trial.config:
                continue

            key = f"{stable_json(trial.config[left])} × {stable_json(trial.config[right])}"
            groups[key].append(objective_value(float(trial.metric_value), direction))

        pair_eta = eta_squared(groups)
        if pair_eta is None:
            continue

        strongest_single = max(
            single_importance.get(left, 0.0), single_importance.get(right, 0.0)
        )
        additive_single = min(
            1.0, single_importance.get(left, 0.0) + single_importance.get(right, 0.0)
        )

        rows.append(
            {
                "left": left,
                "right": right,
                "pair_eta_squared": pair_eta,
                "strongest_single_eta_squared": strongest_single,
                "additive_single_eta_squared": additive_single,
                "interaction_lift_over_strongest": pair_eta - strongest_single,
                "interaction_lift_over_additive": pair_eta - additive_single,
            }
        )

    rows.sort(key=lambda item: item["pair_eta_squared"], reverse=True)
    return rows[:limit]


def summarize_overall_signal(
    parameter_importance: list[dict[str, Any]],
) -> dict[str, Any]:
    eta_values = [
        float(row["eta_squared"])
        for row in parameter_importance
        if row.get("eta_squared") is not None
    ]
    corr_values = [
        abs(float(row["directional_correlation"]))
        for row in parameter_importance
        if row.get("directional_correlation") is not None
    ]

    return {
        "parameter_count": len(parameter_importance),
        "mean_eta_squared": statistics.fmean(eta_values) if eta_values else None,
        "max_eta_squared": max(eta_values) if eta_values else None,
        "mean_abs_directional_correlation": (
            statistics.fmean(corr_values) if corr_values else None
        ),
        "max_abs_directional_correlation": max(corr_values) if corr_values else None,
        "interpretation": (
            "Closer to 1.0 means the tested parameter values explain more of the observed objective variance. "
            "This is descriptive, not causal, and can be distorted by sparse samples or correlated parameters."
        ),
    }


def build_summary(
    experiment: Experiment,
    trials: list[Trial],
    top_limit: int,
    interaction_limit: int,
) -> dict[str, Any]:
    metric_name = metric_name_from_grid(experiment.grid)
    direction = metric_direction_from_grid(experiment.grid)
    values = successful_metric_values(trials)
    parameter_importance = summarize_parameter_importance(experiment, trials)

    return {
        "experiment_name": experiment.experiment_name,
        "metric_name": metric_name,
        "metric_direction": direction,
        "trial_count": len(trials),
        "successful_trial_count": len(values),
        "status_counts": dict(Counter(trial.status for trial in trials)),
        "selection_reason_counts": dict(
            Counter(trial.selection_reason or "unknown" for trial in trials)
        ),
        "metric_summary": {
            "mean": statistics.fmean(values) if values else None,
            "median": statistics.median(values) if values else None,
            "min": min(values) if values else None,
            "max": max(values) if values else None,
            "stdev": statistics.pstdev(values) if len(values) > 1 else 0.0,
        },
        "top_configs": summarize_top_configs(trials, direction, top_limit),
        "parameter_effects": summarize_parameter_effects(trials, direction),
        "group_performance": summarize_group_performance(trials, direction),
        "parameter_importance": parameter_importance,
        "overall_grid_signal": summarize_overall_signal(parameter_importance),
        "pairwise_interactions": summarize_pairwise_interactions(
            experiment=experiment,
            trials=trials,
            parameter_importance=parameter_importance,
            limit=interaction_limit,
        ),
    }


def plot_metric_over_time(path: Path, trials: list[Trial], metric_name: str) -> None:
    successful = successful_trials(trials)
    if not successful:
        return

    x_values = list(range(1, len(successful) + 1))
    y_values = [
        float(trial.metric_value)
        for trial in successful
        if trial.metric_value is not None
    ]

    figure, axis = plt.subplots(figsize=(12, 6))
    axis.plot(x_values, y_values, marker="o", linewidth=1)
    axis.set_title(f"{metric_name} over time")
    axis.set_xlabel("Successful trial")
    axis.set_ylabel(metric_name)
    axis.grid(True, alpha=0.3)
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def plot_cumulative_best(
    path: Path,
    trials: list[Trial],
    metric_name: str,
    direction: MetricDirection,
) -> None:
    successful = successful_trials(trials)
    if not successful:
        return

    x_values: list[int] = []
    y_values: list[float] = []
    best: float | None = None

    for index, trial in enumerate(successful, start=1):
        if trial.metric_value is None:
            continue

        value = float(trial.metric_value)
        if best is None:
            best = value
        elif direction == "maximize":
            best = max(best, value)
        else:
            best = min(best, value)

        x_values.append(index)
        y_values.append(best)

    figure, axis = plt.subplots(figsize=(12, 6))
    axis.plot(x_values, y_values, linewidth=2)
    axis.set_title(f"Cumulative best {metric_name}")
    axis.set_xlabel("Successful trial")
    axis.set_ylabel(metric_name)
    axis.grid(True, alpha=0.3)
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def plot_counter(path: Path, title: str, counter: Counter[str]) -> None:
    if not counter:
        return

    items = counter.most_common()
    labels = [item[0] for item in items]
    values = [item[1] for item in items]

    figure_width = max(10, min(24, len(labels) * 0.7))
    figure, axis = plt.subplots(figsize=(figure_width, 6))
    axis.bar(range(len(labels)), values)
    axis.set_title(title)
    axis.set_xticks(range(len(labels)))
    axis.set_xticklabels(labels, rotation=45, ha="right")
    axis.set_ylabel("Count")
    axis.grid(True, axis="y", alpha=0.3)
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def plot_parameter_effect(
    path: Path,
    parameter: str,
    rows: list[dict[str, Any]],
    metric_name: str,
) -> None:
    if not rows:
        return

    labels = [str(row["value"]) for row in rows]
    values = [float(row["mean"]) for row in rows]
    counts = [int(row["count"]) for row in rows]

    figure, axis = plt.subplots(figsize=(max(8, len(labels) * 0.8), 5))
    axis.bar(range(len(labels)), values)
    axis.set_title(f"Mean {metric_name} by {parameter}")
    axis.set_xlabel(parameter)
    axis.set_ylabel(f"Mean {metric_name}")
    axis.set_xticks(range(len(labels)))
    axis.set_xticklabels(labels, rotation=45, ha="right")
    axis.grid(True, axis="y", alpha=0.3)

    for index, count in enumerate(counts):
        axis.text(
            index, values[index], f"n={count}", ha="center", va="bottom", fontsize=8
        )

    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def plot_parameter_importance(
    path: Path,
    parameter_importance: list[dict[str, Any]],
) -> None:
    rows = [row for row in parameter_importance if row.get("eta_squared") is not None]
    if not rows:
        return

    labels = [str(row["parameter"]) for row in rows]
    values = [float(row["eta_squared"]) for row in rows]

    figure_height = max(6, min(24, len(labels) * 0.55))
    figure, axis = plt.subplots(figsize=(12, figure_height))
    axis.barh(range(len(labels)), values)
    axis.set_title("Parameter importance by eta-squared")
    axis.set_xlabel("Eta-squared objective variance explained")
    axis.set_ylabel("Parameter")
    axis.set_yticks(range(len(labels)))
    axis.set_yticklabels(labels)
    axis.invert_yaxis()
    axis.grid(True, axis="x", alpha=0.3)
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def plot_directional_correlations(
    path: Path,
    parameter_importance: list[dict[str, Any]],
) -> None:
    rows = [
        row
        for row in parameter_importance
        if row.get("directional_correlation") is not None
    ]
    if not rows:
        return

    rows.sort(
        key=lambda item: abs(float(item["directional_correlation"])), reverse=True
    )
    labels = [str(row["parameter"]) for row in rows]
    values = [float(row["directional_correlation"]) for row in rows]

    figure_height = max(6, min(24, len(labels) * 0.55))
    figure, axis = plt.subplots(figsize=(12, figure_height))
    axis.barh(range(len(labels)), values)
    axis.set_title("Directional correlation by grid value order")
    axis.set_xlabel("Correlation with objective value")
    axis.set_ylabel("Parameter")
    axis.set_yticks(range(len(labels)))
    axis.set_yticklabels(labels)
    axis.axvline(0.0, linewidth=1)
    axis.invert_yaxis()
    axis.grid(True, axis="x", alpha=0.3)
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def plot_group_performance(
    path: Path,
    trials: list[Trial],
    metric_name: str,
    max_groups: int,
) -> None:
    grouped: dict[str, list[float]] = defaultdict(list)

    for trial in successful_trials(trials):
        if trial.metric_value is None:
            continue

        grouped[trial.group_value or "ungrouped"].append(float(trial.metric_value))

    if not grouped:
        return

    ordered = sorted(grouped.items(), key=lambda item: len(item[1]), reverse=True)[
        :max_groups
    ]
    labels = [item[0] for item in ordered]
    values = [item[1] for item in ordered]

    figure_width = max(10, min(24, len(labels) * 0.8))
    figure, axis = plt.subplots(figsize=(figure_width, 7))
    axis.boxplot(values, tick_labels=labels, showmeans=True)
    axis.set_title(f"{metric_name} distribution by group")
    axis.set_xlabel("Group")
    axis.set_ylabel(metric_name)
    axis.tick_params(axis="x", labelrotation=45)
    axis.grid(True, axis="y", alpha=0.3)
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def short_config_label(
    config_id: str, config: dict[str, Any], max_parts: int = 4
) -> str:
    parts = []
    for key in sorted(config.keys())[:max_parts]:
        parts.append(f"{key}={config[key]}")

    body = ", ".join(parts)
    if len(config) > max_parts:
        body += ", ..."

    return f"{config_id}\n{body}"


def plot_top_configs(
    path: Path, top_configs: list[dict[str, Any]], metric_name: str
) -> None:
    if not top_configs:
        return

    labels = [
        short_config_label(str(row["config_id"]), row["config"]) for row in top_configs
    ]
    values = [float(row["mean"]) for row in top_configs]

    figure_height = max(7, min(24, len(labels) * 0.9))
    figure, axis = plt.subplots(figsize=(14, figure_height))
    axis.barh(range(len(labels)), values)
    axis.set_title(f"Top configs by mean {metric_name}")
    axis.set_xlabel(f"Mean {metric_name}")
    axis.set_ylabel("Config")
    axis.set_yticks(range(len(labels)))
    axis.set_yticklabels(labels)
    axis.invert_yaxis()
    axis.grid(True, axis="x", alpha=0.3)
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def choose_heatmap_parameters(
    parameter_importance: list[dict[str, Any]],
    heatmap_x: str | None,
    heatmap_y: str | None,
) -> tuple[str, str] | None:
    if heatmap_x and heatmap_y:
        return heatmap_x, heatmap_y

    parameters = [
        str(row["parameter"])
        for row in parameter_importance
        if int(row.get("unique_values") or 0) >= 2
    ]

    if heatmap_x and not heatmap_y:
        for parameter in parameters:
            if parameter != heatmap_x:
                return heatmap_x, parameter
        return None

    if heatmap_y and not heatmap_x:
        for parameter in parameters:
            if parameter != heatmap_y:
                return parameter, heatmap_y
        return None

    if len(parameters) < 2:
        return None

    return parameters[0], parameters[1]


def plot_parameter_heatmap(
    path: Path,
    trials: list[Trial],
    metric_name: str,
    x_parameter: str,
    y_parameter: str,
) -> None:
    buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    x_values_set: set[str] = set()
    y_values_set: set[str] = set()

    for trial in successful_trials(trials):
        if trial.metric_value is None:
            continue

        if x_parameter not in trial.config or y_parameter not in trial.config:
            continue

        x_value = display_value(trial.config[x_parameter])
        y_value = display_value(trial.config[y_parameter])
        x_values_set.add(x_value)
        y_values_set.add(y_value)
        buckets[(x_value, y_value)].append(float(trial.metric_value))

    if not buckets:
        return

    x_values = sorted(x_values_set)
    y_values = sorted(y_values_set)

    matrix: list[list[float]] = []
    for y_value in y_values:
        row: list[float] = []
        for x_value in x_values:
            values = buckets.get((x_value, y_value), [])
            row.append(statistics.fmean(values) if values else math.nan)
        matrix.append(row)

    figure_width = max(9, min(24, len(x_values) * 0.9))
    figure_height = max(7, min(20, len(y_values) * 0.8))
    figure, axis = plt.subplots(figsize=(figure_width, figure_height))
    image = axis.imshow(matrix, aspect="auto")
    axis.set_title(f"Mean {metric_name}: {y_parameter} × {x_parameter}")
    axis.set_xlabel(x_parameter)
    axis.set_ylabel(y_parameter)
    axis.set_xticks(range(len(x_values)))
    axis.set_xticklabels(x_values, rotation=45, ha="right")
    axis.set_yticks(range(len(y_values)))
    axis.set_yticklabels(y_values)
    figure.colorbar(image, ax=axis, label=f"Mean {metric_name}")

    for y_index, row in enumerate(matrix):
        for x_index, value in enumerate(row):
            if not math.isnan(value):
                axis.text(
                    x_index,
                    y_index,
                    f"{value:.2f}",
                    ha="center",
                    va="center",
                    fontsize=8,
                )

    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def plot_pairwise_interactions(
    path: Path,
    pairwise_interactions: list[dict[str, Any]],
    limit: int,
) -> None:
    rows = pairwise_interactions[:limit]
    if not rows:
        return

    labels = [f"{row['left']} × {row['right']}" for row in rows]
    values = [float(row["pair_eta_squared"]) for row in rows]

    figure_height = max(6, min(24, len(labels) * 0.65))
    figure, axis = plt.subplots(figsize=(13, figure_height))
    axis.barh(range(len(labels)), values)
    axis.set_title("Pairwise interaction strength by eta-squared")
    axis.set_xlabel("Pair eta-squared")
    axis.set_ylabel("Parameter pair")
    axis.set_yticks(range(len(labels)))
    axis.set_yticklabels(labels)
    axis.invert_yaxis()
    axis.grid(True, axis="x", alpha=0.3)
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def build_markdown_report(summary: dict[str, Any], generated_files: list[str]) -> str:
    lines = [
        f"# Grid Search Report: {summary['experiment_name']}",
        "",
        f"- Metric: `{summary['metric_name']}`",
        f"- Direction: `{summary['metric_direction']}`",
        f"- Trials: `{summary['trial_count']}`",
        f"- Successful trials: `{summary['successful_trial_count']}`",
        "",
        "## Metric Summary",
        "",
        "| Statistic | Value |",
        "|---|---:|",
    ]

    metric_summary = summary["metric_summary"]
    for key in ["mean", "median", "min", "max", "stdev"]:
        value = metric_summary.get(key)
        lines.append(
            f"| {key} | {'null' if value is None else f'{float(value):.6g}'} |"
        )

    signal = summary["overall_grid_signal"]
    lines.extend(
        [
            "",
            "## Overall Grid Signal",
            "",
            "| Statistic | Value |",
            "|---|---:|",
            f"| Parameter count | {signal['parameter_count']} |",
            f"| Mean eta-squared | {'null' if signal['mean_eta_squared'] is None else f'{float(signal['mean_eta_squared']):.6g}'} |",
            f"| Max eta-squared | {'null' if signal['max_eta_squared'] is None else f'{float(signal['max_eta_squared']):.6g}'} |",
            f"| Mean absolute directional correlation | {'null' if signal['mean_abs_directional_correlation'] is None else f'{float(signal['mean_abs_directional_correlation']):.6g}'} |",
            "",
            signal["interpretation"],
            "",
            "## Top Configs",
            "",
            "| Rank | Config ID | Count | Mean | Median | Best |",
            "|---:|---|---:|---:|---:|---:|",
        ]
    )

    for index, row in enumerate(summary["top_configs"], start=1):
        lines.append(
            f"| {index} | `{row['config_id']}` | {row['count']} | "
            f"{float(row['mean']):.6g} | {float(row['median']):.6g} | {float(row['best']):.6g} |"
        )

    lines.extend(
        [
            "",
            "## Parameter Importance",
            "",
            "| Rank | Parameter | Eta-squared | Directional correlation | Best value | Worst value |",
            "|---:|---|---:|---:|---|---|",
        ]
    )

    for index, row in enumerate(summary["parameter_importance"], start=1):
        eta = row["eta_squared"]
        correlation = row["directional_correlation"]
        lines.append(
            f"| {index} | `{row['parameter']}` | "
            f"{'null' if eta is None else f'{float(eta):.6g}'} | "
            f"{'null' if correlation is None else f'{float(correlation):.6g}'} | "
            f"`{row['best_value']}` | `{row['worst_value']}` |"
        )

    lines.extend(
        [
            "",
            "## Group Performance",
            "",
            "| Group | Count | Mean | Median | Min | Max |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )

    for row in summary["group_performance"]:
        lines.append(
            f"| `{row['group']}` | {row['count']} | {float(row['mean']):.6g} | "
            f"{float(row['median']):.6g} | {float(row['min']):.6g} | {float(row['max']):.6g} |"
        )

    lines.extend(["", "## Generated Files", ""])
    lines.extend(f"- `{path}`" for path in generated_files)
    lines.append("")

    return "\n".join(lines)


def generate_report(
    database: str | Path,
    experiment: str,
    output_dir: str | Path,
    top_limit: int = 20,
    max_groups: int = 20,
    heatmap_x: str | None = None,
    heatmap_y: str | None = None,
    interaction_limit: int = 30,
) -> dict[str, Any]:
    database_path = Path(database).expanduser().resolve()
    output_path = Path(output_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    experiment_row = load_experiment(database_path, experiment)
    trials = load_trials(database_path, experiment)
    summary = build_summary(experiment_row, trials, top_limit, interaction_limit)

    plots_dir = output_path / "plots"
    parameter_dir = plots_dir / "parameter_effects"
    parameter_dir.mkdir(parents=True, exist_ok=True)

    generated_files: list[str] = []

    trials_csv = output_path / "trials.csv"
    write_trials_csv(trials_csv, trials)
    generated_files.append(str(trials_csv))

    summary_json = output_path / "summary.json"
    write_json(summary_json, summary)
    generated_files.append(str(summary_json))

    metric_name = summary["metric_name"]
    direction = summary["metric_direction"]

    metric_over_time = plots_dir / "metric_over_time.png"
    plot_metric_over_time(metric_over_time, trials, metric_name)
    if metric_over_time.exists():
        generated_files.append(str(metric_over_time))

    cumulative_best = plots_dir / "cumulative_best.png"
    plot_cumulative_best(cumulative_best, trials, metric_name, direction)
    if cumulative_best.exists():
        generated_files.append(str(cumulative_best))

    status_counts = plots_dir / "status_counts.png"
    plot_counter(
        status_counts, "Trial status counts", Counter(trial.status for trial in trials)
    )
    if status_counts.exists():
        generated_files.append(str(status_counts))

    selection_counts = plots_dir / "selection_reason_counts.png"
    plot_counter(
        selection_counts,
        "Selection reason counts",
        Counter(trial.selection_reason or "unknown" for trial in trials),
    )
    if selection_counts.exists():
        generated_files.append(str(selection_counts))

    parameter_importance = plots_dir / "parameter_importance.png"
    plot_parameter_importance(parameter_importance, summary["parameter_importance"])
    if parameter_importance.exists():
        generated_files.append(str(parameter_importance))

    directional_correlations = plots_dir / "directional_correlations.png"
    plot_directional_correlations(
        directional_correlations, summary["parameter_importance"]
    )
    if directional_correlations.exists():
        generated_files.append(str(directional_correlations))

    group_performance = plots_dir / "group_performance.png"
    plot_group_performance(group_performance, trials, metric_name, max_groups)
    if group_performance.exists():
        generated_files.append(str(group_performance))

    top_configs = plots_dir / "top_configs.png"
    plot_top_configs(top_configs, summary["top_configs"], metric_name)
    if top_configs.exists():
        generated_files.append(str(top_configs))

    pairwise_interactions = plots_dir / "pairwise_interactions.png"
    plot_pairwise_interactions(
        pairwise_interactions, summary["pairwise_interactions"], interaction_limit
    )
    if pairwise_interactions.exists():
        generated_files.append(str(pairwise_interactions))

    chosen_heatmap_parameters = choose_heatmap_parameters(
        parameter_importance=summary["parameter_importance"],
        heatmap_x=heatmap_x,
        heatmap_y=heatmap_y,
    )
    if chosen_heatmap_parameters is not None:
        heatmap = plots_dir / "parameter_heatmap.png"
        plot_parameter_heatmap(
            heatmap,
            trials,
            metric_name,
            x_parameter=chosen_heatmap_parameters[0],
            y_parameter=chosen_heatmap_parameters[1],
        )
        if heatmap.exists():
            generated_files.append(str(heatmap))

    for parameter, rows in summary["parameter_effects"].items():
        parameter_path = parameter_dir / f"{parameter}.png"
        plot_parameter_effect(parameter_path, parameter, rows, metric_name)
        if parameter_path.exists():
            generated_files.append(str(parameter_path))

    summary_md = output_path / "summary.md"
    write_text(summary_md, build_markdown_report(summary, generated_files))
    generated_files.append(str(summary_md))

    manifest = {
        "database": str(database_path),
        "experiment_name": experiment,
        "output_dir": str(output_path),
        "generated_files": generated_files,
    }

    manifest_path = output_path / "report_manifest.json"
    write_json(manifest_path, manifest)

    return manifest
