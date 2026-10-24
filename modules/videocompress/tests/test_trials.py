"""Tests for videocompress.trials SQLite persistence, quota scheduler, and sample aggregation."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from videocompress.adapters.ffmpeg import SampleEncodeResult
from videocompress.contracts import VideoAsset, VideoStream
from videocompress.recipes import get_recipe
from videocompress.sampling import SampleWindow
from videocompress.trials import (
    SamplePrediction,
    TrialRecord,
    TrialStore,
    aggregate_sample_estimate,
    run_sample_trials,
)
from videocompress.workspace import resolve_workspace


def test_trial_store_crud_and_idempotency(tmp_path: Path):
    """TrialStore must record, query, and avoid duplicate trials for unchanged stat fingerprints."""
    db_path = tmp_path / "trials.sqlite3"
    store = TrialStore(db_path)

    record = TrialRecord(
        trial_id="trial-abc-0",
        source_id="src-123",
        stat_fingerprint="1000:50000000",
        recipe_id="av1_nvenc_cq30",
        window_index=0,
        window_start=10.0,
        window_duration=10.0,
        actual_duration=10.02,
        sample_file_bytes=2_500_000,
        sample_video_bytes=2_498_000,
        sample_video_bps=1_995_000,
        encode_seconds=1.25,
        fps_throughput=192.5,
        encoder="av1_nvenc",
        created_at="2026-10-24T14:00:00Z",
    )

    # 1. Save record
    store.save_trial(record)

    # 2. Query exact trial
    fetched = store.get_trial(
        source_id="src-123",
        stat_fingerprint="1000:50000000",
        recipe_id="av1_nvenc_cq30",
        window_index=0,
    )
    assert fetched is not None
    assert fetched.trial_id == "trial-abc-0"
    assert fetched.sample_video_bps == 1_995_000

    # 3. Query with changed stat fingerprint (cache miss)
    miss = store.get_trial(
        source_id="src-123",
        stat_fingerprint="2000:50000000",  # mtime changed
        recipe_id="av1_nvenc_cq30",
        window_index=0,
    )
    assert miss is None

    # 4. Query all trials for asset
    all_trials = store.get_trials_for_asset("src-123", "1000:50000000", "av1_nvenc_cq30")
    assert len(all_trials) == 1


def test_quota_scheduler_enforces_max_trials(tmp_path: Path):
    """TrialScheduler must respect --max-trials budget and stop executing new trials."""
    media_dir = tmp_path / "videos"
    media_dir.mkdir()
    f1 = media_dir / "vid1.mp4"
    f1.write_bytes(b"content_1" * 100)
    f2 = media_dir / "vid2.mp4"
    f2.write_bytes(b"content_2" * 100)

    ws = resolve_workspace(media_dir)
    recipe = get_recipe("av1_nvenc_cq30")

    vstream = VideoStream(
        stream_index=0,
        stream_type="video",
        codec_name="h264",
        width=1920,
        height=1080,
        bit_rate_bps=6_000_000,
    )
    a1 = VideoAsset(
        source_id="asset-1",
        relative_path="vid1.mp4",
        file_bytes=100_000_000,
        container_format="mp4",
        duration_seconds=300.0,
        streams=(vstream,),
    )
    a2 = VideoAsset(
        source_id="asset-2",
        relative_path="vid2.mp4",
        file_bytes=100_000_000,
        container_format="mp4",
        duration_seconds=300.0,
        streams=(vstream,),
    )

    mock_result = SampleEncodeResult(
        sample_path=tmp_path / "mock.mp4",
        source_path=f1,
        recipe_id="av1_nvenc_cq30",
        window_index=0,
        window_start=0.0,
        window_duration=10.0,
        actual_duration=10.0,
        sample_file_bytes=2_000_000,
        sample_video_bytes=1_998_000,
        sample_video_bps=1_598_400,
        encode_seconds=0.5,
        fps_throughput=480.0,
        encoder="av1_nvenc",
    )

    with patch("videocompress.adapters.ffmpeg.FFmpegAdapter.encode_sample_clip", return_value=mock_result) as mock_encode:
        # Request max 2 trials total across 2 assets with s3 schedule (which would normally want 3*2 = 6 trials)
        records, stopped_reason = run_sample_trials(
            assets=[a1, a2],
            canonical_paths={a1.source_id: str(f1), a2.source_id: str(f2)},
            recipe=recipe,
            workspace=ws,
            schedule="s3",
            max_trials=2,
        )

        assert len(records) == 2
        assert mock_encode.call_count == 2
        assert stopped_reason == "max_trials_budget_reached"


def test_aggregate_sample_estimate_promising_decision():
    """Verify aggregation of measured sample trials into a high-confidence SamplePrediction."""
    vstream = VideoStream(
        stream_index=0,
        stream_type="video",
        codec_name="h264",
        width=1920,
        height=1080,
        bit_rate_bps=8_000_000,
    )
    astream = VideoStream(
        stream_index=1,
        stream_type="audio",
        codec_name="aac",
        channels=2,
        bit_rate_bps=192_000,
    )
    # 1.5 GB source, 1440s duration (original ~8.3 Mbps total)
    asset = VideoAsset(
        source_id="agg-test",
        relative_path="movie.mp4",
        file_bytes=1_500_000_000,
        container_format="mp4",
        duration_seconds=1440.0,
        streams=(vstream, astream),
    )
    recipe = get_recipe("av1_nvenc_cq30")

    # Mock 3 measured trials averaging ~2.4 Mbps for AV1
    t0 = TrialRecord(
        trial_id="t0",
        source_id="agg-test",
        stat_fingerprint="fp",
        recipe_id="av1_nvenc_cq30",
        window_index=0,
        window_start=200.0,
        window_duration=10.0,
        actual_duration=10.0,
        sample_file_bytes=3_000_000,
        sample_video_bytes=2_998_000,
        sample_video_bps=2_398_400,
        encode_seconds=0.8,
        fps_throughput=300.0,
        encoder="av1_nvenc",
        created_at="now",
    )
    t1 = TrialRecord(
        trial_id="t1",
        source_id="agg-test",
        stat_fingerprint="fp",
        recipe_id="av1_nvenc_cq30",
        window_index=1,
        window_start=700.0,
        window_duration=10.0,
        actual_duration=10.0,
        sample_file_bytes=3_100_000,
        sample_video_bytes=3_098_000,
        sample_video_bps=2_478_400,
        encode_seconds=0.8,
        fps_throughput=300.0,
        encoder="av1_nvenc",
        created_at="now",
    )
    t2 = TrialRecord(
        trial_id="t2",
        source_id="agg-test",
        stat_fingerprint="fp",
        recipe_id="av1_nvenc_cq30",
        window_index=2,
        window_start=1100.0,
        window_duration=10.0,
        actual_duration=10.0,
        sample_file_bytes=2_900_000,
        sample_video_bytes=2_898_000,
        sample_video_bps=2_318_400,
        encode_seconds=0.8,
        fps_throughput=300.0,
        encoder="av1_nvenc",
        created_at="now",
    )

    pred = aggregate_sample_estimate(
        asset=asset,
        recipe=recipe,
        trials=[t0, t1, t2],
        min_savings_pct=25.0,
    )

    assert pred.tier == "sampled"
    assert pred.trials_count == 3
    # Average sample bitrate ~2.4 Mbps over 1440s implies ~432 MB video elementary bytes
    assert 400_000_000 <= pred.predicted_video_bytes <= 470_000_000
    # Total container bytes ~432 MB + ~38 MB audio/mux ~470 MB (savings ~1.03 GB, ~68%)
    assert pred.predicted_gross_saved_bytes > 900_000_000
    assert pred.predicted_savings_pct > 60.0
    assert pred.decision == "measured_promising"
    assert pred.confidence == "high"
    assert pred.interval_status == "empirical_sample_measurement"


def test_quota_scheduler_enforces_max_time(tmp_path: Path):
    """TrialScheduler must respect max_time_seconds budget and stop further encodes."""
    media_dir = tmp_path / "videos"
    media_dir.mkdir()
    f1 = media_dir / "vid1.mp4"
    f1.write_bytes(b"content_1" * 100)

    ws = resolve_workspace(media_dir)
    recipe = get_recipe("av1_nvenc_cq30")

    vstream = VideoStream(stream_index=0, stream_type="video", codec_name="h264", width=1920, height=1080)
    a1 = VideoAsset(
        source_id="asset-time-quota",
        relative_path="vid1.mp4",
        file_bytes=100_000_000,
        container_format="mp4",
        duration_seconds=300.0,
        streams=(vstream,),
    )

    # Encode takes 5.0 seconds
    mock_result = SampleEncodeResult(
        sample_path=tmp_path / "mock.mp4",
        source_path=f1,
        recipe_id="av1_nvenc_cq30",
        window_index=0,
        window_start=0.0,
        window_duration=10.0,
        actual_duration=10.0,
        sample_file_bytes=2_000_000,
        sample_video_bytes=1_998_000,
        sample_video_bps=1_598_400,
        encode_seconds=5.0,
        fps_throughput=48.0,
        encoder="av1_nvenc",
    )

    with patch("videocompress.adapters.ffmpeg.FFmpegAdapter.encode_sample_clip", return_value=mock_result) as mock_encode:
        # max_time_seconds=4.0; first trial takes 5.0s, so second trial must be blocked!
        records, stopped_reason = run_sample_trials(
            assets=[a1],
            canonical_paths={a1.source_id: str(f1)},
            recipe=recipe,
            workspace=ws,
            schedule="s3",
            max_time_seconds=4.0,
        )

        assert len(records) == 1
        assert mock_encode.call_count == 1
        assert stopped_reason == "max_time_budget_reached"


def test_trial_cache_hit_avoids_reencoding(tmp_path: Path):
    """Subsequent run must return cached trial from SQLite without calling FFmpeg."""
    media_dir = tmp_path / "videos"
    media_dir.mkdir()
    f1 = media_dir / "vid_cached.mp4"
    f1.write_bytes(b"content_cached" * 100)

    ws = resolve_workspace(media_dir)
    recipe = get_recipe("av1_nvenc_cq30")

    vstream = VideoStream(stream_index=0, stream_type="video", codec_name="h264", width=1920, height=1080)
    a1 = VideoAsset(
        source_id="asset-cached",
        relative_path="vid_cached.mp4",
        file_bytes=100_000_000,
        container_format="mp4",
        duration_seconds=10.0,  # Single window duration
        streams=(vstream,),
    )

    mock_result = SampleEncodeResult(
        sample_path=tmp_path / "mock.mp4",
        source_path=f1,
        recipe_id="av1_nvenc_cq30",
        window_index=0,
        window_start=0.0,
        window_duration=10.0,
        actual_duration=10.0,
        sample_file_bytes=2_000_000,
        sample_video_bytes=1_998_000,
        sample_video_bps=1_598_400,
        encode_seconds=0.4,
        fps_throughput=600.0,
        encoder="av1_nvenc",
    )

    with patch("videocompress.adapters.ffmpeg.FFmpegAdapter.encode_sample_clip", return_value=mock_result) as mock_encode:
        # First run executes encode
        r1, _ = run_sample_trials(
            assets=[a1],
            canonical_paths={a1.source_id: str(f1)},
            recipe=recipe,
            workspace=ws,
            schedule="s3",
            max_trials=1,
        )
        assert len(r1) == 1
        assert mock_encode.call_count == 1

        # Second run without force_refresh uses cache (mock_encode not called again)
        r2, _ = run_sample_trials(
            assets=[a1],
            canonical_paths={a1.source_id: str(f1)},
            recipe=recipe,
            workspace=ws,
            schedule="s3",
            max_trials=1,
            force_refresh=False,
        )
        assert len(r2) == 1
        assert mock_encode.call_count == 1  # Still 1! Cache hit!
        assert r2[0].trial_id == r1[0].trial_id


def test_aggregate_sample_estimate_quality_risk_and_unfavorable():
    """Verify quality_risk when sample bitrate falls below quality floor, and unfavorable when savings are low."""
    vstream = VideoStream(stream_index=0, stream_type="video", codec_name="h264", width=3840, height=2160)
    asset = VideoAsset(
        source_id="potato-sample",
        relative_path="potato.mp4",
        file_bytes=500_000_000,
        container_format="mp4",
        duration_seconds=1000.0,
        streams=(vstream,),
    )
    recipe = get_recipe("av1_nvenc_cq30")

    # 4K quality floor for AV1 is ~2.2 Mbps. Trial measures 500 kbps (severely below quality floor)
    t_potato = TrialRecord(
        trial_id="t_pot",
        source_id="potato-sample",
        stat_fingerprint="fp",
        recipe_id="av1_nvenc_cq30",
        window_index=0,
        window_start=0.0,
        window_duration=10.0,
        actual_duration=10.0,
        sample_file_bytes=625_000,
        sample_video_bytes=623_000,
        sample_video_bps=498_400,
        encode_seconds=0.5,
        fps_throughput=480.0,
        encoder="av1_nvenc",
        created_at="now",
    )

    pred_risk = aggregate_sample_estimate(asset, recipe, [t_potato], min_savings_pct=20.0)
    assert pred_risk.decision == "quality_risk"
    assert any("below recommended visual quality floor" in r for r in pred_risk.rejection_reasons)

    # Now test measured_unfavorable: 1080p asset with target 40% savings, but trial achieves only 10%
    vstream_1080 = VideoStream(stream_index=0, stream_type="video", codec_name="h264", width=1920, height=1080)
    asset_1080 = VideoAsset(
        source_id="bloat-sample",
        relative_path="bloat.mp4",
        file_bytes=500_000_000,
        container_format="mp4",
        duration_seconds=1000.0,
        streams=(vstream_1080,),
    )
    # Measured bitrate ~3.8 Mbps over 1000s implies 475 MB output (only 5% savings)
    t_unfav = TrialRecord(
        trial_id="t_unfav",
        source_id="bloat-sample",
        stat_fingerprint="fp",
        recipe_id="av1_nvenc_cq30",
        window_index=0,
        window_start=0.0,
        window_duration=10.0,
        actual_duration=10.0,
        sample_file_bytes=4_750_000,
        sample_video_bytes=4_748_000,
        sample_video_bps=3_798_400,
        encode_seconds=0.5,
        fps_throughput=480.0,
        encoder="av1_nvenc",
        created_at="now",
    )

    pred_unfav = aggregate_sample_estimate(asset_1080, recipe, [t_unfav], min_savings_pct=40.0)
    assert pred_unfav.decision == "measured_unfavorable"
    assert any("do not meet required minimum savings threshold" in r for r in pred_unfav.rejection_reasons)

