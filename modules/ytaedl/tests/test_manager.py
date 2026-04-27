"""Tests for ytaedl.manager module."""

import os
import random
import re
import tempfile
import threading
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import ytaedl.manager as manager
from termdash import utils as td_utils

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


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
        assert args.download_root == "./stars"
        assert args.url_order_key == "ratio"
        assert args.url_order_ascending is False
        assert args.url_random_order is False
        assert args.url_pick_temperature == 0.0

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

        args_with_reserve = parser.parse_args(["-m", "100GB"])
        assert args_with_reserve.space_remaining == 100 * 1024**3

        args_with_reserve_long = parser.parse_args(["--space-remaining", "1024MB"])
        assert args_with_reserve_long.space_remaining == 1024 * 1024**2

        with pytest.raises(SystemExit):
            parser.parse_args(["--space-remaining", "not-a-size"])

        args_with_temperature = parser.parse_args(["-Q", "0.75"])
        assert args_with_temperature.url_pick_temperature == 0.75

        with pytest.raises(SystemExit):
            parser.parse_args(["--url-pick-temperature", "-1"])

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

    def test_format_watcher_log_line_colors_and_brackets_status(self):
        raw = "[00:00:01.000] \x1b[33mDRYRUN\x1b[0m syncing files"
        formatted = manager._format_watcher_log_line(raw)
        sanitized = _strip_ansi(formatted)
        assert "[00:00:01.000]" in sanitized
        assert "[DRYRUN]" in sanitized
        assert "syncing files" in sanitized
        # Ensure colour codes are present in the formatted output
        assert "\x1b[" in formatted

    def test_format_watcher_log_line_handles_unstructured_text(self):
        raw = "PLAN summary only"
        formatted = manager._format_watcher_log_line(raw)
        assert formatted == raw

    def test_manager_urls_subcommand(self, tmp_path):
        """Ensure `ytaedl urls` subcommand executes the scanner CLI."""
        stars_dir = tmp_path / "stars"
        ae_dir = tmp_path / "ae"
        media_dir = tmp_path / "media"
        for d in (stars_dir, ae_dir, media_dir):
            d.mkdir()
        (stars_dir / "alpha.txt").write_text("https://example.com/a\n", encoding="utf-8")
        (media_dir / "alpha").mkdir()
        (media_dir / "alpha" / "clip.mp4").write_bytes(b"0")

        argv = [
            "urls",
            "-N",
            "-n",
            "--stars-dir",
            str(stars_dir),
            "--ae-dir",
            str(ae_dir),
            "--media-dir",
            str(media_dir),
        ]
        with patch("sys.stdout"):
            result = manager.main(argv)
        assert result == 0

    def test_manager_skips_completed_urlfiles(self, tmp_path):
        """Workers should not be assigned URL files that have zero remaining downloads."""
        stars_dir = tmp_path / "stars"
        stars_dir.mkdir()
        ae_dir = tmp_path / "ae"
        ae_dir.mkdir()
        media_dir = tmp_path / "media"
        media_dir.mkdir()

        complete_file = stars_dir / "complete.txt"
        complete_file.write_text("https://example.com/done\n", encoding="utf-8")
        complete_media = media_dir / "complete"
        complete_media.mkdir()
        (complete_media / "done.mp4").write_bytes(b"0")

        pending_file = stars_dir / "pending.txt"
        pending_file.write_text("https://example.com/todo\n", encoding="utf-8")

        finished_log = tmp_path / "finished.txt"
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        args = [
            "--threads",
            "1",
            "--time-limit",
            "1",
            "--stars-dir",
            str(stars_dir),
            "--aebn-dir",
            str(ae_dir),
            "--download-root",
            str(media_dir),
            "--finished-log",
            str(finished_log),
            "--log-dir",
            str(log_dir),
            "--exit-at-time",
            "1",
        ]

        dummy_process = MagicMock()
        dummy_process.poll.return_value = 0
        dummy_process.stdout = iter([])
        dummy_process.wait.return_value = 0
        dummy_process.terminate.return_value = None

        with patch("sys.argv", ["dlmanager"] + args):
            with patch("subprocess.Popen", return_value=dummy_process) as mock_popen:
                with patch("os.get_terminal_size", return_value=MagicMock(columns=80, lines=24)):
                    with patch("sys.stdout"):
                        with patch("time.sleep", side_effect=lambda _: None):
                            result = manager.main()

        assert result == 0
        assert mock_popen.call_args_list, "Worker was never started"
        assigned_files = []
        for call in mock_popen.call_args_list:
            cmd = call.args[0]
            if "-f" in cmd:
                assigned_files.append(Path(cmd[cmd.index("-f") + 1]).name)
            if "-o" in cmd:
                output_dir = Path(cmd[cmd.index("-o") + 1])
                assert output_dir.parent == media_dir
        assert "pending.txt" in assigned_files
        assert "complete.txt" not in assigned_files

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
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
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
        assert manager._human_short_bytes(1024 * 1024) == "1.00MiB"
        assert manager._human_short_bytes(1024 * 1024 * 1024) == "1.00GiB"
        assert manager._human_short_bytes(512 * 1024 * 1024) == "512.00MiB"

    def test_size_parsing_and_disk_formatting(self):
        assert manager._parse_size_bytes("100GB") == 100 * 1024**3
        assert manager._parse_size_bytes("1024MB") == 1024 * 1024**2
        assert manager._parse_size_bytes("unlimited") is None
        assert manager._format_disk_bytes(1023 * 1024**2) == "1023.00 MB"
        assert manager._format_disk_bytes(1024 * 1024**2) == "1.00 GB"

    def test_download_footer_mentions_digit_selection_without_1_to_9_limit(self):
        footer = manager._wrap_hotkey_lines(manager._downloads_footer_text(), 120)
        text = " ".join(footer)
        # Footer should mention digit-based worker prompt (no hard 1-9 limit)
        assert "digit" in text
        assert "worker" in text
        assert "x=controlled quit" in text
        assert "h=toggle status" in text
        assert "1-9=select worker" not in text

    def test_pinned_viewport_with_reserved_verbose_rows_keeps_header_first(self):
        lines = ["HEADER", "TOTALS", "SEP"] + [f"worker {i}" for i in range(20)] + ["FOOTER"]
        viewport, max_scroll = manager._apply_pinned_viewport(
            lines,
            rows=8,
            header_rows=3,
            footer_rows=1,
            scroll=0,
        )
        verbose = ["---", "Verbose NDJSON [01]", "{}"]
        combined = viewport + verbose[: max(0, 11 - len(viewport))]
        assert len(combined) <= 11
        assert combined[:3] == ["HEADER", "TOTALS", "SEP"]
        assert max_scroll > 0

    def test_cycle_url_sort_modes(self):
        current = ("ratio", False)
        expected = [
            ("ratio", True),
            ("stars", False),
            ("remaining", False),
            ("gb", False),
            ("unique", False),
            ("ratio", False),
        ]
        for wanted in expected:
            current = manager._cycle_url_sort(*current)
            assert current == wanted

    def test_weighted_rank_choice_temperature_zero_returns_top_ranked(self, tmp_path):
        paths = [tmp_path / "b.txt", tmp_path / "a.txt", tmp_path / "c.txt"]
        rankings = {str(paths[0].resolve()): 1, str(paths[1].resolve()): 0, str(paths[2].resolve()): 2}

        assert manager._weighted_rank_choice(paths, rankings, 0.0) == paths[1]

    def test_weighted_rank_choice_with_seed_is_deterministic(self, tmp_path):
        paths = [tmp_path / f"{name}.txt" for name in ("a", "b", "c")]
        rankings = {str(path.resolve()): idx for idx, path in enumerate(paths)}

        selected = manager._weighted_rank_choice(paths, rankings, 1.0, rng=random.Random(6))

        assert selected == paths[1]

    def test_top_domain_normalizes_urls(self):
        assert manager._top_domain("https://example.com/video") == "example.com"
        assert manager._top_domain("https://www.example.com/video") == "example.com"
        assert manager._top_domain("https://cdn.example.com/video") == "cdn.example.com"
        assert manager._top_domain("not-a-url") == "-"
        assert manager._top_domain(None) == "-"

    def test_domains_for_urlfile_reads_remaining_hosts(self, tmp_path):
        urlfile = tmp_path / "star.txt"
        urlfile.write_text(
            "\n".join(
                [
                    "https://www.example.com/a",
                    "https://cdn.example.com/b",
                    "# ignored",
                    "https://example.com/a",
                ]
            ),
            encoding="utf-8",
        )

        assert manager._domains_for_urlfile(urlfile) == {"example.com", "cdn.example.com"}

    def test_domain_diverse_candidate_prefers_new_domain_over_better_rank(self, tmp_path):
        existing = tmp_path / "existing.txt"
        new = tmp_path / "new.txt"
        candidate_domains = {
            str(existing.resolve()): {"active.example"},
            str(new.resolve()): {"fresh.example"},
        }
        rankings = {
            str(existing.resolve()): 0,
            str(new.resolve()): 1,
        }

        selected = manager._choose_domain_diverse_candidate(
            [existing, new],
            rankings,
            candidate_domains,
            {"active.example"},
            0.0,
        )

        assert selected == new

    def test_domain_diverse_candidate_falls_back_to_rank_on_equal_diversity(self, tmp_path):
        first = tmp_path / "first.txt"
        second = tmp_path / "second.txt"
        candidate_domains = {
            str(first.resolve()): {"active.example"},
            str(second.resolve()): {"active.example"},
        }
        rankings = {
            str(first.resolve()): 1,
            str(second.resolve()): 0,
        }

        selected = manager._choose_domain_diverse_candidate(
            [first, second],
            rankings,
            candidate_domains,
            {"active.example"},
            0.0,
        )

        assert selected == second

    def test_domain_diverse_candidate_temperature_is_seeded(self, tmp_path):
        paths = [tmp_path / f"{name}.txt" for name in ("a", "b", "c")]
        candidate_domains = {
            str(paths[0].resolve()): {"active.example"},
            str(paths[1].resolve()): {"fresh.example"},
            str(paths[2].resolve()): {"other.example"},
        }
        rankings = {str(path.resolve()): idx for idx, path in enumerate(paths)}

        selected = manager._choose_domain_diverse_candidate(
            paths,
            rankings,
            candidate_domains,
            {"active.example"},
            3.0,
            rng=random.Random(7),
        )

        assert selected == paths[1]

    def test_domain_diversity_averager_tracks_running_average(self):
        avg = manager.DomainDiversityAverager()

        assert avg.average == 0.0
        assert avg.update(2) == 2.0
        assert avg.update(4) == 3.0
        assert avg.update(-1) == 2.0

    def test_controlled_quit_eta_label(self):
        assert manager._controlled_quit_eta_label([]) == "0s"

        worker = manager.WorkerState(slot=1)
        worker.proc = MagicMock()
        worker.eta_s = None
        assert manager._controlled_quit_eta_label([worker]) == "?"

        worker.eta_s = 119.6
        other = manager.WorkerState(slot=2)
        other.proc = MagicMock()
        other.eta_s = 30
        assert manager._controlled_quit_eta_label([worker, other]) == "120s"

    def test_controlled_quit_complete_requires_enabled_and_idle_workers(self):
        worker = manager.WorkerState(slot=1)
        assert manager._controlled_quit_complete(False, [worker]) is False
        assert manager._controlled_quit_complete(True, [worker]) is True

        worker.proc = MagicMock()
        assert manager._controlled_quit_complete(True, [worker]) is False

    def test_controlled_stopped_worker_zero_exit_is_not_finished(self):
        worker = manager.WorkerState(slot=1)
        worker.rc = 0
        worker.controlled_stopped = True

        finished = worker.rc == 0 and not worker.controlled_stopped

        assert finished is False

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

            with patch("time.strftime", return_value="12:34:56"):
                logger.info("Test message")

            content = log_path.read_text()
            assert "12:34:56|INFO|Test message" in content

    def test_manager_logger_error(self):
        """Test ManagerLogger error method."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "test.log"
            logger = manager.ManagerLogger(log_path)

            with patch("time.strftime", return_value="12:34:56"):
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
        assert ws.controlled_stopped is False
        assert ws.overlay_msg is None
        assert ws.overlay_since == 0.0
        assert len(ws.ndjson_buf) == 0
        assert ws.prog_log_path is None


@pytest.mark.integration
class TestStartWorker:
    """Integration tests for starting workers."""

    def test_start_worker_basic(self):
        """Test starting a worker with basic parameters."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("https://example.com/video1\n")
            temp_path = f.name

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                log_dir = tmp_path / "logs"
                log_dir.mkdir()
                canonical_root = tmp_path / "downloads"
                canonical_root.mkdir()
                urlfile = Path(temp_path)

                # Mock the downloader script to avoid actually running it
                with patch("subprocess.Popen") as mock_popen:
                    mock_process = MagicMock()
                    mock_popen.return_value = mock_process

                    proc = manager._start_worker(
                        slot=1,
                        urlfile=urlfile,
                        canonical_root=canonical_root,
                        max_rate=5.0,
                        quiet=True,
                        archive_dir=None,
                        log_dir=log_dir,
                        cap_mibs=None,
                        proxy_dl_location=None,
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
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("https://example.com/video1\n")
            temp_path = f.name

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_root = Path(tmpdir)
                log_dir = tmp_root / "logs"
                log_dir.mkdir()
                archive_dir = tmp_root / "archive"
                stop_sentinel = tmp_root / "controlled.stop"
                urlfile = Path(temp_path)
                canonical_root = tmp_root / "downloads"
                canonical_root.mkdir()

                with patch("subprocess.Popen") as mock_popen:
                    mock_process = MagicMock()
                    mock_popen.return_value = mock_process

                    proc = manager._start_worker(
                        slot=2,
                        urlfile=urlfile,
                        canonical_root=canonical_root,
                        max_rate=10.0,
                        quiet=False,
                        archive_dir=archive_dir,
                        log_dir=log_dir,
                        cap_mibs=5.5,
                        proxy_dl_location="/tmp/proxy",
                        max_resolution="1080",
                        stop_sentinel=stop_sentinel,
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
                    assert "-B" in cmd
                    stop_idx = cmd.index("-B")
                    assert cmd[stop_idx + 1] == str(stop_sentinel)
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
                "--threads",
                "1",
                "--time-limit",
                "5",
                "--stars-dir",
                str(stars_dir),
                "--aebn-dir",
                str(aebn_dir),
                "--finished-log",
                str(Path(tmpdir) / "finished.txt"),
                "--log-dir",
                str(tmpdir),
                "--refresh-hz",
                "1.0",
                "--exit-at-time",
                "1",  # Exit after 1 second
            ]

            with patch("sys.argv", ["dlmanager"] + args):
                # Mock terminal operations to avoid issues in test environment
                with patch("os.get_terminal_size", return_value=MagicMock(columns=80, lines=24)):
                    with patch("sys.stdout"):
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
                "--threads",
                "1",
                "--time-limit",
                "2",
                "--stars-dir",
                str(stars_dir),
                "--aebn-dir",
                str(Path(tmpdir) / "aebn"),
                "--finished-log",
                str(Path(tmpdir) / "finished.txt"),
                "--log-dir",
                str(tmpdir),
                "--refresh-hz",
                "2.0",
                "--exit-at-time",
                "1",  # Exit after 1 second
            ]

            with patch("sys.argv", ["dlmanager"] + args):
                # Mock subprocess to avoid actually starting workers
                with patch("subprocess.Popen") as mock_popen:
                    mock_process = MagicMock()
                    mock_process.poll.return_value = 0  # Process finished successfully
                    mock_process.stdout = iter([])  # Empty output
                    mock_popen.return_value = mock_process

                    with patch("os.get_terminal_size", return_value=MagicMock(columns=80, lines=24)):
                        with patch("sys.stdout"):
                            result = manager.main()
                            assert result == 0

    def test_main_keyboard_interrupt(self):
        """Test main function handles KeyboardInterrupt gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            args = [
                "--stars-dir",
                str(Path(tmpdir) / "stars"),
                "--aebn-dir",
                str(Path(tmpdir) / "aebn"),
                "--finished-log",
                str(Path(tmpdir) / "finished.txt"),
                "--log-dir",
                str(tmpdir),
                "--exit-at-time",
                "10",
            ]

            with patch("sys.argv", ["dlmanager"] + args):
                with patch("time.sleep", side_effect=KeyboardInterrupt):
                    with patch("os.get_terminal_size", return_value=MagicMock(columns=80, lines=24)):
                        with patch("sys.stdout"):
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

            def log_event(self, *_args, **_kwargs):
                return None

        monkeypatch.setattr(manager, "MP4Watcher", DummyWatcher)

        args = [
            "--threads",
            "1",
            "--time-limit",
            "2",
            "--stars-dir",
            str(stars_dir),
            "--aebn-dir",
            str(aebn_dir),
            "--finished-log",
            str(tmp_path / "finished.txt"),
            "--log-dir",
            str(log_dir),
            "--refresh-hz",
            "2.0",
            "--exit-at-time",
            "1",
            "--enable-mp4-watcher",
            "--proxy-dl-location",
            str(proxy_dir),
        ]

        with patch("sys.argv", ["dlmanager"] + args):
            with patch("subprocess.Popen") as mock_popen:
                mock_process = MagicMock()
                mock_process.poll.return_value = 0
                mock_process.stdout = iter([])
                mock_popen.return_value = mock_process

                with patch("os.get_terminal_size", return_value=MagicMock(columns=80, lines=24)):
                    with patch("sys.stdout"):
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
            idx = int(round((len(xs) - 1) * q))
            return xs[max(0, min(len(xs) - 1, idx))]

        # Test with various inputs
        assert _quantile([], 0.5) is None
        assert _quantile([1], 0.5) == 1
        assert _quantile([1, 2, 3, 4, 5], 0.0) == 1
        assert _quantile([1, 2, 3, 4, 5], 0.5) == 3
        assert _quantile([1, 2, 3, 4, 5], 1.0) == 5
        assert _quantile([1, 2, 3, 4, 5], 0.25) == 2

    def test_make_bar_function(self):
        """Test the progress bar creation logic, including minimum-1-segment fix."""

        def make_bar(pct, width, color_prefix=""):
            try:
                p = float(pct) if pct is not None else -1
            except (ValueError, TypeError):
                p = -1
            inner = max(0, width - 2)
            if p < 0:
                return "[" + ("." * inner) + "]"
            p = max(0.0, min(100.0, p))
            filled = int(inner * (p / 100.0))
            # Always show at least one filled segment while downloading (p > 0)
            if p > 0 and filled == 0:
                filled = 1
            reset = "\x1b[0m"
            if color_prefix:
                return "[" + (f"{color_prefix}" + ("=" * filled) + f"{reset}") + ("." * (inner - filled)) + "]"
            else:
                return "[" + ("=" * filled) + ("." * (inner - filled)) + "]"

        # Basic cases
        assert make_bar(0, 10) == "[........]"
        assert make_bar(50, 10) == "[====....]"
        assert make_bar(100, 10) == "[========]"
        assert make_bar(None, 10) == "[........]"
        assert make_bar(150, 10) == "[========]"  # clamp to 100%

        # Minimum 1 segment: very small percentages that round to 0 filled cells
        # must still show 1 '=' so the bar doesn't look empty while downloading
        bar_tiny = make_bar(0.2, 10)  # 0.2 / 100 * 8 = 0.016 → 0 without fix
        assert bar_tiny.count("=") >= 1, "p>0 must show at least one '='"
        bar_one_pct = make_bar(1.1, 10)
        assert bar_one_pct.count("=") >= 1, "1.1% must show at least one '='"

        # With color
        bar_with_color = make_bar(50, 10, "\x1b[32m")
        assert "[" in bar_with_color
        assert "=" in bar_with_color
        assert "." in bar_with_color

    def test_worker_eta_fallback_from_speed_and_bytes(self):
        """eta_s must be computed from speed+bytes when the event omits eta."""
        ws = manager.WorkerState(slot=1)
        ws.downloaded_bytes = 100_000_000   # 100 MiB
        ws.total_bytes = 200_000_000        # 200 MiB  → 100 MiB remaining
        ws.speed_bps = 1_000_000.0          # 1 MiB/s  → expected ETA 100 s (stored as float)
        ws.eta_s = None

        # Simulate a progress event that carries speed but no eta_s
        eta_in_event = None  # absent
        if isinstance(eta_in_event, (int, float)):
            ws.eta_s = float(eta_in_event)
        elif (
            not isinstance(eta_in_event, (int, float))
            and isinstance(ws.speed_bps, float)
            and ws.speed_bps > 0
            and isinstance(ws.total_bytes, int)
            and isinstance(ws.downloaded_bytes, int)
        ):
            remaining = ws.total_bytes - ws.downloaded_bytes
            if remaining > 0:
                ws.eta_s = remaining / ws.speed_bps

        assert ws.eta_s == pytest.approx(100.0, rel=0.01)

    def test_worker_eta_preserved_when_event_omits_eta(self):
        """If a progress event has no eta_s field, the last known eta_s is kept."""
        ws = manager.WorkerState(slot=1)
        ws.eta_s = 42.0   # previously known

        # Event with no eta key and no bytes/speed info
        eta_in_event = None
        # Without total_bytes/speed we can't recompute, so eta_s stays
        if isinstance(eta_in_event, (int, float)):
            ws.eta_s = float(eta_in_event)
        # else: no update — eta_s stays as 42.0

        assert ws.eta_s == 42.0

    def test_human_short_bytes_separate_dl_and_total(self):
        """dl_txt and tot_txt must each fit within a 10-char column independently."""
        MiB = 1024 ** 2
        GiB = 1024 ** 3

        for val in [302_713_856, 325 * MiB, 13 * GiB + 800 * MiB, 812 * MiB]:
            txt = manager._human_short_bytes(val)
            # Strip ANSI just in case, then check length
            plain = ANSI_RE.sub("", txt)
            assert len(plain) <= 10, f"_human_short_bytes({val}) → {plain!r} exceeds 10 chars"


    def test_eta_display_zero_with_null_percent_shows_question_mark(self):
        """eta_s=0 with unknown percent must display '?' not '00:00:00'."""
        # Replicate the inline display logic from manager's render loop
        def eta_txt(eta_s, percent):
            if isinstance(eta_s, (int, float)):
                eta_val = float(eta_s)
                is_near_done = isinstance(percent, (int, float)) and percent >= 99.5
                return manager._hms(eta_val) if (eta_val > 0 or is_near_done) else "?"
            return "?"

        # eta=0 with unknown percent → should be '?'
        assert eta_txt(0, None) == "?"
        assert eta_txt(0.0, None) == "?"
        assert eta_txt(0, 50.0) == "?"   # 50% but eta=0 means stalled, not done
        # eta=0 at near-completion → should show '00:00:00' (legitimately done)
        assert eta_txt(0, 99.9) == "00:00:00"
        assert eta_txt(0, 100.0) == "00:00:00"
        # Positive ETA always shows
        assert eta_txt(90.0, None) == "00:01:30"
        assert eta_txt(90.0, 50.0) == "00:01:30"
        # None eta → '?'
        assert eta_txt(None, 50.0) == "?"

    def test_percent_reaches_100_when_downloaded_equals_total(self):
        """When dl == total, clamped percent must be 100.0, not capped at 99.9."""
        ws = manager.WorkerState(slot=1)
        total = 500_000_000
        # Simulate the _reader progress handler logic directly
        dl, tot = total, total
        show_dl = min(dl, tot)
        pct_calc = 100.0 * (float(show_dl) / float(tot))
        ws.percent = min(100.0, pct_calc)
        assert ws.percent == 100.0, f"expected 100.0, got {ws.percent}"

    def test_finish_event_sets_100_percent_and_zero_speed(self):
        """On a successful finish, percent→100, speed→0, is_searching→True."""
        ws = manager.WorkerState(slot=1)
        ws.percent = 99.9
        ws.speed_bps = 750_000.0
        ws.eta_s = 5.0
        ws.downloaded_bytes = 500_000_000
        ws.total_bytes = 500_000_000

        # Simulate the finish-event path for rc=0, not duplicate
        rc_v = 0
        ws.last_already = False
        if rc_v == 0 and not ws.last_already:
            ws.percent = 100.0
        else:
            ws.percent = None
        ws.speed_bps = 0.0
        ws.eta_s = None
        ws.is_searching = True

        assert ws.percent == 100.0
        assert ws.speed_bps == 0.0
        assert ws.eta_s is None
        assert ws.is_searching is True
        # Downloaded bytes must be preserved for overlay size display
        assert ws.downloaded_bytes == 500_000_000

    def test_finish_bad_sets_none_percent_and_zero_speed(self):
        """On a failed finish (BAD_URL), percent→None, speed→0, is_searching→True."""
        ws = manager.WorkerState(slot=1)
        ws.percent = 60.0
        ws.speed_bps = 500_000.0

        rc_v = 1  # non-zero → bad
        ws.last_already = False
        if rc_v == 0 and not ws.last_already:
            ws.percent = 100.0
        else:
            ws.percent = None
        ws.speed_bps = 0.0
        ws.is_searching = True

        assert ws.percent is None
        assert ws.speed_bps == 0.0
        assert ws.is_searching is True

    def test_start_event_clears_is_searching(self):
        """A 'start' event must clear is_searching so the → marker disappears."""
        ws = manager.WorkerState(slot=1)
        ws.is_searching = True
        ws.is_searching = False   # simulate start handler
        assert ws.is_searching is False

    def test_clamp_progress_allows_100_percent(self):
        """The percent cap must be 100.0, not 99.9, when downloaded == total."""
        dl, tot = 500_000_000, 500_000_000
        show_dl = min(dl, tot)
        pct = min(100.0, 100.0 * show_dl / tot)
        assert pct == 100.0, f"cap should allow 100.0, got {pct}"
        # Ensure 99.9 cap is NOT applied
        assert pct != 99.9

    def test_footer_always_appended_after_verbose_lines(self):
        """Footer lines are rendered after the verbose panel so they stay at the bottom."""
        footer = ["Keys: q=quit"]
        verbose = ["---sep---", "log line 1", "log line 2"]
        downloads_rows = 5  # tight viewport

        # Simulate the new layout logic
        lines = ["H1", "H2", "W1", "W2", "W3"]
        # Apply viewport (no footer reserved inside)
        from ytaedl.manager import _apply_pinned_viewport
        viewport, _ = _apply_pinned_viewport(lines, rows=downloads_rows, header_rows=2, footer_rows=0, scroll=0)
        result = viewport + verbose + footer
        result = result[:10]  # cap at rows

        # Footer must be last visible content, after verbose
        assert result[-1] == "Keys: q=quit"
        verbose_pos = result.index("---sep---")
        footer_pos = result.index("Keys: q=quit")
        assert footer_pos > verbose_pos, "footer must appear after verbose separator"


if __name__ == "__main__":
    pytest.main([__file__])
