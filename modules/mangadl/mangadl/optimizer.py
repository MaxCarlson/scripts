from __future__ import annotations

import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Literal

from termdash import utils as td_utils

from .ui import human_bytes

EvaluationMode = Literal["complete", "timed"]
SearchStrategy = Literal["adaptive", "grid"]
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp"}


@dataclass(frozen=True, slots=True, order=True)
class OptimizationState:
    workers: int
    image_workers: int

    @property
    def aggregate(self) -> int:
        return self.workers * self.image_workers


@dataclass(frozen=True, slots=True)
class OptimizationTrial:
    index: int
    state: OptimizationState
    reason: str
    evaluation: EvaluationMode
    bytes_downloaded: int
    images_downloaded: int
    elapsed: float
    bytes_per_second: float
    errors: int


@dataclass(frozen=True, slots=True)
class OptimizationStatus:
    strategy: SearchStrategy
    evaluation: EvaluationMode
    total_states: int
    tried_states: int
    completed_trials: int
    planned_trials: int
    current_state: OptimizationState | None
    current_reason: str
    best_state: OptimizationState | None
    best_bps: float
    exploration: float
    convergence: float
    current_elapsed: float
    current_bytes: int
    current_bps: float
    active_workers: int
    logical_cpus: int
    budget: int


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    selected_workers: int
    selected_image_workers: int
    logical_cpus: int
    budget: int
    elapsed: float
    states: tuple[OptimizationState, ...]
    trials: tuple[OptimizationTrial, ...]
    report_path: Path


ProgressCallback = Callable[[OptimizationStatus], None]
StopCallback = Callable[[], bool]


def generate_optimization_states(
    minimum_workers: int,
    maximum_workers: int,
    minimum_image_workers: int,
    maximum_image_workers: int,
    *,
    logical_cpus: int,
    available_series: int,
) -> tuple[OptimizationState, ...]:
    if minimum_workers < 1 or maximum_workers < minimum_workers:
        raise ValueError("require 1 <= minimum_workers <= maximum_workers")
    if minimum_image_workers < 1 or maximum_image_workers < minimum_image_workers:
        raise ValueError("require 1 <= minimum_image_workers <= maximum_image_workers")
    if available_series < 1:
        return ()

    budget = max(1, int(logical_cpus) - 1)
    states = {
        OptimizationState(workers, image_workers)
        for workers in range(minimum_workers, min(maximum_workers, available_series) + 1)
        for image_workers in range(minimum_image_workers, maximum_image_workers + 1)
        if workers * image_workers <= budget
    }
    return tuple(
        sorted(
            states,
            key=lambda state: (state.aggregate, state.workers, state.image_workers),
        )
    )


class AdaptiveStateSelector:
    def __init__(
        self,
        states: tuple[OptimizationState, ...],
        *,
        seed: int | None = None,
        epsilon_start: float = 0.35,
        epsilon_floor: float = 0.05,
        epsilon_decay_trials: float = 18.0,
    ) -> None:
        if not states:
            raise ValueError("optimizer state space is empty")
        if not 0 <= epsilon_floor <= epsilon_start <= 1:
            raise ValueError("require 0 <= epsilon_floor <= epsilon_start <= 1")
        self.states = states
        self.rng = random.Random(seed)
        self.epsilon_start = epsilon_start
        self.epsilon_floor = epsilon_floor
        self.epsilon_decay_trials = max(1.0, epsilon_decay_trials)
        self.trials: list[OptimizationTrial] = []

    def epsilon(self) -> float:
        return self.epsilon_floor + (
            self.epsilon_start - self.epsilon_floor
        ) * math.exp(-len(self.trials) / self.epsilon_decay_trials)

    def grouped(self) -> dict[OptimizationState, list[OptimizationTrial]]:
        grouped: dict[OptimizationState, list[OptimizationTrial]] = {}
        for trial in self.trials:
            if trial.bytes_per_second > 0:
                grouped.setdefault(trial.state, []).append(trial)
        return grouped

    def tried_states(self) -> set[OptimizationState]:
        return {trial.state for trial in self.trials}

    def average_bps(self, state: OptimizationState) -> float:
        values = [
            trial.bytes_per_second
            for trial in self.grouped().get(state, ())
        ]
        return sum(values) / len(values) if values else 0.0

    def best_state(self) -> OptimizationState | None:
        grouped = self.grouped()
        if not grouped:
            return None
        peak = max(self.average_bps(state) for state in grouped)
        near_peak = [
            state
            for state in grouped
            if self.average_bps(state) >= peak * 0.98
        ]
        return min(
            near_peak,
            key=lambda state: (
                state.aggregate,
                state.workers,
                -self.average_bps(state),
            ),
        )

    def convergence(self) -> float:
        if not self.trials:
            return 0.0
        coverage = len(self.tried_states()) / len(self.states)
        exploitation = 1.0 - self.epsilon()
        repeat_factor = min(
            1.0,
            len(self.trials) / max(4.0, math.sqrt(len(self.states)) * 2.0),
        )
        return max(
            0.0,
            min(1.0, (coverage * 0.45 + exploitation * 0.55) * repeat_factor),
        )

    def neighbors(self, center: OptimizationState) -> tuple[OptimizationState, ...]:
        return tuple(
            state
            for state in self.states
            if abs(state.workers - center.workers)
            + abs(state.image_workers - center.image_workers)
            == 1
        )

    def _coverage_state(self) -> OptimizationState:
        untried = [
            state for state in self.states if state not in self.tried_states()
        ]
        if untried:
            return min(
                untried,
                key=lambda state: (
                    state.aggregate,
                    state.workers,
                    state.image_workers,
                ),
            )
        grouped = self.grouped()
        return min(
            self.states,
            key=lambda state: (
                len(grouped.get(state, ())),
                state.aggregate,
                state.workers,
            ),
        )

    def _exploration_state(
        self,
        best: OptimizationState | None,
    ) -> OptimizationState:
        untried = [
            state for state in self.states if state not in self.tried_states()
        ]
        if not untried:
            return self.rng.choice(self.states)
        if best is None:
            return self.rng.choice(untried)
        return max(
            untried,
            key=lambda state: (
                abs(state.workers - best.workers)
                + abs(state.image_workers - best.image_workers),
                -state.aggregate,
                -state.workers,
            ),
        )

    def _model_score(self, state: OptimizationState) -> float:
        related = [
            trial.bytes_per_second
            for trial_state, trials in self.grouped().items()
            if trial_state.workers == state.workers
            or trial_state.image_workers == state.image_workers
            for trial in trials
        ]
        return sum(related) / len(related) if related else 0.0

    def _ucb_state(self) -> OptimizationState:
        grouped = self.grouped()
        successful = sum(len(values) for values in grouped.values())
        peak = max(
            (self.average_bps(state) for state in grouped),
            default=1.0,
        )

        def score(state: OptimizationState) -> float:
            values = grouped.get(state, ())
            if not values:
                return float("inf")
            bonus = peak * 0.20 * math.sqrt(
                math.log(successful + 2.0) / len(values)
            )
            return self.average_bps(state) + bonus

        return max(self.states, key=score)

    def choose(self) -> tuple[OptimizationState, str]:
        warmup = min(
            len(self.states),
            max(4, math.ceil(math.sqrt(len(self.states)) * 2)),
        )
        if len(self.trials) < warmup:
            return self._coverage_state(), "warmup-coverage"

        best = self.best_state()
        if self.rng.random() < self.epsilon():
            return self._exploration_state(best), "epsilon-exploration"

        if best is not None:
            untried_neighbors = [
                state
                for state in self.neighbors(best)
                if state not in self.tried_states()
            ]
            if untried_neighbors:
                return (
                    max(untried_neighbors, key=self._model_score),
                    "best-neighbor",
                )

        return self._ucb_state(), "ucb-exploitation"

    def record(self, trial: OptimizationTrial) -> None:
        self.trials.append(trial)


def _tree_stats(root: Path) -> tuple[int, int]:
    images = 0
    size = 0
    if not root.exists():
        return images, size
    for path in root.rglob("*"):
        try:
            if (
                not path.is_file()
                or "_logs" in path.parts
                or path.name.endswith(".tmp")
            ):
                continue
            size += path.stat().st_size
            if (
                not path.name.endswith(".part")
                and path.suffix.lower() in IMAGE_SUFFIXES
            ):
                images += 1
        except OSError:
            continue
    return images, size


def _terminate_processes(processes: list[subprocess.Popen[str]]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 5.0
    for process in processes:
        if process.poll() is not None:
            continue
        remaining = deadline - time.monotonic()
        if remaining > 0:
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                pass
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def benchmark_online_state(
    state: OptimizationState,
    urls: tuple[str, ...],
    destination: Path,
    *,
    evaluation: EvaluationMode,
    trial_seconds: float,
    cookies: Path | None,
    worker_start_delay: float,
    progress: Callable[[float, int, float, int], None] | None = None,
    stop_requested: StopCallback | None = None,
) -> tuple[int, int, float, int]:
    if evaluation == "timed" and trial_seconds <= 0:
        raise ValueError("timed optimization requires trial_seconds greater than zero")
    if worker_start_delay < 0:
        raise ValueError("worker_start_delay must be zero or greater")

    destination.mkdir(parents=True, exist_ok=True)
    logs = destination / "_logs"
    logs.mkdir(parents=True, exist_ok=True)
    processes: list[subprocess.Popen[str]] = []
    handles: list[object] = []
    started = time.monotonic()
    deadline = started + trial_seconds if evaluation == "timed" else None

    try:
        for index, url in enumerate(urls[: state.workers], start=1):
            if index > 1 and worker_start_delay > 0:
                target = time.monotonic() + worker_start_delay
                while time.monotonic() < target:
                    if stop_requested and stop_requested():
                        raise KeyboardInterrupt
                    if deadline is not None and time.monotonic() >= deadline:
                        break
                    time.sleep(0.05)
            if deadline is not None and time.monotonic() >= deadline:
                break

            log_handle = (
                logs / f"worker-{index:02d}.log"
            ).open("w", encoding="utf-8", errors="replace")
            handles.append(log_handle)
            command = [
                sys.executable,
                "-m",
                "mangadl.manga18fx",
                "--destination",
                str(destination / f"series-{index:02d}"),
                "--image-workers",
                str(state.image_workers),
            ]
            if cookies is not None:
                command.extend(["--cookies", str(cookies)])
            command.append(url)
            processes.append(
                subprocess.Popen(
                    command,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=(
                        subprocess.CREATE_NEW_PROCESS_GROUP
                        if os.name == "nt"
                        else 0
                    ),
                )
            )

        previous_time = started
        previous_size = 0
        while processes and any(
            process.poll() is None for process in processes
        ):
            now = time.monotonic()
            if stop_requested and stop_requested():
                raise KeyboardInterrupt
            if deadline is not None and now >= deadline:
                break
            images, size = _tree_stats(destination)
            delta = max(now - previous_time, 0.001)
            current_bps = max(0.0, (size - previous_size) / delta)
            if progress:
                progress(
                    now - started,
                    size,
                    current_bps,
                    sum(process.poll() is None for process in processes),
                )
            previous_time = now
            previous_size = size
            time.sleep(0.25)
    finally:
        if evaluation == "timed" or any(
            process.poll() is None for process in processes
        ):
            _terminate_processes(processes)
        for handle in handles:
            handle.close()  # type: ignore[attr-defined]

    elapsed = max(time.monotonic() - started, 0.001)
    images, size = _tree_stats(destination)
    errors = sum(
        1
        for process in processes
        if process.returncode not in {0, None} and evaluation == "complete"
    )
    return size, images, elapsed, errors


def _state_averages(
    trials: list[OptimizationTrial],
) -> dict[OptimizationState, float]:
    grouped: dict[OptimizationState, list[float]] = {}
    for trial in trials:
        if trial.bytes_per_second > 0:
            grouped.setdefault(trial.state, []).append(trial.bytes_per_second)
    return {
        state: sum(values) / len(values)
        for state, values in grouped.items()
    }


def select_best_state(
    trials: list[OptimizationTrial],
) -> OptimizationState:
    averages = _state_averages(trials)
    if not averages:
        raise RuntimeError("optimization produced no successful throughput samples")
    peak = max(averages.values())
    near_peak = [
        state
        for state, value in averages.items()
        if value >= peak * 0.98
    ]
    return min(
        near_peak,
        key=lambda state: (
            state.aggregate,
            state.workers,
            -averages[state],
        ),
    )


def _write_report(
    path: Path,
    *,
    status: str,
    strategy: SearchStrategy,
    evaluation: EvaluationMode,
    logical_cpus: int,
    budget: int,
    states: tuple[OptimizationState, ...],
    trials: list[OptimizationTrial],
    selected: OptimizationState | None,
    elapsed: float,
) -> None:
    averages = _state_averages(trials)
    tried = {trial.state for trial in trials}
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "strategy": strategy,
        "evaluation": evaluation,
        "logical_cpus": logical_cpus,
        "budget": budget,
        "elapsed": elapsed,
        "state_count": len(states),
        "tried_state_count": len(tried),
        "states": [
            asdict(state) | {"aggregate": state.aggregate}
            for state in states
        ],
        "trials": [
            asdict(trial)
            | {
                "state": asdict(trial.state),
                "aggregate": trial.state.aggregate,
            }
            for trial in trials
        ],
        "state_averages": [
            {
                "workers": state.workers,
                "image_workers": state.image_workers,
                "aggregate": state.aggregate,
                "average_bps": average,
            }
            for state, average in sorted(
                averages.items(),
                key=lambda item: item[1],
                reverse=True,
            )
        ],
        "selected": (
            asdict(selected) | {"aggregate": selected.aggregate}
            if selected
            else None
        ),
    }
    path.write_text(
        json.dumps(payload, indent=4, sort_keys=True) + os.linesep,
        encoding="utf-8",
    )


def run_online_optimization(
    urls: list[str],
    destination: Path,
    report_path: Path,
    *,
    minimum_workers: int,
    maximum_workers: int,
    minimum_image_workers: int,
    maximum_image_workers: int,
    evaluation: EvaluationMode,
    strategy: SearchStrategy,
    planned_trials: int,
    trial_seconds: float,
    cookies: Path | None,
    worker_start_delay: float,
    logical_cpus: int | None = None,
    seed: int | None = None,
    progress: ProgressCallback | None = None,
    stop_requested: StopCallback | None = None,
) -> OptimizationResult:
    if planned_trials < 1:
        raise ValueError("planned_trials must be at least 1")
    if not urls:
        raise ValueError("optimization requires at least one Manga18FX URL")

    destination.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    logical = max(1, int(logical_cpus or os.cpu_count() or 1))
    budget = max(1, logical - 1)
    states = generate_optimization_states(
        minimum_workers,
        maximum_workers,
        minimum_image_workers,
        maximum_image_workers,
        logical_cpus=logical,
        available_series=len(urls),
    )
    if not states:
        raise ValueError("optimization bounds produced no valid states")

    selector = AdaptiveStateSelector(states, seed=seed)
    trials: list[OptimizationTrial] = []

    def emit(
        current_state: OptimizationState | None,
        reason: str,
        current_elapsed: float = 0.0,
        current_bytes: int = 0,
        current_bps: float = 0.0,
        active_workers: int = 0,
    ) -> None:
        if progress is None:
            return
        best = selector.best_state()
        progress(
            OptimizationStatus(
                strategy=strategy,
                evaluation=evaluation,
                total_states=len(states),
                tried_states=len(selector.tried_states()),
                completed_trials=len(trials),
                planned_trials=planned_trials,
                current_state=current_state,
                current_reason=reason,
                best_state=best,
                best_bps=selector.average_bps(best) if best else 0.0,
                exploration=(
                    selector.epsilon() if strategy == "adaptive" else 0.0
                ),
                convergence=(
                    selector.convergence()
                    if strategy == "adaptive"
                    else len(selector.tried_states()) / len(states)
                ),
                current_elapsed=current_elapsed,
                current_bytes=current_bytes,
                current_bps=current_bps,
                active_workers=active_workers,
                logical_cpus=logical,
                budget=budget,
            )
        )

    try:
        with tempfile.TemporaryDirectory(
            prefix=".mangadl-optimization-",
            dir=destination,
        ) as temporary:
            temporary_root = Path(temporary)
            for index in range(1, planned_trials + 1):
                if stop_requested and stop_requested():
                    raise KeyboardInterrupt

                if strategy == "grid":
                    round_index, position = divmod(index - 1, len(states))
                    ordered = states if round_index % 2 == 0 else tuple(reversed(states))
                    state = ordered[position]
                    reason = (
                        "grid-ascending"
                        if round_index % 2 == 0
                        else "grid-descending"
                    )
                else:
                    state, reason = selector.choose()

                rotation = (index - 1) % len(urls)
                rotated_urls = tuple(urls[rotation:] + urls[:rotation])
                trial_root = temporary_root / (
                    f"trial-{index:04d}-w{state.workers}-i{state.image_workers}"
                )
                emit(state, reason)

                def candidate_progress(
                    elapsed: float,
                    size: int,
                    bps: float,
                    active: int,
                ) -> None:
                    emit(state, reason, elapsed, size, bps, active)

                size, images, elapsed, errors = benchmark_online_state(
                    state,
                    rotated_urls,
                    trial_root,
                    evaluation=evaluation,
                    trial_seconds=trial_seconds,
                    cookies=cookies,
                    worker_start_delay=worker_start_delay,
                    progress=candidate_progress,
                    stop_requested=stop_requested,
                )
                trial = OptimizationTrial(
                    index=index,
                    state=state,
                    reason=reason,
                    evaluation=evaluation,
                    bytes_downloaded=size,
                    images_downloaded=images,
                    elapsed=elapsed,
                    bytes_per_second=size / max(elapsed, 0.001),
                    errors=errors,
                )
                trials.append(trial)
                selector.record(trial)
                shutil.rmtree(trial_root, ignore_errors=True)
                _write_report(
                    report_path,
                    status="running",
                    strategy=strategy,
                    evaluation=evaluation,
                    logical_cpus=logical,
                    budget=budget,
                    states=states,
                    trials=trials,
                    selected=selector.best_state(),
                    elapsed=time.monotonic() - started,
                )
                emit(None, "trial-complete")
    except BaseException:
        _write_report(
            report_path,
            status="interrupted",
            strategy=strategy,
            evaluation=evaluation,
            logical_cpus=logical,
            budget=budget,
            states=states,
            trials=trials,
            selected=selector.best_state(),
            elapsed=time.monotonic() - started,
        )
        raise

    selected = select_best_state(trials)
    elapsed = time.monotonic() - started
    _write_report(
        report_path,
        status="complete",
        strategy=strategy,
        evaluation=evaluation,
        logical_cpus=logical,
        budget=budget,
        states=states,
        trials=trials,
        selected=selected,
        elapsed=elapsed,
    )
    emit(None, "complete")
    return OptimizationResult(
        selected_workers=selected.workers,
        selected_image_workers=selected.image_workers,
        logical_cpus=logical,
        budget=budget,
        elapsed=elapsed,
        states=states,
        trials=tuple(trials),
        report_path=report_path,
    )


class OptimizationDashboard:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.stop = False
        self.latest: OptimizationStatus | None = None

    def request_stop(self) -> bool:
        self._poll_keyboard()
        return self.stop

    def _poll_keyboard(self) -> None:
        if not self.enabled or not sys.stdin.isatty():
            return
        if os.name == "nt":
            import msvcrt

            while msvcrt.kbhit():
                if msvcrt.getwch().lower() == "q":
                    self.stop = True

    def update(self, status: OptimizationStatus) -> None:
        self.latest = status
        self._poll_keyboard()
        if not self.enabled:
            return

        current = status.current_state
        best = status.best_state
        current_text = (
            f"w{current.workers}/i{current.image_workers}"
            if current
            else "--"
        )
        best_text = (
            f"w{best.workers}/i{best.image_workers}"
            if best
            else "--"
        )
        lines = [
            (
                f"{td_utils.color_text('mangadl', 'bright')} "
                f"{status.strategy} {status.evaluation} optimization"
            ),
            (
                f"States {status.tried_states}/{status.total_states} | "
                f"Trials {status.completed_trials}/{status.planned_trials} | "
                f"Convergence {status.convergence * 100:5.1f}% | "
                f"Explore {status.exploration * 100:4.1f}%"
            ),
            (
                f"Current {current_text} ({status.current_reason}) | "
                f"Best {best_text} {human_bytes(status.best_bps, '/s')} | "
                f"Budget {status.budget}/{status.logical_cpus}"
            ),
            (
                f"Trial {status.current_elapsed:6.1f}s | "
                f"Active {status.active_workers} | "
                f"{human_bytes(status.current_bytes)} | "
                f"{human_bytes(status.current_bps, '/s')}"
            ),
            "q Quit optimization safely",
        ]
        print(
            "\x1b[H\x1b[2J" + os.linesep.join(lines),
            end="",
            flush=True,
        )
