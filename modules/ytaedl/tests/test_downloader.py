"""Tests for ytaedl.downloader module."""

import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch

import ytaedl.downloader as downloader


class TestDownloader:
    """Test cases for the downloader module."""

    class _FakeProc:
        def __init__(self, rc=0):
            self.stdout = object()
            self._rc = rc
            self.killed = False
            self.terminated = False

        def kill(self):
            self.killed = True
            self._rc = 124

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return self._rc

    class _NoopProgLogger:
        def simulate_start(self, *args, **kwargs):
            pass

        def simulate_ok(self, *args, **kwargs):
            pass

        def start(self, *args, **kwargs):
            pass

        def attempt_start(self, *args, **kwargs):
            pass

        def attempt_success(self, *args, **kwargs):
            pass

        def attempt_fail(self, *args, **kwargs):
            pass

        def progress(self, *args, **kwargs):
            pass

        def finish(self, *args, **kwargs):
            pass

        def force_exit(self, *args, **kwargs):
            pass

    def test_make_parser(self):
        """Test that make_parser creates a valid ArgumentParser."""
        parser = downloader.make_parser()
        assert parser.prog == "ytaedler.py"

        # Test parsing with required arguments
        args = parser.parse_args(["-f", "test.txt"])
        assert args.url_file == "test.txt"
        assert args.mode == "auto"
        assert args.max_resolution is None

        assert args.proxy_dl_location is None

        args_with_proxy = parser.parse_args(["-f", "test.txt", "-P", "/tmp/mirror"])
        assert args_with_proxy.proxy_dl_location == "/tmp/mirror"

        args_with_res = parser.parse_args(["-f", "test.txt", "--max-resolution", "2k"])
        assert args_with_res.max_resolution == "2k"

        args_with_short = parser.parse_args(["-f", "test.txt", "-H", "720"])
        assert args_with_short.max_resolution == "720"

        args_with_stop = parser.parse_args(["-f", "test.txt", "-B", "/tmp/stop"])
        assert args_with_stop.stop_sentinel == "/tmp/stop"

        args_with_grid = parser.parse_args(["-f", "test.txt", "-G", "/tmp/trial.json"])
        assert args_with_grid.ytdlp_grid_config_file == "/tmp/trial.json"

    def test_read_urls_basic(self):
        """Test reading URLs from a file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("https://example.com/video1\n")
            f.write("https://example.com/video2\n")
            f.write("\n")  # empty line
            f.write("# comment line\n")
            f.write("https://example.com/video3\n")
            temp_path = f.name

        try:
            urls = downloader._read_urls(Path(temp_path))
            assert len(urls) == 3
            assert "https://example.com/video1" in urls
            assert "https://example.com/video2" in urls
            assert "https://example.com/video3" in urls
        finally:
            os.unlink(temp_path)

    def test_read_urls_with_comments(self):
        """Test reading URLs with inline comments."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("https://example.com/video1  # inline comment\n")
            f.write("https://example.com/video2  ; another comment\n")
            f.write("; full line comment\n")
            f.write("] bracket comment\n")
            temp_path = f.name

        try:
            urls = downloader._read_urls(Path(temp_path))
            assert len(urls) == 2
            assert "https://example.com/video1" in urls
            assert "https://example.com/video2" in urls
        finally:
            os.unlink(temp_path)

    def test_read_urls_deduplication(self):
        """Test that duplicate URLs are removed while preserving order."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("https://example.com/video1\n")
            f.write("https://example.com/video2\n")
            f.write("https://example.com/video1\n")  # duplicate
            f.write("https://example.com/video3\n")
            temp_path = f.name

        try:
            urls = downloader._read_urls(Path(temp_path))
            assert len(urls) == 3
            assert urls == ["https://example.com/video1", "https://example.com/video2", "https://example.com/video3"]
        finally:
            os.unlink(temp_path)

    def test_is_aebn(self):
        """Test AEBN URL detection."""
        assert downloader._is_aebn("https://straight.aebn.com/video/123")
        assert downloader._is_aebn("https://gay.aebn.com/video/456")
        assert not downloader._is_aebn("https://pornhub.com/view_video.php?viewkey=123")
        assert not downloader._is_aebn("https://example.com/video")
        assert not downloader._is_aebn("invalid-url")

    def test_looks_supported_video(self):
        """Test video URL support detection."""
        # PornHub
        assert downloader._looks_supported_video("https://pornhub.com/view_video.php?viewkey=123")
        assert downloader._looks_supported_video("https://www.pornhub.com/view_video.php?viewkey=123")

        # Eporner
        assert downloader._looks_supported_video("https://eporner.com/video-123/title")
        assert downloader._looks_supported_video("https://eporner.com/hd-porn/123/title")
        assert not downloader._looks_supported_video("https://eporner.com/pornstar/name")
        assert not downloader._looks_supported_video("https://eporner.com/category/name")

        # AEBN
        assert downloader._looks_supported_video("https://straight.aebn.com/video/123")

        # Default allow
        assert downloader._looks_supported_video("https://example.com/video")

    def test_clamp_progress_preserves_active_bytes_and_drops_unreliable_total(self):
        evt = {
            "event": "progress",
            "downloaded": 125,
            "total": 100,
            "percent": 125.0,
            "speed_bps": 50_000,
        }

        clamped = downloader._clamp_progress(evt)

        assert clamped["downloaded"] == 125
        assert clamped["total"] is None
        assert clamped["percent"] is None
        assert clamped["eta_s"] is None
        assert clamped["unreliable_total"] is True

    def test_archive_processed_status_wins_over_later_stall(self, tmp_path):
        archive_file = tmp_path / "yt-alpha.txt"
        url = "https://example.com/video"
        archive_file.write_text(
            "\n".join([
                f"downloaded\t1.000\t2026-05-07T07:00:00\t2.00MiB\tid\t{url}",
                f"stalled\t30.000\t2026-05-07T07:01:00\t2.00MiB\tid\t{url}",
            ])
            + "\n",
            encoding="utf-8",
        )

        statuses, _lines, changed = downloader._read_archive_statuses(archive_file, [url])

        assert changed is False
        assert statuses[url] == "downloaded"

    def test_archive_stalled_is_processed(self, tmp_path):
        archive_file = tmp_path / "yt-alpha.txt"
        url = "https://example.com/video"
        archive_file.write_text(
            f"stalled\t30.000\t2026-05-07T07:01:00\t2.00MiB\tid\t{url}\n",
            encoding="utf-8",
        )

        statuses, _lines, _changed = downloader._read_archive_statuses(archive_file, [url])

        assert statuses[url] == "stalled"
        assert statuses[url] in downloader.ARCHIVE_PROCESSED_STATUSES

    def test_progress_activity_pre_transfer_stalls_on_short_window(self):
        activity = downloader._ProgressActivity(
            stall_seconds=4,
            complete_stall_seconds=300,
            started_at=0.0,
            last_real_event_t=0.0,
        )
        activity.observe({"event": "heartbeat"}, 5.0)

        assert activity.stall(5.0) == (4, "pre_transfer_no_output")

    def test_progress_activity_active_transfer_uses_longer_window(self):
        activity = downloader._ProgressActivity(
            stall_seconds=4,
            complete_stall_seconds=300,
            started_at=0.0,
            last_real_event_t=0.0,
        )
        activity.observe(
            {"event": "progress", "downloaded": 100, "total": 1_000, "percent": 10.0, "speed_bps": 1_000.0},
            1.0,
        )
        activity.observe({"event": "heartbeat"}, 10.0)

        assert activity.stall(10.0) is None

    def test_progress_activity_active_transfer_stalls_after_growth_window(self):
        activity = downloader._ProgressActivity(
            stall_seconds=4,
            complete_stall_seconds=300,
            started_at=0.0,
            last_real_event_t=0.0,
        )
        activity.observe(
            {"event": "progress", "downloaded": 100, "total": 1_000, "percent": 10.0, "speed_bps": 0.0},
            1.0,
        )
        activity.observe({"event": "heartbeat"}, 32.0)

        assert activity.stall(32.0) == (30, "active_no_byte_growth")

    def test_progress_activity_near_complete_uses_complete_stall_window(self):
        activity = downloader._ProgressActivity(
            stall_seconds=4,
            complete_stall_seconds=300,
            started_at=0.0,
            last_real_event_t=0.0,
        )
        activity.observe(
            {"event": "progress", "downloaded": 990, "total": 1_000, "percent": 99.0, "speed_bps": 0.0},
            1.0,
        )

        assert activity.stall(302.0) == (300, "near_complete_stall")

    def test_run_one_active_progress_survives_short_heartbeat_gap(self, monkeypatch):
        current_time = [0.0]

        def fake_time():
            return current_time[0]

        def fake_iter(tool, stdout, raw_log_path=None, heartbeat_secs=None):
            current_time[0] = 1.0
            yield {"event": "progress", "downloaded": 100, "total": 1_000, "percent": 10.0, "speed_bps": 1_000.0}
            current_time[0] = 10.0
            yield {"event": "heartbeat"}

        emitted = []
        monkeypatch.setattr(downloader.time, "time", fake_time)
        monkeypatch.setattr(downloader, "iter_parsed_events", fake_iter)
        monkeypatch.setattr(downloader, "_emit_json", emitted.append)
        monkeypatch.setattr(downloader.subprocess, "Popen", lambda *a, **k: self._FakeProc(rc=0))

        rc, info = downloader._run_one(
            tool="yt-dlp",
            urls=["https://example.com/video"],
            out_dir=Path("."),
            canonical_out_dir=Path("."),
            partial_root=Path("."),
            raw_dir=Path("."),
            url_index=1,
            proglog=self._NoopProgLogger(),
            timeout=None,
            retries=0,
            quiet=True,
            dry_run=False,
            progress_freq_s=None,
            max_ndjson_rate=-1,
            stall_seconds=4,
            program_deadline=None,
            max_dl_speed=None,
            max_height=None,
            extdl_fallback=False,
            skip_simulate_check=True,
        )

        assert rc == 0
        assert info["downloaded"] == 100
        assert not any(evt.get("event") == "stalled" for evt in emitted)

    def test_run_one_pre_transfer_still_stalls(self, monkeypatch):
        current_time = [0.0]

        def fake_time():
            return current_time[0]

        def fake_iter(tool, stdout, raw_log_path=None, heartbeat_secs=None):
            current_time[0] = 5.0
            yield {"event": "heartbeat"}

        emitted = []
        monkeypatch.setattr(downloader.time, "time", fake_time)
        monkeypatch.setattr(downloader, "iter_parsed_events", fake_iter)
        monkeypatch.setattr(downloader, "_emit_json", emitted.append)
        monkeypatch.setattr(downloader.subprocess, "Popen", lambda *a, **k: self._FakeProc(rc=0))

        rc, _info = downloader._run_one(
            tool="yt-dlp",
            urls=["https://example.com/video"],
            out_dir=Path("."),
            canonical_out_dir=Path("."),
            partial_root=Path("."),
            raw_dir=Path("."),
            url_index=1,
            proglog=self._NoopProgLogger(),
            timeout=None,
            retries=0,
            quiet=True,
            dry_run=False,
            progress_freq_s=None,
            max_ndjson_rate=-1,
            stall_seconds=4,
            program_deadline=None,
            max_dl_speed=None,
            max_height=None,
            extdl_fallback=False,
            skip_simulate_check=True,
        )

        stalled_events = [evt for evt in emitted if evt.get("event") == "stalled"]
        assert rc == 124
        assert stalled_events
        assert stalled_events[-1]["reason"] == "pre_transfer_no_output"

    def test_run_one_successful_fallback_uses_fallback_progress(self, monkeypatch):
        current_time = [0.0]

        def fake_time():
            return current_time[0]

        def fake_iter(tool, stdout, raw_log_path=None, heartbeat_secs=None):
            current_time[0] = 5.0
            yield {"event": "heartbeat"}

        monkeypatch.setattr(downloader.time, "time", fake_time)
        monkeypatch.setattr(downloader, "iter_parsed_events", fake_iter)
        monkeypatch.setattr(downloader.subprocess, "Popen", lambda *a, **k: self._FakeProc(rc=0))
        monkeypatch.setattr(
            downloader,
            "_run_extdl_fallback",
            lambda *a, **k: (0, {"event": "progress", "downloaded": 200, "total": 300, "percent": 66.7}),
        )

        rc, info = downloader._run_one(
            tool="yt-dlp",
            urls=["https://example.com/video"],
            out_dir=Path("."),
            canonical_out_dir=Path("."),
            partial_root=Path("."),
            raw_dir=Path("."),
            url_index=1,
            proglog=self._NoopProgLogger(),
            timeout=None,
            retries=0,
            quiet=True,
            dry_run=False,
            progress_freq_s=None,
            max_ndjson_rate=-1,
            stall_seconds=4,
            program_deadline=None,
            max_dl_speed=None,
            max_height=None,
            extdl_fallback=True,
            skip_simulate_check=True,
        )

        assert rc == 0
        assert info["downloaded"] == 200
        assert info["total"] == 300

    def test_extract_video_id(self):
        """Test video ID extraction from URLs."""
        # PornHub
        assert downloader._extract_video_id("https://pornhub.com/view_video.php?viewkey=abc123") == "abc123"

        # Eporner
        assert downloader._extract_video_id("https://eporner.com/video-123/title") == "video-123"
        assert downloader._extract_video_id("https://eporner.com/hd-porn/456/title") == "hd-porn"

        # AEBN
        assert downloader._extract_video_id("https://straight.aebn.com/video/123#scene-456") == "456"

        # Unknown format
        assert downloader._extract_video_id("https://example.com/video") == ""
        assert downloader._extract_video_id("invalid-url") == ""

    def test_max_height_for_label(self):
        """Test mapping from resolution label to pixel height."""
        assert downloader._max_height_for_label("4k") == 2160
        assert downloader._max_height_for_label("2K") == 1440
        assert downloader._max_height_for_label("1080") == 1080
        assert downloader._max_height_for_label(None) is None
        assert downloader._max_height_for_label("unknown") is None

    def test_build_ytdlp_cmd(self):
        """Test yt-dlp command building."""
        urls = ["https://example.com/video1", "https://example.com/video2"]
        out_dir = Path("/tmp/output")

        cmd = downloader._build_ytdlp_cmd(urls, out_dir)
        assert cmd[0] == "yt-dlp"
        assert "--newline" in cmd
        assert "-o" in cmd
        assert str(out_dir / "%(title)s.%(ext)s") in cmd
        assert "https://example.com/video1" in cmd
        assert "https://example.com/video2" in cmd

    def test_build_ytdlp_cmd_with_rate_limit(self):
        """Test yt-dlp command building with rate limit."""
        urls = ["https://example.com/video1"]
        out_dir = Path("/tmp/output")

        cmd = downloader._build_ytdlp_cmd(urls, out_dir, max_mibs=5.5)
        assert "--limit-rate" in cmd
        assert "5.50M" in cmd

    def test_build_ytdlp_cmd_with_height_limit(self):
        """Test yt-dlp command with a maximum height selector."""
        urls = ["https://example.com/video1"]
        out_dir = Path("/tmp/output")

        cmd = downloader._build_ytdlp_cmd(urls, out_dir, max_height=1080)
        assert "--format" in cmd
        fmt = cmd[cmd.index("--format") + 1]
        assert "height<=1080" in fmt

    def test_build_ytdlp_cmd_with_native_grid_config(self):
        urls = ["https://example.com/video1"]
        out_dir = Path("/tmp/output")
        config = {
            "downloader": "native",
            "concurrent_fragments": 8,
            "http_chunk_size": "10M",
            "buffer_size": "4M",
            "resize_buffer": False,
            "socket_timeout": 30,
            "retries": 5,
            "fragment_retries": 20,
            "force_ip": "ipv4",
            "format": "best",
        }

        cmd = downloader._build_ytdlp_cmd(urls, out_dir, grid_config=config)

        assert cmd[cmd.index("--downloader") + 1] == "native"
        assert cmd[cmd.index("--concurrent-fragments") + 1] == "8"
        assert cmd[cmd.index("--http-chunk-size") + 1] == "10M"
        assert cmd[cmd.index("--buffer-size") + 1] == "4M"
        assert "--no-resize-buffer" in cmd
        assert cmd[cmd.index("--socket-timeout") + 1] == "30"
        assert cmd[cmd.index("--retries") + 1] == "5"
        assert cmd[cmd.index("--fragment-retries") + 1] == "20"
        assert "--force-ipv4" in cmd
        assert cmd[cmd.index("--format") + 1] == "best"

    def test_build_ytdlp_cmd_with_aria2c_grid_config(self):
        urls = ["https://example.com/video1"]
        out_dir = Path("/tmp/output")
        config = {
            "downloader": "aria2c",
            "aria2c_max_connection_per_server": 4,
            "aria2c_split": 8,
            "aria2c_min_split_size": "10M",
            "aria2c_piece_length": "2M",
            "aria2c_file_allocation": "none",
            "aria2c_disk_cache": "64M",
        }

        cmd = downloader._build_ytdlp_cmd(urls, out_dir, grid_config=config)

        assert cmd[cmd.index("--downloader") + 1] == "aria2c"
        aria_args = cmd[cmd.index("--downloader-args") + 1]
        assert aria_args.startswith("aria2c:")
        assert "-x 4" in aria_args
        assert "-s 8" in aria_args
        assert "-k 10M" in aria_args
        assert "--piece-length=2M" in aria_args
        assert "--file-allocation=none" in aria_args
        assert "--disk-cache=64M" in aria_args

    def test_build_aebndl_cmd(self):
        """Test aebndl command building."""
        url = "https://straight.aebn.com/video/123"
        out_dir = Path("/tmp/output")
        work_dir = Path("/tmp/work")

        cmd = downloader._build_aebndl_cmd(url, out_dir, work_dir)
        assert cmd[0] == "aebndl"
        assert "--json" in cmd
        assert "-o" in cmd
        assert str(out_dir) in cmd
        assert "-w" in cmd
        assert str(work_dir) in cmd
        assert url in cmd

    def test_build_aebndl_cmd_with_height_limit(self):
        """Test aebndl command when max height is provided."""
        url = "https://straight.aebn.com/video/123"
        out_dir = Path("/tmp/output")
        work_dir = Path("/tmp/work")

        cmd = downloader._build_aebndl_cmd(url, out_dir, work_dir, max_height=720)
        assert "-r" in cmd
        idx = cmd.index("-r")
        assert cmd[idx + 1] == "720"

    def test_default_outdir_for(self):
        """Test default output directory generation."""
        urlfile = Path("/path/to/my_videos.txt")
        outdir = downloader._default_outdir_for(urlfile)
        assert outdir == Path("./stars/my_videos")

    def test_urlfile_stem(self):
        """Test URL file stem extraction."""
        assert downloader._urlfile_stem(Path("/path/to/test.txt")) == "test"
        assert downloader._urlfile_stem(Path("videos.txt")) == "videos"

    def test_hms_ms_formatting(self):
        """Test HMS millisecond formatting."""
        assert downloader._hms_ms(0) == "00:00:00.000"
        assert downloader._hms_ms(61.5) == "00:01:01.500"
        assert downloader._hms_ms(3661.123) == "01:01:01.123"

    def test_ensure_dir(self):
        """Test directory creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir) / "test" / "nested"
            downloader._ensure_dir(test_dir)
            assert test_dir.exists()
            assert test_dir.is_dir()

    def test_emit_json(self):
        """Test JSON emission to stdout."""
        test_data = {"event": "test", "value": 123}

        with patch('sys.stdout') as mock_stdout:
            downloader._emit_json(test_data)
            mock_stdout.write.assert_called_once_with('{"event": "test", "value": 123}\n')
            mock_stdout.flush.assert_called_once()

    def test_stop_sentinel_active(self, tmp_path):
        sentinel = tmp_path / "stop"
        assert downloader._stop_sentinel_active(None) is False
        assert downloader._stop_sentinel_active(sentinel) is False
        sentinel.write_text("stop", encoding="utf-8")
        assert downloader._stop_sentinel_active(sentinel) is True


class TestProgLogger:
    """Test cases for the ProgLogger class."""

    def test_prog_logger_creation(self):
        """Test ProgLogger creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "test.log"
            logger = downloader.ProgLogger(log_path, t0=1000.0)
            assert logger.path == log_path
            assert logger.t0 == 1000.0
            assert logger.counter == 0

    def test_prog_logger_start(self):
        """Test ProgLogger start method."""
        import datetime
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "test.log"

            fixed_dt = datetime.datetime(2025, 1, 1, 10, 41, 37)
            with patch('time.time', return_value=1001.5), \
                 patch('ytaedl.downloader.datetime') as mock_dt:
                mock_dt.datetime.now.return_value = fixed_dt
                logger = downloader.ProgLogger(log_path, t0=1000.0)
                logger.start(1, 1, "https://example.com/video")

            content = log_path.read_text()
            assert "[10:41:37][00:00:01.500] START  [1/1] https://example.com/video" in content
            assert logger.counter == 1

    def test_prog_logger_finish(self):
        """Test ProgLogger finish method."""
        import datetime
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "test.log"

            fixed_dt = datetime.datetime(2025, 1, 1, 10, 41, 37)
            with patch('time.time', return_value=1002.0), \
                 patch('ytaedl.downloader.datetime') as mock_dt:
                mock_dt.datetime.now.return_value = fixed_dt
                logger = downloader.ProgLogger(log_path, t0=1000.0)
                logger.counter = 1
                logger.finish(1, 1.5, "FINISH_SUCCESS")

            content = log_path.read_text()
            assert "[10:41:37][00:00:02.000] FINISH_SUCCESS [1] Elapsed 00:00:01.500, Status=SUCCESS" in content


@pytest.mark.integration
class TestIntegration:
    """Integration tests that require external dependencies."""

    def test_main_dry_run(self):
        """Test main function with dry run."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("https://example.com/video1\n")
            temp_path = f.name

        try:
            with patch('sys.argv', ['ytaedl', '-f', temp_path, '-n']):
                with patch('ytaedl.downloader.print') as mock_print:
                    result = downloader.main()
                    assert result == 0
                    # Should have printed dry run command
                    mock_print.assert_called()
        finally:
            os.unlink(temp_path)

    def test_main_missing_file(self):
        """Test main function with missing URL file."""
        with patch('sys.argv', ['ytaedl', '-f', '/nonexistent/file.txt']):
            with patch('sys.stderr'):
                result = downloader.main()
                assert result == 2

    def test_main_empty_file(self):
        """Test main function with empty URL file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("")  # empty file
            temp_path = f.name

        try:
            with patch('sys.argv', ['ytaedl', '-f', temp_path]):
                with patch('sys.stderr'):
                    result = downloader.main()
                    assert result == 3
        finally:
            os.unlink(temp_path)

    def test_main_with_max_resolution_ytdlp(self):
        """Ensure --max-resolution caps yt-dlp height."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("https://example.com/video1\n")
            temp_path = f.name

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                log_path = Path(tmpdir) / "prog.log"
                raw_dir = Path(tmpdir) / "raw"
                raw_dir.mkdir()

                with patch('sys.argv', ['ytaedl', '-f', temp_path, '--max-resolution', '2k', '-g', str(log_path), '-r', str(raw_dir)]):
                    with patch('ytaedl.downloader._run_one') as mock_run:
                        mock_run.return_value = (0, {'elapsed_s': 0.1, 'downloaded': 0, 'total': 0, 'already': False, 'downloader': 'yt-dlp'})
                        result = downloader.main()

                assert result == 0
                assert mock_run.called
                call_kwargs = mock_run.call_args.kwargs
                assert call_kwargs['tool'] == 'yt-dlp'
                assert call_kwargs['max_height'] == 1440
        finally:
            os.unlink(temp_path)

    def test_main_with_max_resolution_aebn(self):
        """Ensure --max-resolution caps aebndl height."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("https://straight.aebn.com/video/123#scene-45\n")
            temp_path = f.name

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                log_path = Path(tmpdir) / "prog.log"
                raw_dir = Path(tmpdir) / "raw"
                raw_dir.mkdir()

                with patch('sys.argv', ['ytaedl', '-f', temp_path, '--max-resolution', '2k', '-g', str(log_path), '-r', str(raw_dir)]):
                    with patch('ytaedl.downloader._run_one') as mock_run:
                        mock_run.return_value = (0, {'elapsed_s': 0.1, 'downloaded': 0, 'total': 0, 'already': False, 'downloader': 'aebndl'})
                        result = downloader.main()

                assert result == 0
                assert mock_run.called
                call_kwargs = mock_run.call_args.kwargs
                assert call_kwargs['tool'] == 'aebndl'
                assert call_kwargs['max_height'] == 1440
        finally:
            os.unlink(temp_path)

    def test_main_stop_sentinel_after_current_url_stops_before_next(self, tmp_path):
        urlfile = tmp_path / "urls.txt"
        urlfile.write_text("https://example.com/video1\nhttps://example.com/video2\n", encoding="utf-8")
        stop_sentinel = tmp_path / "stop"
        log_path = tmp_path / "prog.log"
        raw_dir = tmp_path / "raw"
        archive_dir = tmp_path / "archive"
        raw_dir.mkdir()

        def run_one_once(**kwargs):
            stop_sentinel.write_text("stop", encoding="utf-8")
            return (0, {"elapsed_s": 0.1, "downloaded": 0, "total": 0, "already": False, "downloader": "yt-dlp"})

        argv = [
            "ytaedl",
            "-f",
            str(urlfile),
            "-q",
            "-g",
            str(log_path),
            "-r",
            str(raw_dir),
            "-a",
            str(archive_dir),
            "-B",
            str(stop_sentinel),
        ]
        with patch("sys.argv", argv):
            with patch("ytaedl.downloader._run_one", side_effect=run_one_once) as mock_run:
                result = downloader.main()

        assert result == 0
        assert mock_run.call_count == 1
        archive_file = archive_dir / f"yt-{urlfile.stem}.txt"
        assert archive_file.exists()
        assert len(archive_file.read_text(encoding="utf-8").splitlines()) == 1
        assert "CONTROLLED_STOP" in log_path.read_text(encoding="utf-8")

    def test_main_existing_stop_sentinel_starts_no_urls_and_writes_no_archive(self, tmp_path):
        urlfile = tmp_path / "urls.txt"
        urlfile.write_text("https://example.com/video1\nhttps://example.com/video2\n", encoding="utf-8")
        stop_sentinel = tmp_path / "stop"
        stop_sentinel.write_text("stop", encoding="utf-8")
        log_path = tmp_path / "prog.log"
        raw_dir = tmp_path / "raw"
        archive_dir = tmp_path / "archive"
        raw_dir.mkdir()

        argv = [
            "ytaedl",
            "-f",
            str(urlfile),
            "-q",
            "-g",
            str(log_path),
            "-r",
            str(raw_dir),
            "-a",
            str(archive_dir),
            "-B",
            str(stop_sentinel),
        ]
        with patch("sys.argv", argv):
            with patch("ytaedl.downloader._run_one") as mock_run:
                result = downloader.main()

        assert result == 0
        mock_run.assert_not_called()
        archive_file = archive_dir / f"yt-{urlfile.stem}.txt"
        assert not archive_file.exists()
        assert "CONTROLLED_STOP" in log_path.read_text(encoding="utf-8")

    def test_main_archive_respects_existing_statuses(self):
        """Existing archive entries skip prior URLs and update only new ones."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write('https://example.com/video1\n')
            f.write('https://example.com/video2\n')
            temp_path = f.name

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                archive_dir = Path(tmpdir) / 'archive'
                archive_dir.mkdir()
                archive_file = archive_dir / f"yt-{Path(temp_path).stem}.txt"
                archive_file.write_text("downloaded\t1.000\t2025-09-30T09:47:55\t0.00MiB\tid1\n\n")

                with patch('sys.argv', ['ytaedl', '-f', temp_path, '--archive-dir', str(archive_dir)]):
                    with patch('ytaedl.downloader._run_one') as mock_run:
                        mock_run.return_value = (0, {'elapsed_s': 0.5, 'downloaded': 150, 'total': 150, 'already': False, 'downloader': 'yt-dlp'})
                        result = downloader.main()
                        assert result == 0
                        assert mock_run.call_count == 1
                        assert mock_run.call_args.kwargs['url_index'] == 2

                lines = archive_file.read_text().strip().splitlines()
                assert len(lines) == 2
                first_fields = lines[0].split('	')
                second_fields = lines[1].split('	')
                assert len(first_fields) == 6
                assert len(second_fields) == 6
                assert first_fields[-1] == 'https://example.com/video1'
                assert second_fields[-1] == 'https://example.com/video2'
                assert second_fields[0] == 'downloaded'
        finally:
            os.unlink(temp_path)

    def test_main_archive_skips_by_url_not_line_position(self, tmp_path):
        urlfile = tmp_path / "urls.txt"
        urlfile.write_text(
            "https://example.com/video1\nhttps://example.com/video2\n",
            encoding="utf-8",
        )
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        archive_file = archive_dir / f"yt-{urlfile.stem}.txt"
        archive_file.write_text(
            downloader._format_archive_line(
                "downloaded",
                1.0,
                "2026-05-07T04:13:23",
                0.0,
                "id2",
                "https://example.com/video2",
            )
            + "\n",
            encoding="utf-8",
        )

        argv = ["ytaedl", "-f", str(urlfile), "--archive-dir", str(archive_dir)]
        with patch("sys.argv", argv):
            with patch("ytaedl.downloader._run_one") as mock_run:
                mock_run.return_value = (
                    0,
                    {
                        "elapsed_s": 0.5,
                        "downloaded": 150,
                        "total": 150,
                        "already": False,
                        "downloader": "yt-dlp",
                    },
                )
                result = downloader.main()

        assert result == 0
        assert mock_run.call_count == 1
        assert mock_run.call_args.kwargs["url_index"] == 1
        assert mock_run.call_args.kwargs["urls"] == ["https://example.com/video1"]

    def test_main_archive_source_file_controls_archive_name(self, tmp_path):
        tmp_urlfile = tmp_path / "logs" / "tmp_urls" / "w03_166_14.txt"
        tmp_urlfile.parent.mkdir(parents=True)
        tmp_urlfile.write_text("https://example.com/video2\n", encoding="utf-8")
        source_file = tmp_path / "files" / "downloads" / "stars" / "sofi_li.txt"
        source_file.parent.mkdir(parents=True)
        source_file.write_text(
            "https://example.com/video1\nhttps://example.com/video2\n",
            encoding="utf-8",
        )
        archive_dir = tmp_path / "archive"

        argv = [
            "ytaedl",
            "-f",
            str(tmp_urlfile),
            "--archive-dir",
            str(archive_dir),
            "-O",
            str(source_file),
        ]
        with patch("sys.argv", argv):
            with patch("ytaedl.downloader._run_one") as mock_run:
                mock_run.return_value = (
                    0,
                    {
                        "elapsed_s": 0.5,
                        "downloaded": 150,
                        "total": 150,
                        "already": False,
                        "downloader": "yt-dlp",
                    },
                )
                result = downloader.main()

        assert result == 0
        assert mock_run.call_count == 1
        assert (archive_dir / "yt-sofi_li.txt").exists()
        assert not (archive_dir / "yt-w03_166_14.txt").exists()

    def test_main_archive_skips_failed_statuses(self, tmp_path):
        urlfile = tmp_path / "urls.txt"
        urlfile.write_text("https://example.com/video1\n", encoding="utf-8")
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        archive_file = archive_dir / f"yt-{urlfile.stem}.txt"
        archive_file.write_text(
            downloader._format_archive_line(
                "bad-url",
                1.0,
                "2026-05-07T04:13:23",
                0.0,
                "id1",
                "https://example.com/video1",
            )
            + "\n",
            encoding="utf-8",
        )

        argv = ["ytaedl", "-f", str(urlfile), "--archive-dir", str(archive_dir)]
        with patch("sys.argv", argv):
            with patch("ytaedl.downloader._run_one") as mock_run:
                mock_run.return_value = (
                    0,
                    {
                        "elapsed_s": 0.5,
                        "downloaded": 150,
                        "total": 150,
                        "already": False,
                        "downloader": "yt-dlp",
                    },
                )
                result = downloader.main()

        assert result == 0
        assert mock_run.call_count == 0

    def test_main_archive_records_stalled_url(self):
        """Stalled downloads are recorded in the archive."""
        with tempfile.TemporaryDirectory() as tmpdir:
            url_root = Path(tmpdir) / 'files' / 'downloads' / 'ae-stars'
            url_root.mkdir(parents=True)
            urlfile = url_root / 'stall_test.txt'
            urlfile.write_text('https://straight.aebn.com/video/123#scene-45\n')

            archive_dir = Path(tmpdir) / 'archive'
            archive_dir.mkdir()

            with patch('sys.argv', ['ytaedl', '-f', str(urlfile), '--archive-dir', str(archive_dir)]):
                with patch('ytaedl.downloader._run_one', return_value=(124, {'elapsed_s': 2.5, 'downloaded': 0, 'total': 0, 'already': False, 'downloader': 'aebndl'})):
                    with patch('ytaedl.downloader._emit_json') as mock_emit:
                        result = downloader.main()
                        assert result == 124
                        write_events = [evt for call in mock_emit.call_args_list for evt in ([call.args[0]] if call.args else []) if isinstance(evt, dict) and evt.get('event') == 'archive_write']
                        assert any(evt.get('status') == 'stalled' for evt in write_events)

            archive_file = archive_dir / 'ae-stall_test.txt'
            content = archive_file.read_text().strip().splitlines()
            assert len(content) == 1
            fields = content[0].split('\t')
            assert fields[0] == 'stalled'
            assert fields[-1] == 'https://straight.aebn.com/video/123#scene-45'

    def test_main_archive_skips_processed_urls(self):
        """Processed URLs recorded in archive files are skipped on rerun."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write('https://example.com/video1\n')
            f.write('https://example.com/video2\n')
            temp_path = f.name

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                archive_dir = Path(tmpdir) / 'archive'
                archive_dir.mkdir()

                with patch('sys.argv', ['ytaedl', '-f', temp_path, '--archive-dir', str(archive_dir)]):
                    with patch('ytaedl.downloader._run_one') as mock_run:
                        mock_run.side_effect = [
                            (0, {'elapsed_s': 0.5, 'downloaded': 100, 'total': 100, 'already': False, 'downloader': 'yt-dlp'}),
                            (0, {'elapsed_s': 0.7, 'downloaded': 200, 'total': 200, 'already': False, 'downloader': 'yt-dlp'}),
                        ]
                        result = downloader.main()
                        assert result == 0
                        assert mock_run.call_count == 2

                archive_files = list(archive_dir.glob('*.txt'))
                assert archive_files, 'archive status file should be created'
                contents = archive_files[0].read_text().strip().splitlines()
                assert len(contents) == 2
                for idx, line in enumerate(contents, 1):
                    fields = line.split('	')
                    assert len(fields) == 6
                    assert fields[-1] == [
                        'https://example.com/video1',
                        'https://example.com/video2',
                    ][idx - 1]
                    assert fields[0] in {'downloaded', 'already', 'bad-url'}

                with patch('sys.argv', ['ytaedl', '-f', temp_path, '--archive-dir', str(archive_dir)]):
                    with patch('ytaedl.downloader._run_one') as mock_run:
                        result = downloader.main()
                        assert result == 0
                        assert mock_run.called is False
        finally:
            os.unlink(temp_path)


class TestEmitJsonEncoding:
    """Verify _emit_json never raises UnicodeEncodeError for replacement chars."""

    def test_emit_json_replacement_char_does_not_raise(self, capsys):
        """A URL containing \\ufffd (the UTF-8 replacement char) must not crash _emit_json
        even when sys.stdout uses a narrow encoding like cp1252."""
        import io
        import sys

        # Simulate a cp1252 stdout that can't encode \\ufffd
        class _Cp1252Writer(io.TextIOWrapper):
            pass

        original_stdout = sys.stdout
        # We use a BytesIO wrapped in TextIOWrapper to simulate narrow encoding behaviour
        buf = io.BytesIO()
        narrow_stdout = io.TextIOWrapper(buf, encoding="cp1252", errors="strict")
        sys.stdout = narrow_stdout
        try:
            # reconfigure to utf-8 (mirrors what main() now does)
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            # This must not raise even though \\ufffd can't be encoded in cp1252
            downloader._emit_json({"event": "start", "url": "https://example.com/test�"})
            sys.stdout.flush()
        finally:
            sys.stdout = original_stdout

    def test_emit_json_ascii_safe_with_replacement_char(self):
        """_emit_json output round-trips through json.loads without data loss."""
        import io
        import json
        import sys

        buf = io.StringIO()
        original_stdout = sys.stdout
        sys.stdout = buf
        try:
            downloader._emit_json({"event": "start", "url": "https://example.com/test�"})
        finally:
            sys.stdout = original_stdout

        line = buf.getvalue().strip()
        parsed = json.loads(line)
        assert parsed["event"] == "start"
        assert "�" in parsed["url"]
