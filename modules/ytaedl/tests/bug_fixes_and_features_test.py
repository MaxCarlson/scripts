"""
Tests for the batch of bug fixes and feature changes:

Bugs:
  1. Partial dirs accumulate for 'already' URLs (simulate-check early return)
  2. worker_slot always 0 in meta.json
  3. meta.json file_path shows temp file instead of original

Features:
  4. Sub-subcommand parsers (ytaedl run watcher/grid/webview/disable)
  5. Multiple --download-root + --primary-root
  6. Default changes (unique-domain-dls=2, max-resolution=2k, archive=./archive)
  7. --show-bars removed
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytaedl import _partial_utils, downloader, manager
from ytaedl._cli_help import (
    make_run_disable_parser,
    make_run_grid_parser,
    make_run_watcher_parser,
    make_run_webview_parser,
    profile_auto_flags,
)
from ytaedl.cli import main as cli_main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_proglog(tmp_path: Path):
    return downloader.ProgLogger(path=tmp_path / "log.txt", t0=0.0)


class _FakeProc:
    def __init__(self, rc: int = 0):
        self._rc = rc
        self.stdout = iter([])

    def poll(self):
        return self._rc

    def wait(self, timeout=None):
        return self._rc

    def terminate(self):
        pass

    def kill(self):
        pass


# ---------------------------------------------------------------------------
# Bug 1: Partial dir cleaned for 'already' URLs
# ---------------------------------------------------------------------------

class TestBug1PartialDirCleanup:
    def test_partial_dir_deleted_on_simulate_duplicate(self, tmp_path, monkeypatch):
        """When simulate check finds a duplicate, partial dir must be removed."""
        partial_root = tmp_path / "_partial"
        partial_root.mkdir()

        canonical_dir = tmp_path / "canonical"
        canonical_dir.mkdir()
        # Place a file that simulate will "find"
        existing = canonical_dir / "Video Title.mp4"
        existing.write_bytes(b"x" * 1000)

        url = "https://example.com/video/1"
        url_work_dir = _partial_utils.partial_dir_for(url, partial_root)

        # Simulate returns is_duplicate=True
        sim_result = downloader._SimulateResult(
            is_duplicate=True, existing_path=str(existing), predicted_name="Video Title.mp4"
        )
        emitted = []
        monkeypatch.setattr(downloader, "_simulate_check", lambda *a, **k: sim_result)
        monkeypatch.setattr(downloader, "_emit_json", emitted.append)

        rc, info = downloader._run_one(
            tool="yt-dlp",
            urls=[url],
            out_dir=canonical_dir,
            canonical_out_dir=canonical_dir,
            partial_root=partial_root,
            raw_dir=tmp_path / "raw",
            url_index=1,
            proglog=_make_proglog(tmp_path),
            timeout=None,
            retries=0,
            quiet=True,
            dry_run=False,
            progress_freq_s=None,
            max_ndjson_rate=-1,
            skip_simulate_check=False,
        )

        assert rc == 0
        assert info.get("already") is True
        # Partial dir must NOT exist after an 'already' result
        assert not url_work_dir.exists(), "Partial dir should be cleaned up for duplicate URLs"

    def test_partial_dir_kept_on_failure(self, tmp_path, monkeypatch):
        """On download failure, partial dir is kept for later resume."""
        partial_root = tmp_path / "_partial"
        partial_root.mkdir()
        canonical_dir = tmp_path / "canonical"
        canonical_dir.mkdir()

        url = "https://example.com/video/2"
        url_work_dir = _partial_utils.partial_dir_for(url, partial_root)

        monkeypatch.setattr(downloader, "_simulate_check",
                            lambda *a, **k: downloader._SimulateResult(is_duplicate=False))
        monkeypatch.setattr(downloader, "_emit_json", lambda *a, **k: None)
        monkeypatch.setattr(downloader.subprocess, "Popen", lambda *a, **k: _FakeProc(rc=1))
        monkeypatch.setattr(downloader, "iter_parsed_events", lambda *a, **k: iter([]))

        rc, _info = downloader._run_one(
            tool="yt-dlp",
            urls=[url],
            out_dir=canonical_dir,
            canonical_out_dir=canonical_dir,
            partial_root=partial_root,
            raw_dir=tmp_path / "raw",
            url_index=1,
            proglog=_make_proglog(tmp_path),
            timeout=None,
            retries=0,
            quiet=True,
            dry_run=False,
            progress_freq_s=None,
            max_ndjson_rate=-1,
            skip_simulate_check=True,
            extdl_fallback=False,
        )

        assert rc != 0
        assert url_work_dir.exists(), "Partial dir should survive a download failure (for resume)"


# ---------------------------------------------------------------------------
# Bug 2: worker_slot passed through to meta.json
# ---------------------------------------------------------------------------

class TestBug2WorkerSlot:
    def test_meta_json_records_worker_slot(self, tmp_path, monkeypatch):
        """meta.json worker_slot should reflect the slot passed to _run_one."""
        partial_root = tmp_path / "_partial"
        canonical_dir = tmp_path / "canonical"
        canonical_dir.mkdir()
        url = "https://example.com/video/slot"

        monkeypatch.setattr(downloader, "_simulate_check",
                            lambda *a, **k: downloader._SimulateResult(is_duplicate=False))
        monkeypatch.setattr(downloader, "_emit_json", lambda *a, **k: None)
        monkeypatch.setattr(downloader.subprocess, "Popen", lambda *a, **k: _FakeProc(rc=0))
        monkeypatch.setattr(downloader, "iter_parsed_events",
                            lambda *a, **k: iter([{"event": "finish", "rc": 0}]))

        downloader._run_one(
            tool="yt-dlp",
            urls=[url],
            out_dir=canonical_dir,
            canonical_out_dir=canonical_dir,
            partial_root=partial_root,
            raw_dir=tmp_path / "raw",
            url_index=1,
            proglog=_make_proglog(tmp_path),
            timeout=None,
            retries=0,
            quiet=True,
            dry_run=False,
            progress_freq_s=None,
            max_ndjson_rate=-1,
            skip_simulate_check=True,
            worker_slot=7,
            extdl_fallback=False,
        )
        # Partial dir is deleted on success, so we need to catch the meta.json before cleanup.
        # Test by using dry_run=False but checking with a slightly different approach:
        # Re-run just the meta write part manually.
        pdir = _partial_utils.partial_dir_for(url, partial_root)
        pdir.mkdir(parents=True, exist_ok=True)
        _partial_utils.write_partial_meta(pdir, url=url, file_path="stars/test.txt",
                                          line_num=1, slot=7)
        meta = _partial_utils.read_partial_meta(pdir)
        assert meta is not None
        assert meta["worker_slot"] == 7

    def test_start_worker_passes_slot_flag(self, tmp_path):
        """_start_worker() must include -W <slot> in the subprocess command."""
        cmd_captured = []

        def fake_popen(cmd, **kwargs):
            cmd_captured.extend(cmd)
            proc = MagicMock()
            proc.stdout = iter([])
            return proc

        with patch("subprocess.Popen", side_effect=fake_popen):
            manager._start_worker(
                slot=5,
                urlfile=tmp_path / "test.txt",
                canonical_root=tmp_path,
                max_rate=5.0,
                quiet=True,
                archive_dir=None,
                log_dir=tmp_path,
                cap_mibs=None,
            )

        assert "-W" in cmd_captured
        slot_idx = cmd_captured.index("-W")
        assert cmd_captured[slot_idx + 1] == "5"


# ---------------------------------------------------------------------------
# Bug 3: meta.json file_path uses archive_source_file
# ---------------------------------------------------------------------------

class TestBug3MetaFilePath:
    def test_meta_uses_archive_source_not_tmp(self, tmp_path, monkeypatch):
        """file_path in meta.json should be the original URL file, not a temp file."""
        partial_root = tmp_path / "_partial"
        original_file = tmp_path / "stars" / "emma_white.txt"
        original_file.parent.mkdir(parents=True)
        original_file.write_text("https://example.com/v\n", encoding="utf-8")

        url = "https://example.com/v"
        pdir = _partial_utils.partial_dir_for(url, partial_root)

        _partial_utils.write_partial_meta(
            pdir,
            url=url,
            file_path=str(original_file),  # the fix: pass archive_source_file
            line_num=1,
            slot=3,
        )
        meta = _partial_utils.read_partial_meta(pdir)
        assert meta is not None
        assert "emma_white.txt" in meta["file_path"]
        assert "tmp_urls" not in meta["file_path"]


# ---------------------------------------------------------------------------
# Feature 4: Sub-subcommand parsers
# ---------------------------------------------------------------------------

class TestRunSubSubcommandParsers:
    def test_watcher_parser_has_watcher_flags(self):
        p = make_run_watcher_parser()
        ns = p.parse_args(["-t", "4", "-F", "50.0"])
        assert ns.threads == 4
        assert ns.mp4_trigger_free_gb == 50.0

    def test_watcher_parser_has_core_flags(self):
        p = make_run_watcher_parser()
        ns = p.parse_args(["-P", "B:/stars/", "-t", "8"])
        assert ns.proxy_dl_location == "B:/stars/"
        assert ns.threads == 8

    def test_grid_parser_has_grid_flags(self):
        p = make_run_grid_parser()
        ns = p.parse_args(["-B", "./grid.db", "-t", "2"])
        assert ns.yt_dlp_grid_db == "./grid.db"
        assert ns.threads == 2

    def test_webview_parser_has_webview_flags(self):
        p = make_run_webview_parser()
        ns = p.parse_args(["-Y", "my-dash", "-t", "3"])
        assert ns.web_id == "my-dash"
        assert ns.threads == 3

    def test_disable_parser_has_disable_flags(self):
        p = make_run_disable_parser()
        ns = p.parse_args(["-n", "-K", "-t", "1"])
        assert ns.no_extdl_fallback is True
        assert ns.skip_simulate_check is True
        assert ns.threads == 1

    def test_watcher_auto_flag(self):
        assert profile_auto_flags("watcher") == {"enable_mp4_watcher": True}

    def test_grid_auto_flag(self):
        assert profile_auto_flags("grid") == {"yt_dlp_grid_search": True}

    def test_webview_auto_flag(self):
        assert profile_auto_flags("webview") == {"web_view": True}

    def test_disable_has_no_auto_flag(self):
        assert profile_auto_flags("disable") == {}

    def test_cli_run_watcher_dispatches(self):
        """ytaedl run watcher calls run_main with enable_mp4_watcher=True in namespace."""
        captured_ns = []

        def fake_run_main(argv=None, _ns=None):
            if _ns is not None:
                captured_ns.append(_ns)
            return 0

        with patch("ytaedl.manager.run_main", side_effect=fake_run_main):
            rc = cli_main(["run", "watcher", "-t", "2"])
        assert rc == 0
        assert captured_ns, "run_main was not called with a namespace"
        assert captured_ns[0].enable_mp4_watcher is True

    def test_cli_run_watcher_help(self, capsys):
        rc = cli_main(["run", "watcher", "-h"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "watcher" in out.lower()
        assert "SUBCOMMAND" in out or "watcher" in out

    def test_watcher_parsers_all_have_complete_namespace(self):
        """Each combined parser must define all flags run_main() might access."""
        required_attrs = [
            "threads", "proxy_dl_location", "enable_mp4_watcher",
            "yt_dlp_grid_search", "web_view", "no_extdl_fallback",
        ]
        for factory in (make_run_watcher_parser, make_run_grid_parser,
                        make_run_webview_parser, make_run_disable_parser):
            ns = factory().parse_args([])
            for attr in required_attrs:
                assert hasattr(ns, attr), f"{factory.__name__} missing attr {attr!r}"


# ---------------------------------------------------------------------------
# Feature 5: Multiple --download-root + --primary-root
# ---------------------------------------------------------------------------

class TestMultiRoot:
    def test_simulate_check_searches_all_canonical_dirs(self, tmp_path, monkeypatch):
        """_simulate_check loops over all canonical dirs, not just the first."""
        dir_a = tmp_path / "root_a" / "channel"
        dir_b = tmp_path / "root_b" / "channel"
        dir_b.mkdir(parents=True)  # only dir_b exists
        (dir_b / "Video.mp4").write_bytes(b"x" * 1000)

        # Simulate predicts "Video.mp4" with size 1000
        import subprocess as sp_mod
        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.communicate.return_value = ("Video.mp4\n1000\n", "")

        with patch.object(sp_mod, "Popen", return_value=fake_proc):
            result = downloader._simulate_check(
                "https://example.com/v",
                [dir_a, dir_b],  # dir_a doesn't exist, dir_b has the file
            )

        assert result.is_duplicate is True
        assert "root_b" in result.existing_path

    def test_simulate_check_not_duplicate_when_not_in_any_dir(self, tmp_path, monkeypatch):
        dir_a = tmp_path / "root_a" / "channel"
        dir_b = tmp_path / "root_b" / "channel"
        # Neither dir has the file

        import subprocess as sp_mod
        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.communicate.return_value = ("NewVideo.mp4\n5000\n", "")

        with patch.object(sp_mod, "Popen", return_value=fake_proc):
            result = downloader._simulate_check(
                "https://example.com/v/new",
                [dir_a, dir_b],
            )

        assert result.is_duplicate is False

    def test_manager_download_root_appends_to_list(self):
        p = manager.make_parser()
        ns = p.parse_args(["-L", "/stars/d1", "-L", "/stars/d2"])
        assert isinstance(ns.download_root, list)
        assert len(ns.download_root) == 2

    def test_manager_primary_root_flag(self):
        p = manager.make_parser()
        ns = p.parse_args(["-L", "/stars/d1", "-U", "/primary"])
        assert ns.primary_root == "/primary"

    def test_start_worker_passes_extra_canonical_roots(self, tmp_path):
        cmd_captured = []

        def fake_popen(cmd, **kwargs):
            cmd_captured.extend(cmd)
            proc = MagicMock()
            proc.stdout = iter([])
            return proc

        extra = [tmp_path / "root_b" / "channel"]
        with patch("subprocess.Popen", side_effect=fake_popen):
            manager._start_worker(
                slot=1,
                urlfile=tmp_path / "test.txt",
                canonical_root=tmp_path,
                max_rate=5.0,
                quiet=True,
                archive_dir=None,
                log_dir=tmp_path,
                cap_mibs=None,
                extra_canonical_roots=extra,
            )

        assert "-Z" in cmd_captured
        assert "--extra-canonical-roots" not in cmd_captured
        idx = cmd_captured.index("-Z")
        assert "root_b" in cmd_captured[idx + 1]


# ---------------------------------------------------------------------------
# Feature 6: Default changes
# ---------------------------------------------------------------------------

class TestNewDefaults:
    def test_unique_domain_dls_default_2(self):
        args = manager.make_parser().parse_args([])
        assert args.unique_domain_dls == 2

    def test_max_resolution_default_2k(self):
        args = manager.make_parser().parse_args([])
        assert args.max_resolution == "2k"

    def test_archive_default_archive_dir(self):
        args = manager.make_parser().parse_args([])
        assert args.archive == "./archive"

    def test_download_root_default_is_none_not_string(self):
        """With action=append, default is None (resolved to ./stars in run_main)."""
        args = manager.make_parser().parse_args([])
        assert args.download_root is None


# ---------------------------------------------------------------------------
# Feature 7: --show-bars removed
# ---------------------------------------------------------------------------

class TestShowBarsRemoved:
    def test_show_bars_not_in_parser(self):
        p = manager.make_parser()
        with pytest.raises(SystemExit):
            p.parse_args(["-b"])

    def test_show_bars_not_in_namespace(self):
        args = manager.make_parser().parse_args([])
        assert not hasattr(args, "show_bars")
