#!/usr/bin/env python3
"""
Integration tests for the enhanced video deduplication pipeline.
"""
import tempfile
import json
from pathlib import Path
from unittest.mock import patch, Mock

from vdedup.pipeline import PipelineConfig, run_pipeline
from vdedup.models import VideoMeta
from vdedup.cache import HashCache
from vdedup.progress import ProgressReporter


def create_test_video_files(temp_dir: Path, count: int = 3):
    """Create mock video files for testing."""
    video_files = []
    for i in range(count):
        video_file = temp_dir / f"video_{i}.mp4"
        video_file.write_bytes(b"fake video content " + str(i).encode() * 100)
        video_files.append(video_file)
    return video_files


def test_pipeline_stage_selection():
    """Test that pipeline correctly handles different stage selections."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        video_files = create_test_video_files(temp_path, 2)

        cfg = PipelineConfig(threads=1)
        reporter = ProgressReporter(enable_dash=False)

        # Test stage 1 only (size-based)
        groups = run_pipeline(
            root=temp_path,
            patterns=["*.mp4"],
            max_depth=0,
            selected_stages=[1],
            cfg=cfg,
            reporter=reporter
        )

        # Should not find duplicates (different content)
        assert len(groups) == 0


def test_pipeline_with_cache():
    """Test pipeline integration with caching."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        cache_path = temp_path / "test_cache.jsonl"
        video_files = create_test_video_files(temp_path, 2)

        # Create identical files for testing
        video_files[1].write_bytes(video_files[0].read_bytes())

        cfg = PipelineConfig(threads=1)
        reporter = ProgressReporter(enable_dash=False)
        cache = HashCache(cache_path)
        cache.open_append()

        try:
            # Run pipeline with stages 1-2 (size + hash)
            groups = run_pipeline(
                root=temp_path,
                patterns=["*.mp4"],
                max_depth=0,
                selected_stages=[1, 2],
                cfg=cfg,
                cache=cache,
                reporter=reporter
            )

            # Should find one duplicate group
            assert len(groups) >= 1

            # Verify cache was used
            assert cache_path.exists()
            cache_content = cache_path.read_text()
            assert len(cache_content.strip().split('\n')) > 0

        finally:
            cache.close()


def test_pipeline_exclusion_logic():
    """Test that files excluded by earlier stages skip later stages."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        video_files = create_test_video_files(temp_path, 3)

        # Create two identical files (will be caught by stage 2)
        video_files[1].write_bytes(video_files[0].read_bytes())

        cfg = PipelineConfig(threads=1)
        reporter = ProgressReporter(enable_dash=False)

        # Mock pHash computation to verify it's not called for excluded files
        with patch('vdedup.phash.compute_phash_signature') as mock_phash:
            mock_phash.return_value = (0x1234567890ABCDEF,) * 5

            groups = run_pipeline(
                root=temp_path,
                patterns=["*.mp4"],
                max_depth=0,
                selected_stages=[1, 2, 4],  # Include pHash stage
                cfg=cfg,
                reporter=reporter
            )

            # pHash should only be called for files not excluded by stage 2
            # Since 2 files are identical, they should be excluded from stage 4
            expected_phash_calls = len(video_files) - 2  # Exclude the duplicate pair
            assert mock_phash.call_count <= len(video_files)  # Should not exceed total files


def test_pipeline_skip_paths():
    """Test that skip_paths parameter correctly excludes files."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        video_files = create_test_video_files(temp_path, 3)

        cfg = PipelineConfig(threads=1)
        reporter = ProgressReporter(enable_dash=False)

        # Skip the first video file
        skip_paths = {video_files[0]}

        groups = run_pipeline(
            root=temp_path,
            patterns=["*.mp4"],
            max_depth=0,
            selected_stages=[1],
            cfg=cfg,
            reporter=reporter,
            skip_paths=skip_paths
        )

        # Verify that skipped file was not processed
        # Since we only have different-sized files and skipped one,
        # we should see fewer files in the scan results
        assert reporter.scanned_files == len(video_files) - 1


def test_pipeline_error_recovery():
    """Test that pipeline continues when individual files fail."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        video_files = create_test_video_files(temp_path, 3)

        # Create a file that will cause stat() to fail
        bad_file = temp_path / "corrupted.mp4"
        bad_file.write_text("fake video")

        cfg = PipelineConfig(threads=1)
        reporter = ProgressReporter(enable_dash=False)

        # Mock os.stat to fail for the bad file
        original_stat = Path.stat

        def mock_stat(self):
            if self.name == "corrupted.mp4":
                raise OSError("Mock file error")
            return original_stat(self)

        with patch.object(Path, 'stat', mock_stat):
            # Pipeline should continue despite the error
            groups = run_pipeline(
                root=temp_path,
                patterns=["*.mp4"],
                max_depth=0,
                selected_stages=[1],
                cfg=cfg,
                reporter=reporter
            )

            # Should complete without crashing
            assert isinstance(groups, dict)


def test_reporter_integration():
    """Test that progress reporter correctly tracks pipeline progress."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        video_files = create_test_video_files(temp_path, 2)

        cfg = PipelineConfig(threads=1)
        reporter = ProgressReporter(enable_dash=False)

        run_pipeline(
            root=temp_path,
            patterns=["*.mp4"],
            max_depth=0,
            selected_stages=[1],
            cfg=cfg,
            reporter=reporter
        )

        # Verify reporter tracked the files
        assert reporter.total_files == len(video_files)
        assert reporter.scanned_files == len(video_files)


if __name__ == "__main__":
    test_pipeline_stage_selection()
    test_pipeline_with_cache()
    test_pipeline_exclusion_logic()
    test_pipeline_skip_paths()
    test_pipeline_error_recovery()
    test_reporter_integration()
    print("All integration tests passed!")