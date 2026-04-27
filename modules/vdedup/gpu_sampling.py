from __future__ import annotations

from typing import Dict, List


PROFILES: Dict[str, Dict[str, int]] = {
    "fast": {"target_frames": 24},
    "balanced": {"target_frames": 64},
    "thorough": {"target_frames": 128},
}


def _profile_target(profile: str) -> int:
    try:
        return int(PROFILES[profile]["target_frames"])
    except KeyError as exc:
        choices = ", ".join(sorted(PROFILES))
        raise ValueError(f"Invalid GPU sampling profile {profile!r}. Must be one of: {choices}.") from exc


def _cap_sorted_unique(values: List[float], target: int) -> List[float]:
    rounded = sorted({round(max(0.0, value), 3) for value in values})
    if len(rounded) <= target:
        return rounded
    if target <= 1:
        return rounded[:target]
    last = len(rounded) - 1
    indexes = sorted({round(i * last / (target - 1)) for i in range(target)})
    return [rounded[int(i)] for i in indexes]


def is_edge_timestamp(
    timestamp_seconds: float,
    duration_seconds: float,
    avoid_first_seconds: float = 3.0,
    avoid_last_seconds: float = 3.0,
) -> bool:
    if duration_seconds <= 60:
        return False
    return (
        timestamp_seconds < avoid_first_seconds
        or timestamp_seconds > max(0.0, duration_seconds - avoid_last_seconds)
    )


def select_frame_timestamps(
    duration_seconds: float,
    profile: str = "balanced",
    avoid_first_seconds: float = 3.0,
    avoid_last_seconds: float = 3.0,
) -> List[float]:
    """
    Return deterministic timestamp positions, in seconds, to sample for GPU signature extraction.

    Edge timestamps are intentionally still extractable; callers use is_edge_timestamp() to exclude
    them from matching when duration_seconds > 60.
    """
    target = _profile_target(profile)
    if duration_seconds <= 0 or target <= 0:
        return []

    duration = float(duration_seconds)
    if duration <= 60.0:
        timestamps = [float(i) for i in range(0, max(1, int(duration)) + 1)]
        if timestamps and timestamps[-1] >= duration:
            timestamps[-1] = max(0.0, duration - 0.001)
        return _cap_sorted_unique(timestamps, target)

    if duration <= 600.0:
        end = max(avoid_first_seconds, duration - avoid_last_seconds)
        timestamps = []
        current = avoid_first_seconds
        while current <= end:
            timestamps.append(current)
            current += 2.0
        return _cap_sorted_unique(timestamps, target)

    start = avoid_first_seconds
    end = max(start, duration - avoid_last_seconds)
    if target == 1:
        return [round((start + end) / 2.0, 3)]
    step = (end - start) / float(target - 1)
    return [round(start + (step * i), 3) for i in range(target)]
