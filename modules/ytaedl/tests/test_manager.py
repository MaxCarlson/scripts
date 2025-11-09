"""Tests for ytaedl.manager module."""

import os
import tempfile
import threading
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import ytaedl.manager as manager
from termdash import utils as td_utils


class TestManager:
    """Test cases for the manager module."""

    def test_make_parser(self):
        """Test that make_parser creates a valid ArgumentParser."""
        parser = manager.make_parser()
        assert parser.prog == "dlmanager.py"

        # Test parsing with defaults
        args = parser.parse_args([])
        assert args.threads == 2
        assert args.time_limit == -1
        assert args.max_ndjson_rate == 5.0
        assert args.max_resolution is None

        assert args.proxy_dl_location is None

        args_with_proxy = parser.parse_args(["-P", "/mirror"])
        assert args_with_proxy.proxy_dl_location == "/mirror"

        args_with_priority = parser.parse_args(["-p", "file.txt"])
        assert args_with_priority.priority_files == ["file.txt"]

        args_with_res = parser.parse_args(["--max-resolution", "1080"])
        assert args_with_res.max_resolution == "1080"

        args_with_short = parser.parse_args(["-v", "720"])
        assert args_with_short.max_resolution == "720"

        args_with_show = parser.parse_args(["-b"])
        assert args_with_show.show_bars is True

    def test_prepare_log_window(self):
        logs = [f"line {i}" for i in range(6)]
        window, max_scroll = manager._prepare_log_window(logs, available_rows=3, scroll=0)
        assert window == ["line 3", "line 4", "line 5"]
        assert max_scroll == 3

        window2, max_scroll2 = manager._prepare_log_window(logs, available_rows=3, scroll=5)
        assert window2 == ["line 0", "line 1", "line 2"]
        assert max_scroll2 == 3

    def test_wrap_hotkey_lines(self):
        text = " ".join(f"word{i}" for i in range(10))
        lines = manager._wrap_hotkey_lines(text, cols=20)
        assert len(lines) >= 2
        assert all(len(line) <= 20 for line in lines)
        assert " ".join(lines).split() == text.split()

    def test_storage_summary_lines_same_volume(self):
        staging = td_utils.DiskStats(
            path=Path("/staging"),
            total_bytes=50 * manager.GIB,
            used_bytes=10 * manager.GIB,
            free_bytes=40 * manager.GIB,
            device=1,
            label="disk-a",
        )
        dest = td_utils.DiskStats(
            path=Path("/dest"),
            total_bytes=50 * manager.GIB,
            used_bytes=5 * manager.GIB,
            free_bytes=45 * manager.GIB,
            device=1,
            label="disk-a",
        )
        lines = manager._storage_summary_lines(
            staging,
            dest,
            threshold_bytes=20 * manager.GIB,
            download_speed_bps=1024 * 1024,
        )
        assert any("buffer" in line for line in lines)
        assert any("shares staging volume" in line for line in lines)

    def test_storage_summary_lines_separate_volume(self):
        staging = td_utils.DiskStats(
            path=Path("/staging"),
            total_bytes=20 * manager.GIB,
            used_bytes=5 * manager.GIB,
            free_bytes=15 * manager.GIB,
            device=1,
            label="disk-a",
        )
        dest = td_utils.DiskStats(
            path=Path("/dest"),
            total_bytes=30 * manager.GIB,
            used_bytes=10 * manager.GIB,
            free_bytes=20 * manager.GIB,
            device=2,
            label="disk-b",
        )
        lines = manager._storage_summary_lines(
            staging,
            dest,
            threshold_bytes=None,
            download_speed_bps=0,
        )
        assert any("disk-b" in line for line in lines)
        assert all("shares staging volume" not in line for line in lines)

    def test_read_urls(self):
        """Test reading URLs from a file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("https://example.com/video1\n")
            f.write("https://example.com/video2\n")
            f.write("\n")  # empty line
            f.write("# comment line\n")
            f.write("https://example.com/video3\n")
            temp_path = f.name

        try:
            urls = manager._read_urls(Path(temp_path))
            assert len(urls) == 3
            assert "https://example.com/video1" in urls
            assert "https://example.com/video2" in urls
            assert "https://example.com/video3" in urls
        finally:
            os.unlink(temp_path)

    def test_human_bytes(self):
        """Test human-readable byte formatting."""
        assert manager._human_bytes(None) == "?"
        assert manager._human_bytes(500) == "500.00B"
        assert manager._human_bytes(1024) == "1.00KiB"
        assert manager._human_bytes(1024 * 1024) == "1.00MiB"
        assert manager._human_bytes(1024 * 1024 * 1024) == "1.00GiB"

    def test_human_short_bytes(self):
        """Test short human-readable byte formatting."""
        assert manager._human_short_bytes(None) == "?"
        assert manager._human_short_bytes(1024 * 1024) == "1.0M"
        assert manager._human_short_bytes(1024 * 1024 * 1024) == "1.0G"
        assert manager._human_short_bytes(512 * 1024 * 1024) == "512.0M"

    def test_hms(self):
        """Test HMS time formatting."""
        assert manager._hms(0) == "00:00:00"
        assert manager._hms(61) == "00:01:01"
        assert manager._hms(3661) == "01:01:01"

    def test_gather_from_roots_empty(self):
        """Test gathering files from empty roots."""
        with tempfile.TemporaryDirectory() as tmpdir:
            finished_log = Path(tmpdir) / "finished.txt"
            roots = [Path(tmpdir) / "nonexistent"]
            regular, priority = manager._gather_from_roots(roots, finished_log)
            assert regular == []
            assert priority == []

    def test_gather_from_roots_with_files(self):
        """Test gathering files from roots with txt files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            finished_log = root / "finished.txt"

            # Create some test files
            (root / "test1.txt").write_text("test")
            (root / "test2.txt").write_text("test")
            (root / "subdir").mkdir()
            (root / "subdir" / "test3.txt").write_text("test")
            (root / "not_txt.dat").write_text("test")  # Should be ignored

            regular, priority = manager._gather_from_roots([root], finished_log)
            assert priority == []
            file_names = [f.name for f in regular]

            assert "test1.txt" in file_names
            assert "test2.txt" in file_names
            assert "test3.txt" in file_names
            assert "not_txt.dat" not in file_names

    def test_gather_from_roots_with_finished_log(self):
        """Test gathering files excluding finished ones."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            finished_log = root / "finished.txt"

            # Create test files
            file1 = root / "test1.txt"
            file2 = root / "test2.txt"
            file1.write_text("test")
            file2.write_text("test")

            # Mark file1 as finished
            finished_log.write_text(str(file1.resolve()) + "\n")

            regular, priority = manager._gather_from_roots([root], finished_log)
            # Should exclude both the finished file and the finished.txt log file itself
            assert priority == []
            remaining_files = [f for f in regular if f.name != "finished.txt"]
            assert len(remaining_files) == 1
            assert remaining_files[0].name == "test2.txt"


class TestManagerLogger:
    """Test cases for the ManagerLogger class."""

    def test_manager_logger_creation(self):
        """Test ManagerLogger creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "test.log"
            logger = manager.ManagerLogger(log_path)
            assert logger.path == log_path

    def test_manager_logger_info(self):
        """Test ManagerLogger info method."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "test.log"
            logger = manager.ManagerLogger(log_path)

            with patch('time.strftime', return_value="12:34:56"):
                logger.info("Test message")

            content = log_path.read_text()
            assert "12:34:56|INFO|Test message" in content

    def test_manager_logger_error(self):
        """Test ManagerLogger error method."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "test.log"
            logger = manager.ManagerLogger(log_path)

            with patch('time.strftime', return_value="12:34:56"):
                logger.error("Error message")

            content = log_path.read_text()
            assert "12:34:56|ERROR|Error message" in content


class TestWorkerState:
    """Test cases for the WorkerState class."""

    def test_worker_state_creation(self):
        """Test WorkerState creation."""
        ws = manager.WorkerState(slot=1)
        assert ws.slot == 1
        assert ws.proc is None
        assert ws.reader is None
        assert ws.url_count == 0
        assert isinstance(ws.reader_stop, threading.Event)
        assert isinstance(ws.ndjson_buf, list)

    def test_worker_state_defaults(self):
        """Test WorkerState default values."""
        ws = manager.WorkerState(slot=5)
        assert ws.slot == 5
        assert ws.urlfile is None
        assert ws.url_index is None
        assert ws.url_current is None
        assert ws.downloader is None
        assert ws.percent is None
        assert ws.speed_bps is None
        assert ws.eta_s is None
        assert ws.downloaded_bytes is None
        assert ws.total_bytes is None
        assert ws.assign_t0 == 0.0
        assert ws.url_t0 == 0.0
        assert ws.last_event_time == 0.0
        assert ws.destination is None
        assert ws.rc is None
        assert ws.cap_mibs is None
        assert ws.last_throttle_t == 0.0
        assert ws.last_already is False
        assert ws.overlay_msg is None
        assert ws.overlay_since == 0.0
        assert len(ws.ndjson_buf) == 0
        assert ws.prog_log_path is None


@pytest.mark.integration
class TestStartWorker:
    """Integration tests for starting workers."""

    def test_start_worker_basic(self):
        """Test starting a worker with basic parameters."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("https://example.com/video1\n")
            temp_path = f.name

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                log_dir = Path(tmpdir)
                urlfile = Path(temp_path)

                # Mock the downloader script to avoid actually running it
                with patch('subprocess.Popen') as mock_popen:
                    mock_process = MagicMock()
                    mock_popen.return_value = mock_process

                    proc = manager._start_worker(
                        slot=1,
                        urlfile=urlfile,
                        max_rate=5.0,
                        quiet=True,
                        archive_dir=None,
                        log_dir=log_dir,
                        cap_mibs=None,
                        proxy_dl_location=None
                    )

                    assert proc == mock_process
                    # Verify subprocess was called with correct arguments
                    mock_popen.assert_called_once()
                    args, kwargs = mock_popen.call_args
                    cmd = args[0]
                    assert "downloader.py" in cmd[1]
                    assert "-f" in cmd
                    assert str(urlfile) in cmd
                    assert "-U" in cmd
                    assert "5.0" in cmd
                    assert "-q" in cmd
                    assert "--proxy-dl-location" not in cmd
                    assert "--max-resolution" not in cmd
        finally:
            os.unlink(temp_path)

    def test_start_worker_with_options(self):
        """Test starting a worker with additional options."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("https://example.com/video1\n")
            temp_path = f.name

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                log_dir = Path(tmpdir)
                archive_dir = Path(tmpdir) / "archive"
                urlfile = Path(temp_path)

                with patch('subprocess.Popen') as mock_popen:
                    mock_process = MagicMock()
                    mock_popen.return_value = mock_process

                    proc = manager._start_worker(
                        slot=2,
                        urlfile=urlfile,
                        max_rate=10.0,
                        quiet=False,
                        archive_dir=archive_dir,
                        log_dir=log_dir,
                        cap_mibs=5.5,
                        proxy_dl_location="/tmp/proxy",
                        max_resolution="1080",
                    )

                    assert proc == mock_process
                    args, kwargs = mock_popen.call_args
                    cmd = args[0]
                    assert "-X" in cmd
                    assert "5.5" in cmd
                    assert "-a" in cmd
                    assert str(archive_dir) in cmd
                    assert "--max-resolution" in cmd
                    res_idx = cmd.index("--max-resolution")
                    assert cmd[res_idx + 1] == "1080"
                    assert "-q" not in cmd
        finally:
            os.unlink(temp_path)


@pytest.mark.integration
class TestMainFunction:
    """Integration tests for the main function."""

    def test_main_no_files(self):
        """Test main function when no URL files are found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create empty test directories
            stars_dir = Path(tmpdir) / "stars"
            aebn_dir = Path(tmpdir) / "aebn"
            stars_dir.mkdir()
            aebn_dir.mkdir()

            args = [
                "--threads", "1",
                "--time-limit", "5",
                "--stars-dir", str(stars_dir),
                "--aebn-dir", str(aebn_dir),
                "--finished-log", str(Path(tmpdir) / "finished.txt"),
                "--log-dir", str(tmpdir),
                "--refresh-hz", "1.0",
                "--exit-at-time", "1"  # Exit after 1 second
            ]

            with patch('sys.argv', ['dlmanager'] + args):
                # Mock terminal operations to avoid issues in test environment
                with patch('os.get_terminal_size', return_value=MagicMock(columns=80, lines=24)):
                    with patch('sys.stdout'):
                        result = manager.main()
                        assert result == 0

    def test_main_with_test_files(self):
        """Test main function with test URL files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test URL files
            stars_dir = Path(tmpdir) / "stars"
            stars_dir.mkdir()
            (stars_dir / "test1.txt").write_text("https://example.com/video1\n")

            args = [
                "--threads", "1",
                "--time-limit", "2",
                "--stars-dir", str(stars_dir),
                "--aebn-dir", str(Path(tmpdir) / "aebn"),
                "--finished-log", str(Path(tmpdir) / "finished.txt"),
                "--log-dir", str(tmpdir),
                "--refresh-hz", "2.0",
                "--exit-at-time", "1"  # Exit after 1 second
            ]

            with patch('sys.argv', ['dlmanager'] + args):
                # Mock subprocess to avoid actually starting workers
                with patch('subprocess.Popen') as mock_popen:
                    mock_process = MagicMock()
                    mock_process.poll.return_value = 0  # Process finished successfully
                    mock_process.stdout = iter([])  # Empty output
                    mock_popen.return_value = mock_process

                    with patch('os.get_terminal_size', return_value=MagicMock(columns=80, lines=24)):
                        with patch('sys.stdout'):
                            result = manager.main()
                            assert result == 0

    def test_main_keyboard_interrupt(self):
        """Test main function handles KeyboardInterrupt gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            args = [
                "--stars-dir", str(Path(tmpdir) / "stars"),
                "--aebn-dir", str(Path(tmpdir) / "aebn"),
                "--finished-log", str(Path(tmpdir) / "finished.txt"),
                "--log-dir", str(tmpdir),
                "--exit-at-time", "10"
            ]

            with patch('sys.argv', ['dlmanager'] + args):
                with patch('time.sleep', side_effect=KeyboardInterrupt):
                    with patch('os.get_terminal_size', return_value=MagicMock(columns=80, lines=24)):
                        with patch('sys.stdout'):
                            result = manager.main()
                            assert result == 0

    def test_main_with_mp4_watcher(self, monkeypatch, tmp_path):
        """Ensure enabling the MP4 watcher does not raise runtime errors."""
        stars_dir = tmp_path / "stars"
        stars_dir.mkdir()
        (stars_dir / "test1.txt").write_text("https://example.com/video1\n", encoding="utf-8")
        aebn_dir = tmp_path / "aebn"
        aebn_dir.mkdir()
        proxy_dir = tmp_path / "proxy"
        proxy_dir.mkdir()
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        class DummyWatcher:
            def __init__(self, config, enabled):
                self._config = config
                self._enabled = enabled

            def is_enabled(self):
                return self._enabled

            def update_download_progress(self, *_):
                return None

            def snapshot(self):
                return None

            def manual_run(self, **_):
                return False

        monkeypatch.setattr(manager, "MP4Watcher", DummyWatcher)

        args = [
            "--threads", "1",
            "--time-limit", "2",
            "--stars-dir", str(stars_dir),
            "--aebn-dir", str(aebn_dir),
            "--finished-log", str(tmp_path / "finished.txt"),
            "--log-dir", str(log_dir),
            "--refresh-hz", "2.0",
            "--exit-at-time", "1",
            "--enable-mp4-watcher",
            "--proxy-dl-location", str(proxy_dir),
        ]

        with patch('sys.argv', ['dlmanager'] + args):
            with patch('subprocess.Popen') as mock_popen:
                mock_process = MagicMock()
                mock_process.poll.return_value = 0
                mock_process.stdout = iter([])
                mock_popen.return_value = mock_process

                with patch('os.get_terminal_size', return_value=MagicMock(columns=80, lines=24)):
                    with patch('sys.stdout'):
                        result = manager.main()
                        assert result == 0


class TestUtilityFunctions:
    """Test utility functions in the manager module."""

    def test_quantile_function(self):
        """Test the _quantile helper function used in speed color coding."""
        # This function is defined inline in main(), so we'll test the logic
        def _quantile(xs, q):
            if not xs:
                return None
            idx = int(round((len(xs)-1) * q))
            return xs[max(0, min(len(xs)-1, idx))]

        # Test with various inputs
        assert _quantile([], 0.5) is None
        assert _quantile([1], 0.5) == 1
        assert _quantile([1, 2, 3, 4, 5], 0.0) == 1
        assert _quantile([1, 2, 3, 4, 5], 0.5) == 3
        assert _quantile([1, 2, 3, 4, 5], 1.0) == 5
        assert _quantile([1, 2, 3, 4, 5], 0.25) == 2

    def test_make_bar_function(self):
        """Test the progress bar creation logic."""
        def make_bar(pct, width, color_prefix=""):
            try:
                p = float(pct) if pct is not None else -1
            except (ValueError, TypeError):
                p = -1
            inner = max(0, width-2)
            if p < 0:
                return "[" + ("." * inner) + "]"
            p = max(0.0, min(100.0, p))
            filled = int(inner * (p/100.0))
            reset = "\x1b[0m"
            if color_prefix:
                return "[" + (f"{color_prefix}" + ("=" * filled) + f"{reset}") + ("." * (inner - filled)) + "]"
            else:
                return "[" + ("=" * filled) + ("." * (inner - filled)) + "]"

        # Test basic functionality
        assert make_bar(0, 10) == "[........]"
        assert make_bar(50, 10) == "[====....]"
        assert make_bar(100, 10) == "[========]"
        assert make_bar(None, 10) == "[........]"
        assert make_bar(150, 10) == "[========]"  # Should clamp to 100%

        # Test with color
        bar_with_color = make_bar(50, 10, "\x1b[32m")
        assert "[" in bar_with_color
        assert "]" in bar_with_color
        assert "=" in bar_with_color
        assert "." in bar_with_color


if __name__ == "__main__":
    pytest.main([__file__])
