from __future__ import annotations

import pytest

from vdedup.gpu_sampling import PROFILES, is_edge_timestamp, select_frame_timestamps


def test_sampling_is_deterministic():
    first = select_frame_timestamps(3600.0, profile="balanced")
    second = select_frame_timestamps(3600.0, profile="balanced")

    assert first == second


def test_sampling_respects_profile_caps():
    for profile, config in PROFILES.items():
        timestamps = select_frame_timestamps(7200.0, profile=profile)
        assert len(timestamps) <= config["target_frames"]


def test_short_video_samples_every_second_without_edges():
    timestamps = select_frame_timestamps(10.0, profile="balanced")

    assert timestamps[:3] == [0.0, 1.0, 2.0]
    assert is_edge_timestamp(timestamps[0], 10.0) is False


def test_medium_video_uses_two_second_steps_and_avoids_edges():
    timestamps = select_frame_timestamps(120.0, profile="balanced")

    assert timestamps[0] >= 3.0
    assert timestamps[1] - timestamps[0] == 2.0
    assert timestamps[-1] <= 117.0


def test_long_video_uniform_sampling_hits_profile_target():
    timestamps = select_frame_timestamps(3600.0, profile="fast")

    assert len(timestamps) == PROFILES["fast"]["target_frames"]
    assert timestamps == sorted(timestamps)
    assert timestamps[0] == 3.0
    assert timestamps[-1] == 3597.0


def test_edge_timestamp_detection_for_long_videos():
    assert is_edge_timestamp(2.9, 120.0) is True
    assert is_edge_timestamp(117.1, 120.0) is True
    assert is_edge_timestamp(60.0, 120.0) is False


def test_invalid_profile_raises():
    with pytest.raises(ValueError, match="Invalid GPU sampling profile"):
        select_frame_timestamps(120.0, profile="ultra")
