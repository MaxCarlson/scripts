"""Deterministic temporal sampling window generator for empirical trial encoding."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SampleWindow:
    """Represents a bounded temporal extraction interval within a video asset."""

    window_index: int
    start_seconds: float
    duration_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_index": self.window_index,
            "start_seconds": round(self.start_seconds, 3),
            "duration_seconds": round(self.duration_seconds, 3),
        }


SCHEDULE_COUNTS: dict[str, int] = {
    "s3": 3,
    "s5": 5,
    "s8": 8,
}


def generate_sample_windows(
    duration_seconds: float,
    schedule: str = "s3",
    window_duration_seconds: float = 10.0,
) -> list[SampleWindow]:
    """Generate deterministically spaced temporal windows across playable duration.

    Args:
        duration_seconds: Total duration of the video asset in seconds.
        schedule: Sampling schedule identifier ('s3', 's5', 's8').
        window_duration_seconds: Nominal target duration per clip in seconds.

    Returns:
        List of SampleWindow objects with non-overlapping, in-bounds intervals.
    """
    if duration_seconds <= 0.0 or window_duration_seconds <= 0.0:
        return []

    norm_sched = schedule.strip().lower()
    if norm_sched not in SCHEDULE_COUNTS:
        raise ValueError(
            f"Unknown sampling schedule '{schedule}'. Supported schedules: {list(SCHEDULE_COUNTS.keys())}"
        )

    target_count = SCHEDULE_COUNTS[norm_sched]

    # If the video is shorter than or equal to one window, take the whole clip as 1 sample
    if duration_seconds <= window_duration_seconds:
        return [
            SampleWindow(
                window_index=0,
                start_seconds=0.0,
                duration_seconds=duration_seconds,
            )
        ]

    # If duration cannot accommodate target_count * window_duration_seconds,
    # scale the window duration or count so windows fit without overlapping
    max_total_window_time = duration_seconds * 0.90
    actual_window_dur = min(window_duration_seconds, max_total_window_time / target_count)
    actual_window_dur = max(1.0, actual_window_dur)  # minimum 1 second per window

    # Calculate usable span for window starts
    # We want to distribute centers or start points across the duration
    # Centers at (i + 0.5) / target_count
    windows: list[SampleWindow] = []
    for i in range(target_count):
        center_fraction = (i + 0.5) / target_count
        center_time = duration_seconds * center_fraction
        start_time = max(0.0, center_time - (actual_window_dur / 2.0))
        # Ensure it fits within bounds
        if start_time + actual_window_dur > duration_seconds:
            start_time = max(0.0, duration_seconds - actual_window_dur)

        # Enforce non-overlap with previous window
        if windows and start_time < (windows[-1].start_seconds + windows[-1].duration_seconds):
            start_time = windows[-1].start_seconds + windows[-1].duration_seconds

        # Check remaining time
        dur = min(actual_window_dur, max(0.0, duration_seconds - start_time))
        if dur <= 0.0:
            break

        windows.append(
            SampleWindow(
                window_index=len(windows),
                start_seconds=round(start_time, 3),
                duration_seconds=round(dur, 3),
            )
        )

    return windows
