from __future__ import annotations

import time
from pathlib import Path

import pytest

import mangadl.autotune as autotune
from mangadl.autotune import (
    ProbeImage,
    ProbeSeries,
    TuneCandidate,
    TuneRange,
    TuneSample,
    TuneScore,
    benchmark_candidate,
    generate_candidates,
    parse_tune_range,
    select_best_score,
)


def test_parse_tune_range_accepts_inclusive_bounds() -> None:
    assert parse_tune_range("2:6") == TuneRange(2, 6)


@pytest.mark.parametrize("value", ["", "4", "0:4", "5:2", "a:b"])
def test_parse_tune_range_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        parse_tune_range(value)


def test_generate_candidates_respects_bounds_series_and_cpu_budget() -> None:
    candidates = generate_candidates(
        TuneRange(1, 4),
        TuneRange(1, 8),
        logical_cpus=8,
        available_series=3,
    )

    assert candidates
    assert all(candidate.workers <= 3 for candidate in candidates)
    assert all(candidate.aggregate <= 7 for candidate in candidates)
    assert TuneCandidate(3, 2) in candidates
    assert TuneCandidate(3, 3) not in candidates


def test_select_best_prefers_lower_concurrency_within_two_percent() -> None:
    scores = (
        TuneScore(4, 4, 16, 1000.0, 1000.0, 0.0, 62.5, 2, 0),
        TuneScore(2, 4, 8, 990.0, 990.0, 0.0, 123.75, 2, 0),
        TuneScore(1, 4, 4, 800.0, 800.0, 0.0, 200.0, 2, 0),
    )

    selected = select_best_score(scores)

    assert (selected.workers, selected.image_workers) == (2, 4)


def test_benchmark_candidate_includes_stagger_in_elapsed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    starts: list[float] = []

    def fake_probe(*args: object, **kwargs: object) -> tuple[int, int, int]:
        del args, kwargs
        starts.append(time.monotonic())
        time.sleep(0.01)
        return 1024, 1, 0

    monkeypatch.setattr(autotune, "_benchmark_probe", fake_probe)
    probes = tuple(
        ProbeSeries(
            url=f"https://manga18fx.com/manga/example-{index}/",
            title=f"Example {index}",
            images=(ProbeImage(f"https://cdn.example/{index}.jpg", "https://manga18fx.com/"),),
        )
        for index in range(3)
    )

    sample = benchmark_candidate(
        TuneCandidate(3, 2),
        probes,
        tmp_path,
        seconds=1.0,
        cookies=None,
        timeout=1.0,
        round_number=1,
        worker_start_delay=0.03,
    )

    assert sample.images_downloaded == 3
    assert len(starts) == 3
    assert starts[1] - starts[0] >= 0.02
    assert starts[2] - starts[1] >= 0.02
    assert sample.elapsed >= 0.06


def test_score_samples_averages_each_combination() -> None:
    scores = autotune.score_samples(
        (
            TuneSample(1, 2, 4, 8, 1000, 1, 1.0, 1000.0, 0),
            TuneSample(2, 2, 4, 8, 2000, 2, 1.0, 2000.0, 0),
            TuneSample(1, 1, 4, 4, 500, 1, 1.0, 500.0, 0),
        )
    )

    score = next(item for item in scores if (item.workers, item.image_workers) == (2, 4))
    assert score.average_bps == 1500.0
    assert score.successful_samples == 2
