"""Deterministic task selection and filtering for benchmark datasets."""

from __future__ import annotations

import random
from typing import Sequence

from .schema import DatasetDescriptor


def select_tasks(
    descriptor: DatasetDescriptor,
    *,
    task_ids: Sequence[str] | None = None,
    language: str | None = None,
    count: int | None = None,
    seed: int | None = None,
) -> list[str]:
    """
    Select and order tasks deterministically.

    - Explicit task_ids are filtered and verified.
    - Language filters by language prefix.
    - Deterministic random sampling if seed and count are specified.
    - Returns sorted list if no seed is specified.
    """
    candidates = list(descriptor.all_tasks)
    if not task_ids and not language and descriptor.default_tasks:
        candidates = list(descriptor.default_tasks)

    # 1. Filter by language if specified
    if language:
        lang_norm = language.lower().strip()
        candidates = [
            task
            for task in candidates
            if task.startswith(f"polyglot_{lang_norm}_") or task.startswith(f"{lang_norm}/")
        ]
        if not candidates:
            raise ValueError(
                f"No tasks found for language {language!r} in dataset {descriptor.id}. "
                f"Supported: {list(descriptor.supported_languages)}"
            )

    # 2. Filter by explicit task IDs if provided
    if task_ids:
        selected: list[str] = []
        for tid in task_ids:
            clean_tid = tid.strip()
            # Match exact, normalized prefix, or suffix
            matches = [
                t
                for t in candidates
                if t == clean_tid
                or t == f"polyglot_{clean_tid.replace('/', '_')}"
                or t.endswith(f"_{clean_tid}")
                or t.endswith(f"/{clean_tid}")
            ]
            if not matches:
                raise ValueError(f"Task ID {tid!r} not found in dataset {descriptor.id}")
            selected.extend(matches)
        candidates = list(dict.fromkeys(selected))  # preserve order, drop duplicates

    # 3. Deterministic sampling or count limit
    if count is not None and count > 0:
        if count > len(candidates):
            count = len(candidates)
        if seed is not None:
            rng = random.Random(seed)
            # Use sample on deterministic sorted list
            sorted_candidates = sorted(candidates)
            candidates = sorted(rng.sample(sorted_candidates, count))
        else:
            candidates = sorted(candidates)[:count]
    elif seed is not None:
        rng = random.Random(seed)
        shuffled = list(sorted(candidates))
        rng.shuffle(shuffled)
        candidates = shuffled
    elif not task_ids:
        candidates = sorted(candidates)

    return candidates
