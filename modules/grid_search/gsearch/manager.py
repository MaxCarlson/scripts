from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import random
import sqlite3
import statistics
import time
import uuid
from pathlib import Path
from typing import Any, Literal

MetricDirection = Literal["maximize", "minimize"]
GroupMode = Literal["global", "per-group", "hybrid"]
SelectionMode = Literal["adaptive", "coverage", "random", "ucb", "neighbor"]


DEFAULT_POLICY: dict[str, Any] = {
    "warmup_trials": 40,
    "epsilon_start": 0.35,
    "epsilon_floor": 0.08,
    "epsilon_decay_trials": 180,
    "ucb_weight": 0.75,
    "candidate_pool_size": 256,
    "neighbor_probability_after_warmup": 0.55,
    "ucb_probability_after_warmup": 0.30,
    "coverage_probability_after_warmup": 0.15,
    "min_group_trials": 16,
    "planned_trial_ttl_seconds": 21600,
}


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


def now_unix() -> float:
    return time.time()


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def config_id(config: dict[str, Any]) -> str:
    return hashlib.sha256(stable_json(config).encode("utf-8")).hexdigest()[:16]


def normalize_group_value(value: str | None) -> str | None:
    if value is None:
        return None

    stripped = value.strip().lower()
    return stripped or None


def read_json_file(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()

    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"Could not read JSON file: {resolved}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON file: {resolved}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON root must be an object: {resolved}")

    return payload


def write_json_file(path: str | Path, payload: dict[str, Any]) -> None:
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(
        json.dumps(payload, indent=4, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def parse_json_object(value: str | None, label: str) -> dict[str, Any]:
    if value is None or not value.strip():
        return {}

    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} is not valid JSON") from exc

    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} must be a JSON object")

    return payload


class GridSpec:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        parameters = payload.get("parameters")

        if not isinstance(parameters, dict) or not parameters:
            raise RuntimeError(
                "Grid spec must contain a non-empty 'parameters' object."
            )

        self.parameters: dict[str, dict[str, Any]] = {}
        for name, spec in parameters.items():
            if not isinstance(name, str) or not name:
                raise RuntimeError("Parameter names must be non-empty strings.")
            if not isinstance(spec, dict):
                raise RuntimeError(f"Parameter {name!r} spec must be an object.")
            values = spec.get("values")
            if not isinstance(values, list) or not values:
                raise RuntimeError(
                    f"Parameter {name!r} must define a non-empty values list."
                )
            self.parameters[name] = spec

        baseline = payload.get("baseline", {})
        self.baseline = baseline if isinstance(baseline, dict) else {}

        metric = payload.get("metric")
        if not isinstance(metric, dict):
            raise RuntimeError(
                "Grid spec must contain a metric object, e.g. "
                '{"metric": {"name": "average_mbps", "direction": "maximize"}}.'
            )

        metric_name = metric.get("name")
        if not isinstance(metric_name, str) or not metric_name.strip():
            raise RuntimeError("Grid metric.name must be a non-empty string.")

        metric_direction = metric.get("direction")
        if metric_direction not in {"maximize", "minimize"}:
            raise RuntimeError(
                "Grid metric.direction must be either 'maximize' or 'minimize'."
            )

        self.metric_name = metric_name.strip()
        self.metric_direction: MetricDirection = metric_direction

        policy = dict(DEFAULT_POLICY)
        raw_policy = payload.get("policy")
        if isinstance(raw_policy, dict):
            policy.update(raw_policy)
        self.policy = policy

        constraints = payload.get("constraints", [])
        self.constraints = constraints if isinstance(constraints, list) else []

    def parameter_names(self) -> list[str]:
        def sort_key(name: str) -> tuple[int, str]:
            priority = self.parameters[name].get("priority", 99)
            try:
                priority_value = int(priority)
            except Exception:
                priority_value = 99
            return priority_value, name

        return sorted(self.parameters.keys(), key=sort_key)

    def values_for(self, name: str) -> list[Any]:
        return list(self.parameters[name]["values"])

    def normalize_config(self, partial_config: dict[str, Any]) -> dict[str, Any]:
        config = dict(self.baseline)
        config.update(partial_config)

        for name in self.parameter_names():
            if name not in config:
                config[name] = self.values_for(name)[0]

        return config

    def is_active(self, name: str, config: dict[str, Any]) -> bool:
        active_when = self.parameters[name].get("active_when")
        if not isinstance(active_when, dict):
            return True

        return all(config.get(key) == expected for key, expected in active_when.items())

    def strip_inactive(self, config: dict[str, Any]) -> dict[str, Any]:
        normalized = self.normalize_config(config)
        stripped: dict[str, Any] = {}

        for name in self.parameter_names():
            if self.is_active(name, normalized):
                stripped[name] = normalized[name]

        return stripped

    def active_parameter_names(self, config: dict[str, Any]) -> list[str]:
        normalized = self.normalize_config(config)
        return [
            name for name in self.parameter_names() if self.is_active(name, normalized)
        ]

    def is_valid_value_membership(self, config: dict[str, Any]) -> bool:
        normalized = self.normalize_config(config)

        for name in self.parameter_names():
            if normalized.get(name) not in self.values_for(name):
                return False

        return True

    def constraint_is_active(
        self, constraint: dict[str, Any], config: dict[str, Any]
    ) -> bool:
        active_when = constraint.get("active_when")
        if not isinstance(active_when, dict):
            return True

        return all(config.get(key) == expected for key, expected in active_when.items())

    def evaluate_constraint(
        self, constraint: dict[str, Any], config: dict[str, Any]
    ) -> bool:
        if not self.constraint_is_active(constraint, config):
            return True

        constraint_type = constraint.get("type")

        if constraint_type == "greater_equal":
            left = constraint.get("left")
            right = constraint.get("right")
            if not isinstance(left, str) or not isinstance(right, str):
                return False
            return float(config.get(left, 0)) >= float(config.get(right, 0))

        if constraint_type == "less_equal":
            left = constraint.get("left")
            right = constraint.get("right")
            if not isinstance(left, str) or not isinstance(right, str):
                return False
            return float(config.get(left, 0)) <= float(config.get(right, 0))

        if constraint_type == "not_equal":
            left = constraint.get("left")
            right = constraint.get("right")
            if not isinstance(left, str) or not isinstance(right, str):
                return False
            return config.get(left) != config.get(right)

        if constraint_type == "requires":
            when = constraint.get("when")
            require = constraint.get("require")
            if not isinstance(when, dict) or not isinstance(require, dict):
                return False
            if any(config.get(key) != expected for key, expected in when.items()):
                return True
            return all(config.get(key) == expected for key, expected in require.items())

        return True

    def is_valid_config(self, config: dict[str, Any]) -> bool:
        normalized = self.normalize_config(config)

        if not self.is_valid_value_membership(normalized):
            return False

        for constraint in self.constraints:
            if isinstance(constraint, dict) and not self.evaluate_constraint(
                constraint, normalized
            ):
                return False

        return True


class AdaptiveGridStore:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database_path))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize_schema(self) -> None:
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_name TEXT PRIMARY KEY,
                    grid_json TEXT NOT NULL,
                    created_at_unix REAL NOT NULL,
                    updated_at_unix REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trials (
                    trial_id TEXT PRIMARY KEY,
                    experiment_name TEXT NOT NULL,
                    config_id TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    metric_name TEXT NOT NULL,
                    metric_value REAL,
                    group_key TEXT,
                    group_value TEXT,
                    selection_reason TEXT,
                    created_at_unix REAL NOT NULL,
                    completed_at_unix REAL,
                    metadata_json TEXT NOT NULL,
                    FOREIGN KEY (experiment_name)
                        REFERENCES experiments(experiment_name)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_trials_experiment
                    ON trials(experiment_name);

                CREATE INDEX IF NOT EXISTS idx_trials_config
                    ON trials(experiment_name, config_id);

                CREATE INDEX IF NOT EXISTS idx_trials_group
                    ON trials(experiment_name, group_key, group_value);

                CREATE INDEX IF NOT EXISTS idx_trials_status
                    ON trials(experiment_name, status);
                """)

    def upsert_experiment(self, experiment_name: str, grid: dict[str, Any]) -> None:
        self.initialize_schema()
        GridSpec(grid)
        timestamp = now_unix()

        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO experiments (
                    experiment_name,
                    grid_json,
                    created_at_unix,
                    updated_at_unix
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(experiment_name) DO UPDATE SET
                    grid_json = excluded.grid_json,
                    updated_at_unix = excluded.updated_at_unix
                """,
                (
                    experiment_name,
                    json.dumps(grid, sort_keys=True, ensure_ascii=False),
                    timestamp,
                    timestamp,
                ),
            )

    def read_experiment_grid(self, experiment_name: str) -> dict[str, Any]:
        self.initialize_schema()

        with self.connect() as connection:
            row = connection.execute(
                "SELECT grid_json FROM experiments WHERE experiment_name = ?",
                (experiment_name,),
            ).fetchone()

        if row is None:
            raise RuntimeError(f"Experiment does not exist: {experiment_name}")

        payload = json.loads(row["grid_json"])
        if not isinstance(payload, dict):
            raise RuntimeError(
                f"Stored grid for experiment is invalid: {experiment_name}"
            )

        GridSpec(payload)
        return payload

    def load_trials(self, experiment_name: str) -> list[Trial]:
        self.initialize_schema()

        with self.connect() as connection:
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
            config = json.loads(row["config_json"])
            metadata = json.loads(row["metadata_json"])

            trials.append(
                Trial(
                    trial_id=row["trial_id"],
                    experiment_name=row["experiment_name"],
                    config_id=row["config_id"],
                    config=config,
                    status=row["status"],
                    metric_name=row["metric_name"],
                    metric_value=row["metric_value"],
                    group_key=row["group_key"],
                    group_value=row["group_value"],
                    selection_reason=row["selection_reason"],
                    created_at_unix=row["created_at_unix"],
                    completed_at_unix=row["completed_at_unix"],
                    metadata=metadata,
                )
            )

        return trials

    def expire_stale_planned_trials(
        self, experiment_name: str, ttl_seconds: float
    ) -> int:
        self.initialize_schema()
        cutoff = now_unix() - ttl_seconds

        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE trials
                SET status = 'expired',
                    completed_at_unix = ?
                WHERE experiment_name = ?
                    AND status = 'planned'
                    AND created_at_unix < ?
                """,
                (now_unix(), experiment_name, cutoff),
            )
            return int(cursor.rowcount or 0)

    def create_planned_trial(
        self,
        experiment_name: str,
        metric_name: str,
        config: dict[str, Any],
        group_key: str | None,
        group_value: str | None,
        selection_reason: str,
        metadata: dict[str, Any],
    ) -> Trial:
        self.initialize_schema()

        timestamp = now_unix()
        trial_id = str(uuid.uuid4())
        normalized_group_value = normalize_group_value(group_value)
        normalized_config_id = config_id(config)

        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO trials (
                    trial_id,
                    experiment_name,
                    config_id,
                    config_json,
                    status,
                    metric_name,
                    metric_value,
                    group_key,
                    group_value,
                    selection_reason,
                    created_at_unix,
                    completed_at_unix,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trial_id,
                    experiment_name,
                    normalized_config_id,
                    json.dumps(config, sort_keys=True, ensure_ascii=False),
                    "planned",
                    metric_name,
                    None,
                    group_key,
                    normalized_group_value,
                    selection_reason,
                    timestamp,
                    None,
                    json.dumps(metadata, sort_keys=True, ensure_ascii=False),
                ),
            )

        return Trial(
            trial_id=trial_id,
            experiment_name=experiment_name,
            config_id=normalized_config_id,
            config=config,
            status="planned",
            metric_name=metric_name,
            metric_value=None,
            group_key=group_key,
            group_value=normalized_group_value,
            selection_reason=selection_reason,
            created_at_unix=timestamp,
            completed_at_unix=None,
            metadata=metadata,
        )

    def record_result(
        self,
        trial_id: str,
        status: str,
        metric_value: float | None,
        metadata_update: dict[str, Any],
    ) -> None:
        self.initialize_schema()

        with self.connect() as connection:
            row = connection.execute(
                "SELECT metadata_json FROM trials WHERE trial_id = ?",
                (trial_id,),
            ).fetchone()

            if row is None:
                raise RuntimeError(f"Trial does not exist: {trial_id}")

            metadata = json.loads(row["metadata_json"])
            if not isinstance(metadata, dict):
                metadata = {}
            metadata.update(metadata_update)

            connection.execute(
                """
                UPDATE trials
                SET status = ?,
                    metric_value = ?,
                    completed_at_unix = ?,
                    metadata_json = ?
                WHERE trial_id = ?
                """,
                (
                    status,
                    metric_value,
                    now_unix(),
                    json.dumps(metadata, sort_keys=True, ensure_ascii=False),
                    trial_id,
                ),
            )


class AdaptiveGridOptimizer:
    def __init__(
        self,
        grid: GridSpec,
        trials: list[Trial],
        seed: int | None = None,
    ) -> None:
        self.grid = grid
        self.trials = trials
        self.rng = random.Random(seed)

    def successful_trials(self, trials: list[Trial] | None = None) -> list[Trial]:
        source = self.trials if trials is None else trials
        return [
            trial
            for trial in source
            if trial.status == "ok" and trial.metric_value is not None
        ]

    def active_trials(self, trials: list[Trial] | None = None) -> list[Trial]:
        source = self.trials if trials is None else trials
        return [
            trial
            for trial in source
            if trial.status in {"planned", "running", "ok", "failed"}
        ]

    def tried_config_ids(self, trials: list[Trial] | None = None) -> set[str]:
        return {trial.config_id for trial in self.active_trials(trials)}

    def scoped_trials(
        self,
        group_key: str | None,
        group_value: str | None,
        group_mode: GroupMode,
    ) -> tuple[list[Trial], str]:
        normalized_group_value = normalize_group_value(group_value)
        min_group_trials = int(self.grid.policy.get("min_group_trials", 16))

        if group_mode == "global" or not group_key or not normalized_group_value:
            return self.trials, "global"

        group_trials = [
            trial
            for trial in self.trials
            if trial.group_key == group_key
            and trial.group_value == normalized_group_value
        ]

        if group_mode == "per-group":
            return group_trials, "group"

        if len(self.successful_trials(group_trials)) >= min_group_trials:
            return group_trials, "group"

        return self.trials, "hybrid-global-fallback"

    def metric_reward(self, value: float) -> float:
        return value if self.grid.metric_direction == "maximize" else -value

    def epsilon(self, trial_count: int) -> float:
        start = float(self.grid.policy.get("epsilon_start", 0.35))
        floor = float(self.grid.policy.get("epsilon_floor", 0.08))
        decay = max(float(self.grid.policy.get("epsilon_decay_trials", 180)), 1.0)
        return floor + (start - floor) * math.exp(-trial_count / decay)

    def random_config(self) -> dict[str, Any]:
        config: dict[str, Any] = {}

        for name in self.grid.parameter_names():
            normalized = self.grid.normalize_config(config)
            if not self.grid.is_active(name, normalized):
                continue
            config[name] = self.rng.choice(self.grid.values_for(name))

        config = self.grid.strip_inactive(self.grid.normalize_config(config))

        if not self.grid.is_valid_config(config):
            return self.random_config()

        return config

    def coverage_counts(self, trials: list[Trial]) -> dict[tuple[str, str], int]:
        counts: dict[tuple[str, str], int] = {}

        for trial in self.active_trials(trials):
            for name, value in trial.config.items():
                key = (name, stable_json(value))
                counts[key] = counts.get(key, 0) + 1

        return counts

    def coverage_score(self, config: dict[str, Any], trials: list[Trial]) -> float:
        counts = self.coverage_counts(trials)
        score = 0.0

        for name in self.grid.active_parameter_names(config):
            key = (name, stable_json(config.get(name)))
            score += 1.0 / math.sqrt(counts.get(key, 0) + 1.0)

        return score

    def coverage_config(self, trials: list[Trial]) -> tuple[dict[str, Any], str]:
        pool_size = int(self.grid.policy.get("candidate_pool_size", 256))
        tried = self.tried_config_ids(trials)
        candidates: list[dict[str, Any]] = []
        attempts = max(pool_size * 4, 64)

        for _ in range(attempts):
            candidate = self.random_config()
            if config_id(candidate) not in tried:
                candidates.append(candidate)
            if len(candidates) >= pool_size:
                break

        if not candidates:
            candidates = [self.random_config() for _ in range(pool_size)]

        return (
            max(candidates, key=lambda item: self.coverage_score(item, trials)),
            "coverage",
        )

    def parameter_value_rewards(
        self, trials: list[Trial]
    ) -> dict[tuple[str, str], tuple[int, float]]:
        grouped: dict[tuple[str, str], list[float]] = {}

        for trial in self.successful_trials(trials):
            if trial.metric_value is None:
                continue

            reward = self.metric_reward(trial.metric_value)

            for name, value in trial.config.items():
                key = (name, stable_json(value))
                grouped.setdefault(key, []).append(reward)

        return {
            key: (len(values), statistics.fmean(values))
            for key, values in grouped.items()
        }

    def model_score(self, config: dict[str, Any], trials: list[Trial]) -> float:
        rewards = self.parameter_value_rewards(trials)
        total = max(len(self.successful_trials(trials)), 1)
        ucb_weight = float(self.grid.policy.get("ucb_weight", 0.75))
        scores: list[float] = []

        for name in self.grid.active_parameter_names(config):
            key = (name, stable_json(config.get(name)))
            count, mean = rewards.get(key, (0, 0.0))
            bonus = ucb_weight * math.sqrt(math.log(total + 2.0) / (count + 1.0))
            scores.append(mean + bonus)

        return statistics.fmean(scores) if scores else 0.0

    def ucb_config(self, trials: list[Trial]) -> tuple[dict[str, Any], str]:
        pool_size = int(self.grid.policy.get("candidate_pool_size", 256))
        tried = self.tried_config_ids(trials)
        candidates: list[dict[str, Any]] = []
        attempts = max(pool_size * 4, 64)

        for _ in range(attempts):
            candidate = self.random_config()
            if config_id(candidate) not in tried:
                candidates.append(candidate)
            if len(candidates) >= pool_size:
                break

        if not candidates:
            candidates = [self.random_config() for _ in range(pool_size)]

        return max(candidates, key=lambda item: self.model_score(item, trials)), "ucb"

    def best_trial(self, trials: list[Trial]) -> Trial | None:
        successful = self.successful_trials(trials)

        if not successful:
            return None

        reverse = self.grid.metric_direction == "maximize"
        return sorted(
            successful, key=lambda item: item.metric_value or 0.0, reverse=reverse
        )[0]

    def adjacent_values(self, name: str, current_value: Any) -> list[Any]:
        values = self.grid.values_for(name)

        if current_value not in values:
            return values[:1]

        index = values.index(current_value)
        output: list[Any] = []

        if index > 0:
            output.append(values[index - 1])
        if index + 1 < len(values):
            output.append(values[index + 1])

        return output

    def neighbor_configs(self, center: dict[str, Any]) -> list[dict[str, Any]]:
        normalized = self.grid.normalize_config(center)
        neighbors: dict[str, dict[str, Any]] = {}

        for name in self.grid.active_parameter_names(normalized):
            current = normalized.get(name)

            for value in self.adjacent_values(name, current):
                candidate = dict(normalized)
                candidate[name] = value
                candidate = self.grid.strip_inactive(candidate)

                if self.grid.is_valid_config(candidate):
                    neighbors[config_id(candidate)] = candidate

        return list(neighbors.values())

    def neighbor_config(self, trials: list[Trial]) -> tuple[dict[str, Any], str]:
        best = self.best_trial(trials)

        if best is None:
            return self.coverage_config(trials)

        tried = self.tried_config_ids(trials)
        neighbors = self.neighbor_configs(best.config)
        untried = [item for item in neighbors if config_id(item) not in tried]

        if untried:
            return (
                max(untried, key=lambda item: self.model_score(item, trials)),
                "neighbor",
            )

        return self.ucb_config(trials)

    def choose(
        self,
        group_key: str | None,
        group_value: str | None,
        group_mode: GroupMode,
        selection_mode: SelectionMode,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        trials, scope = self.scoped_trials(group_key, group_value, group_mode)
        trial_count = len(self.active_trials(trials))
        warmup_trials = int(self.grid.policy.get("warmup_trials", 40))
        epsilon = self.epsilon(trial_count)

        if selection_mode == "random":
            config = self.random_config()
            reason = "random"
        elif selection_mode == "coverage":
            config, reason = self.coverage_config(trials)
        elif selection_mode == "ucb":
            config, reason = self.ucb_config(trials)
        elif selection_mode == "neighbor":
            config, reason = self.neighbor_config(trials)
        else:
            if trial_count < warmup_trials:
                config, reason = self.coverage_config(trials)
                reason = "warmup-" + reason
            elif self.rng.random() < epsilon:
                config, reason = self.coverage_config(trials)
                reason = "epsilon-" + reason
            else:
                roll = self.rng.random()
                neighbor_p = float(
                    self.grid.policy.get("neighbor_probability_after_warmup", 0.55)
                )
                ucb_p = float(
                    self.grid.policy.get("ucb_probability_after_warmup", 0.30)
                )

                if roll < neighbor_p:
                    config, reason = self.neighbor_config(trials)
                elif roll < neighbor_p + ucb_p:
                    config, reason = self.ucb_config(trials)
                else:
                    config, reason = self.coverage_config(trials)

        metadata = {
            "selection_reason": reason,
            "selection_scope": scope,
            "epsilon": epsilon,
            "scoped_trial_count": trial_count,
            "group_mode": group_mode,
            "group_key": group_key,
            "group_value": normalize_group_value(group_value),
            "metric_name": self.grid.metric_name,
            "metric_direction": self.grid.metric_direction,
        }

        return config, metadata


def trial_to_payload(trial: Trial) -> dict[str, Any]:
    return {
        "trial_id": trial.trial_id,
        "experiment_name": trial.experiment_name,
        "config_id": trial.config_id,
        "config": trial.config,
        "status": trial.status,
        "metric_name": trial.metric_name,
        "metric_value": trial.metric_value,
        "group_key": trial.group_key,
        "group_value": trial.group_value,
        "selection_reason": trial.selection_reason,
        "created_at_unix": trial.created_at_unix,
        "completed_at_unix": trial.completed_at_unix,
        "metadata": trial.metadata,
    }


def initialize_experiment(
    database: str | Path, grid_path: str | Path, experiment: str
) -> None:
    grid = read_json_file(grid_path)
    store = AdaptiveGridStore(database)
    store.upsert_experiment(experiment, grid)


def create_next_trial(
    database: str | Path,
    experiment: str,
    output: str | Path | None,
    group_key: str | None,
    group_value: str | None,
    group_mode: GroupMode,
    selection_mode: SelectionMode,
    metadata: dict[str, Any],
    seed: int | None,
) -> dict[str, Any]:
    store = AdaptiveGridStore(database)
    grid_payload = store.read_experiment_grid(experiment)
    grid = GridSpec(grid_payload)

    ttl_seconds = float(
        grid.policy.get(
            "planned_trial_ttl_seconds", DEFAULT_POLICY["planned_trial_ttl_seconds"]
        )
    )
    expired_count = store.expire_stale_planned_trials(experiment, ttl_seconds)

    trials = store.load_trials(experiment)
    optimizer = AdaptiveGridOptimizer(grid, trials, seed=seed)
    config, selection_metadata = optimizer.choose(
        group_key=group_key,
        group_value=group_value,
        group_mode=group_mode,
        selection_mode=selection_mode,
    )

    merged_metadata = dict(selection_metadata)
    merged_metadata.update(metadata)

    trial = store.create_planned_trial(
        experiment_name=experiment,
        metric_name=grid.metric_name,
        config=config,
        group_key=group_key,
        group_value=group_value,
        selection_reason=str(selection_metadata["selection_reason"]),
        metadata=merged_metadata,
    )

    payload = trial_to_payload(trial)
    payload["expired_stale_planned_trials"] = expired_count

    if output is not None:
        write_json_file(output, payload)

    return payload


def record_trial_result(
    database: str | Path,
    trial_id: str,
    status: str,
    metric_value: float | None,
    metadata: dict[str, Any],
) -> None:
    if status == "ok" and metric_value is None:
        raise RuntimeError("metric_value is required when status is ok")

    store = AdaptiveGridStore(database)
    store.record_result(
        trial_id=trial_id,
        status=status,
        metric_value=metric_value,
        metadata_update=metadata,
    )


def export_trials(database: str | Path, experiment: str, output: str | Path) -> int:
    store = AdaptiveGridStore(database)
    trials = store.load_trials(experiment)
    resolved = Path(output).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)

    with resolved.open("w", encoding="utf-8") as handle:
        for trial in trials:
            handle.write(
                json.dumps(trial_to_payload(trial), sort_keys=True, ensure_ascii=False)
                + "\n"
            )

    return len(trials)


def summarize_trials(
    database: str | Path, experiment: str, limit: int
) -> dict[str, Any]:
    store = AdaptiveGridStore(database)
    grid = GridSpec(store.read_experiment_grid(experiment))
    trials = store.load_trials(experiment)

    successful = [
        trial
        for trial in trials
        if trial.status == "ok" and trial.metric_value is not None
    ]
    grouped: dict[str, list[Trial]] = {}

    for trial in successful:
        grouped.setdefault(trial.config_id, []).append(trial)

    rows: list[dict[str, Any]] = []
    for cid, config_trials in grouped.items():
        values = [
            float(trial.metric_value)
            for trial in config_trials
            if trial.metric_value is not None
        ]
        if not values:
            continue

        rows.append(
            {
                "config_id": cid,
                "count": len(values),
                "mean": statistics.fmean(values),
                "median": statistics.median(values),
                "best": (
                    max(values) if grid.metric_direction == "maximize" else min(values)
                ),
                "config": config_trials[0].config,
            }
        )

    reverse = grid.metric_direction == "maximize"
    rows.sort(key=lambda item: item["mean"], reverse=reverse)

    return {
        "experiment_name": experiment,
        "metric_name": grid.metric_name,
        "metric_direction": grid.metric_direction,
        "trial_count": len(trials),
        "successful_trial_count": len(successful),
        "top": rows[:limit],
    }
