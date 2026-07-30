import json
from pathlib import Path

import pytest

from mangadl.optimizer import (
    AdaptiveStateSelector,
    OptimizationState,
    OptimizationTrial,
    generate_optimization_states,
    run_online_optimization,
)


def _trial(index: int, state: OptimizationState, bps: float) -> OptimizationTrial:
    return OptimizationTrial(
        index=index,
        state=state,
        reason="test",
        evaluation="timed",
        bytes_downloaded=int(bps),
        images_downloaded=1,
        elapsed=1.0,
        bytes_per_second=bps,
        errors=0,
    )


def test_generate_optimization_states_respects_bounds_series_and_cpu_budget() -> None:
    states = generate_optimization_states(
        1,
        8,
        1,
        8,
        logical_cpus=8,
        available_series=4,
    )

    assert states
    assert all(1 <= state.workers <= 4 for state in states)
    assert all(1 <= state.image_workers <= 8 for state in states)
    assert all(state.aggregate <= 7 for state in states)
    assert OptimizationState(4, 2) not in states
    assert OptimizationState(3, 2) in states


def test_adaptive_selector_exploration_decays_and_prefers_lower_near_tie() -> None:
    states = (
        OptimizationState(1, 1),
        OptimizationState(1, 2),
        OptimizationState(2, 1),
        OptimizationState(2, 2),
    )
    selector = AdaptiveStateSelector(states, seed=7, epsilon_decay_trials=2.0)
    initial_epsilon = selector.epsilon()

    selector.record(_trial(1, states[0], 100.0))
    selector.record(_trial(2, states[1], 198.0))
    selector.record(_trial(3, states[2], 200.0))
    selector.record(_trial(4, states[3], 150.0))

    assert selector.epsilon() < initial_epsilon
    assert selector.best_state() == states[1]
    assert 0.0 < selector.convergence() <= 1.0


def test_online_optimizer_persists_matrix_and_selects_best_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "downloads"
    destination.mkdir()
    report = tmp_path / "optimizer.json"

    def fake_benchmark(state, _urls, _destination, **_kwargs):
        score = {
            (1, 1): 100,
            (1, 2): 200,
            (2, 1): 300,
            (2, 2): 500,
        }[(state.workers, state.image_workers)]
        return score * 10, 10, 10.0, 0

    monkeypatch.setattr("mangadl.optimizer.benchmark_online_state", fake_benchmark)

    result = run_online_optimization(
        ["https://manga18fx.com/manga/one/", "https://manga18fx.com/manga/two/"],
        destination,
        report,
        minimum_workers=1,
        maximum_workers=2,
        minimum_image_workers=1,
        maximum_image_workers=2,
        evaluation="timed",
        strategy="adaptive",
        planned_trials=8,
        trial_seconds=1.0,
        cookies=None,
        worker_start_delay=0.0,
        logical_cpus=8,
        seed=3,
    )

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert result.selected_workers == 2
    assert result.selected_image_workers == 2
    assert payload["status"] == "complete"
    assert payload["state_count"] == 4
    assert payload["tried_state_count"] == 4
    assert payload["selected"]["workers"] == 2
    assert payload["selected"]["image_workers"] == 2
