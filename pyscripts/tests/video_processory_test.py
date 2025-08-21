import argparse
import json
import pathlib
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

# Add script directory to path to allow import
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import video_processor as vp


@pytest.fixture
def mock_video_info():
    """Provides a mock VideoInfo object for testing."""
    info = vp.VideoInfo(pathlib.Path("test.mp4"))
    info.resolution = (1920, 1080)
    info.duration = 120.0
    info.size = 500 * 1024 * 1024 # 500 MiB
    info.bitrate = 3500 * 1000 # 3500 kbps
    return info


class TestHelperFunctions:
    @pytest.mark.parametrize("input_str, expected_bytes", [
        ("1024", 1024), ("1K", 1024), ("1M", 1024**2), ("1.5G", int(1.5 * 1024**3)),
        ("2T", 2 * 1024**4), ("0", 0), (" 500M ", 500 * 1024**2)
    ])
    def test_parse_size_valid(self, input_str, expected_bytes):
        assert vp.parse_size(input_str) == expected_bytes

    def test_parse_size_invalid(self):
        with pytest.raises(ValueError):
            vp.parse_size("500X")

    @pytest.mark.parametrize("input_str, expected_bps", [
        ("128k", 128_000), ("2M", 2_000_000), ("0.5m", 500_000), ("3000", 3000)
    ])
    def test_parse_bitrate_valid(self, input_str, expected_bps):
        assert vp.parse_bitrate(input_str) == expected_bps

    @pytest.mark.parametrize("input_str, expected_res", [
        ("1920x1080", (1920, 1080)), ("1280:720", (1280, 720)), ("640 480", (640, 480))
    ])
    def test_parse_resolution_valid(self, input_str, expected_res):
        assert vp.parse_resolution(input_str) == expected_res

    def test_parse_resolution_invalid(self):
        with pytest.raises(ValueError):
            vp.parse_resolution("1920-1080")

    @patch('video_processor.shutil.which', return_value=None)
    def test_check_dependencies_missing(self, mock_which):
        with pytest.raises(SystemExit):
            vp.check_dependencies()


class TestVideoFinder:
    def test_find_videos(self, tmp_path):
        """Tests recursive and non-recursive file finding."""
        sub_dir = tmp_path / "sub"
        sub_dir.mkdir()
        (tmp_path / "vid1.mp4").touch()
        (tmp_path / "image.jpg").touch()
        (sub_dir / "vid2.mkv").touch()

        # Non-recursive
        found = list(vp.VideoFinder.find([tmp_path], recursive=False))
        assert len(found) == 1
        assert found[0].name == "vid1.mp4"

        # Recursive
        found_rec = list(vp.VideoFinder.find([tmp_path], recursive=True))
        assert len(found_rec) == 2
        assert {p.name for p in found_rec} == {"vid1.mp4", "vid2.mkv"}

        # Find specific file
        found_file = list(vp.VideoFinder.find([tmp_path / "vid1.mp4"], recursive=False))
        assert len(found_file) == 1


class TestVideoInfo:
    @patch('video_processor.subprocess.run')
    def test_get_video_info_success(self, mock_run):
        """Tests successful parsing of ffprobe JSON output."""
        ffprobe_output = {
            "format": {"size": "1000000", "duration": "120.5", "bit_rate": "66378"},
            "streams": [{
                "codec_type": "video", "width": 1920, "height": 1080,
                "bit_rate": "65000", "codec_name": "h264"
            }]
        }
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(ffprobe_output)
        )
        info = vp.VideoInfo.get_video_info(pathlib.Path("dummy.mp4"))

        assert not info.error
        assert info.size == 1000000
        assert info.duration == 120.5
        assert info.resolution == (1920, 1080)
        assert info.codec_name == "h264"

    @patch('video_processor.subprocess.run')
    def test_get_video_info_failure(self, mock_run):
        """Tests handling of ffprobe errors."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "cmd")
        info = vp.VideoInfo.get_video_info(pathlib.Path("bad.mp4"))
        assert info.error is not None


class TestArgGeneration:
    def test_generate_args_cpu_crf(self, mock_video_info):
        args = argparse.Namespace(video_encoder="libx264", preset="medium", crf=22, cq=None, video_bitrate=None, audio_bitrate=None, resolution=None)
        ffmpeg_args = vp.generate_ffmpeg_args(mock_video_info, args)
        assert ffmpeg_args == ["-c:v", "libx264", "-preset", "medium", "-crf", "22", "-c:a", "copy"]

    def test_generate_args_gpu_cq(self, mock_video_info):
        args = argparse.Namespace(video_encoder="hevc_nvenc", preset="p5", crf=None, cq=24, video_bitrate=None, audio_bitrate="128k", resolution=None)
        ffmpeg_args = vp.generate_ffmpeg_args(mock_video_info, args)
        assert ffmpeg_args == ["-c:v", "hevc_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "24", "-c:a", "aac", "-b:a", "128k"]

    def test_generate_args_downscale(self, mock_video_info):
        """Test that downscaling filter is added when source is larger."""
        mock_video_info.resolution = (3840, 2160)
        args = argparse.Namespace(resolution=(1920, 1080), video_encoder="libx264", preset="medium", crf=22, cq=None, video_bitrate=None, audio_bitrate=None)
        ffmpeg_args = vp.generate_ffmpeg_args(mock_video_info, args)
        assert any("scale=1920:1080" in arg for arg in ffmpeg_args)

    def test_generate_args_no_upscale(self, mock_video_info):
        """Test that scale filter is NOT added when source is smaller."""
        mock_video_info.resolution = (1280, 720)
        args = argparse.Namespace(resolution=(1920, 1080), video_encoder="libx264", preset="medium", crf=22, cq=None, video_bitrate=None, audio_bitrate=None)
        ffmpeg_args = vp.generate_ffmpeg_args(mock_video_info, args)
        assert not any("scale=" in arg for arg in ffmpeg_args)

    def test_generate_args_no_upscale_bugfix(self, mock_video_info):
        """Test the specific bug fix for vertical/non-standard aspect ratios."""
        mock_video_info.resolution = (1080, 1920) # Vertical video
        args = argparse.Namespace(resolution=(1920, 1080), video_encoder="libx264", preset="medium", crf=22, cq=None, video_bitrate=None, audio_bitrate=None)
        ffmpeg_args = vp.generate_ffmpeg_args(mock_video_info, args)
        assert any("scale=1920:1080" in arg for arg in ffmpeg_args)


class TestArgParsing:
    def test_valid_args(self, monkeypatch):
        """Test a valid command line invocation."""
        monkeypatch.setattr(sys, 'argv', [
            'video_processor.py', 'process', '-i', '.', '-o', '.', '--crf', '22'
        ])
        parser = vp.create_parser()
        args = parser.parse_args()
        assert args.command == 'process'
        assert args.crf == 22

    @pytest.mark.parametrize("invalid_args", [
        ['process', '-i', '.', '-o', '.', '--crf', '22', '--cq', '22'], # Mutually exclusive
        ['process', '-i', '.', '-o', '.', '--crf', '22', '-ve', 'h264_nvenc'], # CRF with NVENC
        ['process', '-i', '.', '-o', '.', '--cq', '22', '-ve', 'libx264'], # CQ with libx
        ['process', '-i', '.', '-o', '.'] # No processing options
    ])
    def test_invalid_combinations(self, monkeypatch, invalid_args):
        """Test argument combinations that should cause the program to exit."""
        monkeypatch.setattr(sys, 'argv', ['video_processor.py'] + invalid_args)
        with pytest.raises(SystemExit):
            vp.main()

class TestProcessCommandFiltering:
    @pytest.fixture
    def mock_videos(self):
        """Create a list of mock VideoInfo objects for filtering tests."""
        v1 = vp.VideoInfo(pathlib.Path("small_low_res.mp4"))
        v1.size = 100 * 1024**2
        v1.resolution = (1280, 720)
        v1.bitrate = 1000 * 1000

        v2 = vp.VideoInfo(pathlib.Path("medium_hd.mp4"))
        v2.size = 800 * 1024**2
        v2.resolution = (1920, 1080)
        v2.bitrate = 5000 * 1000

        v3 = vp.VideoInfo(pathlib.Path("large_4k.mkv"))
        v3.size = 2 * 1024**3
        v3.resolution = (3840, 2160)
        v3.bitrate = 20000 * 1000
        return [v1, v2, v3]

    @patch('video_processor.VideoFinder.find')
    @patch('video_processor.VideoInfo.get_video_info')
    def test_dry_run_filtering(self, mock_get_info, mock_find, mock_videos, capsys):
        """Test that dry-run filtering correctly selects videos and prints output."""
        mock_find.return_value = [v.path for v in mock_videos]
        # This makes get_video_info return the corresponding mock object
        mock_get_info.side_effect = mock_videos

        args = argparse.Namespace(
            input=[pathlib.Path(".")], output_dir=pathlib.Path("out"), recursive=False,
            dry_run=True,
            min_size=vp.parse_size("500M"),
            max_size=vp.parse_size("1G"),
            min_bitrate=None, max_bitrate=None,
            min_resolution=None, max_resolution=None,
            # Dummy encoding args
            video_encoder="libx264", preset="medium", crf=22, cq=None, video_bitrate=None, audio_bitrate=None, resolution=None
        )

        vp.run_process_command(args)
        captured = capsys.readouterr()

        # Assert that only the medium video was selected
        assert "Filtered down to 1 videos to process." in captured.out
        assert "medium_hd.mp4" in captured.out
        assert "small_low_res.mp4" not in captured.out
        assert "large_4k.mkv" not in captured.out
