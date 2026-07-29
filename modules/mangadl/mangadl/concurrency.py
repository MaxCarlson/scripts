from __future__ import annotations

import os
from dataclasses import dataclass

MAX_OUTER_WORKERS = 8


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


def plan_manga18fx_concurrency(
    workers: int,
    image_workers: int,
    *,
    logical_cpus: int | None = None,
    maximum_workers: int = MAX_OUTER_WORKERS,
) -> Manga18FXConcurrencyPlan:
    """Bound aggregate Manga18FX concurrency below the logical CPU count."""
    if workers < 1:
        raise ValueError("workers must be at least 1")
    if image_workers < 1:
        raise ValueError("image_workers must be at least 1")
    if maximum_workers < 1:
        raise ValueError("maximum_workers must be at least 1")

    detected = logical_cpus if logical_cpus is not None else os.cpu_count()
    logical = max(1, int(detected or 1))
    budget = max(1, logical - 1)

    effective_workers = min(workers, maximum_workers, budget)
    effective_image_workers = min(image_workers, max(1, budget // effective_workers))

    return Manga18FXConcurrencyPlan(
        requested_workers=workers,
        requested_image_workers=image_workers,
        effective_workers=effective_workers,
        effective_image_workers=effective_image_workers,
        logical_cpus=logical,
        budget=budget,
        maximum_workers=maximum_workers,
    )
