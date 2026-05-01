from __future__ import annotations

import csv
import dataclasses
import json
import sqlite3
import statistics
from collections import Counter
from collections import defaultdict
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


def successful_metric_values(trials: list[Trial]) -> list[float]:
    return [
        float(trial.metric_value)
        for trial in trials
        if trial.status == "ok" and trial.metric_value is not None
    ]


def summarize_top_configs(
    trials: list[Trial],
    direction: MetricDirection,
    limit: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[Trial]] = defaultdict(list)

    for trial in trials:
        if trial.status == "ok" and trial.metric_value is not None:
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
                "config": config_trials[0].config,
            }
        )

    reverse = direction == "maximize"
    rows.sort(key=lambda item: item["mean"], reverse=reverse)
    return rows[:limit]


def summarize_parameter_effects(trials: list[Trial]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    for trial in trials:
        if trial.status != "ok" or trial.metric_value is None:
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
                }
            )
        rows.sort(key=lambda item: item["mean"], reverse=True)
        output[parameter] = rows

    return output


def build_summary(
    experiment: Experiment, trials: list[Trial], top_limit: int
) -> dict[str, Any]:
    metric_name = metric_name_from_grid(experiment.grid)
    direction = metric_direction_from_grid(experiment.grid)
    values = successful_metric_values(trials)

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
        },
        "top_configs": summarize_top_configs(trials, direction, top_limit),
        "parameter_effects": summarize_parameter_effects(trials),
    }


def plot_metric_over_time(path: Path, trials: list[Trial], metric_name: str) -> None:
    successful = [
        trial
        for trial in trials
        if trial.status == "ok" and trial.metric_value is not None
    ]
    if not successful:
        return

    x_values = list(range(1, len(successful) + 1))
    y_values = [float(trial.metric_value) for trial in successful]

    figure, axis = plt.subplots(figsize=(10, 5))
    axis.plot(x_values, y_values, marker="o", linewidth=1)
    axis.set_title(f"{metric_name} over time")
    axis.set_xlabel("Successful trial")
    axis.set_ylabel(metric_name)
    axis.grid(True, alpha=0.3)
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def plot_cumulative_best(
    path: Path, trials: list[Trial], metric_name: str, direction: MetricDirection
) -> None:
    successful = [
        trial
        for trial in trials
        if trial.status == "ok" and trial.metric_value is not None
    ]
    if not successful:
        return

    x_values: list[int] = []
    y_values: list[float] = []
    best: float | None = None

    for index, trial in enumerate(successful, start=1):
        value = float(trial.metric_value)
        if best is None:
            best = value
        elif direction == "maximize":
            best = max(best, value)
        else:
            best = min(best, value)

        x_values.append(index)
        y_values.append(best)

    figure, axis = plt.subplots(figsize=(10, 5))
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

    figure, axis = plt.subplots(figsize=(10, 5))
    axis.bar(range(len(labels)), values)
    axis.set_title(title)
    axis.set_xticks(range(len(labels)))
    axis.set_xticklabels(labels, rotation=45, ha="right")
    axis.grid(True, axis="y", alpha=0.3)
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def plot_parameter_effect(
    path: Path, parameter: str, rows: list[dict[str, Any]], metric_name: str
) -> None:
    if not rows:
        return

    labels = [str(row["value"]) for row in rows]
    values = [float(row["mean"]) for row in rows]

    figure, axis = plt.subplots(figsize=(max(8, len(labels) * 0.8), 5))
    axis.bar(range(len(labels)), values)
    axis.set_title(f"Mean {metric_name} by {parameter}")
    axis.set_xlabel(parameter)
    axis.set_ylabel(f"Mean {metric_name}")
    axis.set_xticks(range(len(labels)))
    axis.set_xticklabels(labels, rotation=45, ha="right")
    axis.grid(True, axis="y", alpha=0.3)
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
        "## Top Configs",
        "",
        "| Rank | Config ID | Count | Mean | Median |",
        "|---:|---|---:|---:|---:|",
    ]

    for index, row in enumerate(summary["top_configs"], start=1):
        lines.append(
            f"| {index} | `{row['config_id']}` | {row['count']} | "
            f"{float(row['mean']):.6g} | {float(row['median']):.6g} |"
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
) -> dict[str, Any]:
    database_path = Path(database).expanduser().resolve()
    output_path = Path(output_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    experiment_row = load_experiment(database_path, experiment)
    trials = load_trials(database_path, experiment)
    summary = build_summary(experiment_row, trials, top_limit)

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
