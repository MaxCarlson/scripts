from __future__ import annotations

import os
from dataclasses import dataclass

MAX_OUTER_WORKERS_ENV = "MANGADL_MAX_OUTER_WORKERS"
DEFAULT_MAX_OUTER_WORKERS = 4
HARD_MAX_OUTER_WORKERS = 8
# Backward-compatible exported name used by the manager.
MAX_OUTER_WORKERS = HARD_MAX_OUTER_WORKERS


@dataclass(frozen=True, slots=True)
class Manga18FXConcurrencyPlan:
    requested_workers: int
    requested_image_workers: int
    effective_workers: int
    effective_image_workers: int
    logical_cpus: int
    budget: int
    maximum_workers: int

    @property
    def requested_total(self) -> int:
        return self.requested_workers * self.requested_image_workers

    @property
    def effective_total(self) -> int:
        return self.effective_workers * self.effective_image_workers

    @property
    def adjusted(self) -> bool:
        return (
            self.requested_workers != self.effective_workers
            or self.requested_image_workers != self.effective_image_workers
        )


def configured_maximum_workers(value: int | None = None) -> int:
    """Resolve the safe outer-worker ceiling, allowing an explicit override to eight."""
    if value is None:
        raw = os.environ.get(MAX_OUTER_WORKERS_ENV, str(DEFAULT_MAX_OUTER_WORKERS))
        try:
            value = int(raw)
        except ValueError:
            value = DEFAULT_MAX_OUTER_WORKERS
    if not 1 <= value <= HARD_MAX_OUTER_WORKERS:
        raise ValueError(
            f"maximum outer workers must be between 1 and {HARD_MAX_OUTER_WORKERS}"
        )
    return value


def plan_manga18fx_concurrency(
    workers: int,
    image_workers: int,
    *,
    logical_cpus: int | None = None,
    maximum_workers: int | None = None,
) -> Manga18FXConcurrencyPlan:
    """Bound outer workers and aggregate Manga18FX concurrency conservatively."""
    if workers < 1:
        raise ValueError("workers must be at least 1")
    if image_workers < 1:
        raise ValueError("image_workers must be at least 1")

    maximum = configured_maximum_workers(maximum_workers)
    detected = logical_cpus if logical_cpus is not None else os.cpu_count()
    logical = max(1, int(detected or 1))
    budget = max(1, logical - 1)

    effective_workers = min(workers, maximum, budget)
    effective_image_workers = min(image_workers, max(1, budget // effective_workers))

    return Manga18FXConcurrencyPlan(
        requested_workers=workers,
        requested_image_workers=image_workers,
        effective_workers=effective_workers,
        effective_image_workers=effective_image_workers,
        logical_cpus=logical,
        budget=budget,
        maximum_workers=maximum,
    )
