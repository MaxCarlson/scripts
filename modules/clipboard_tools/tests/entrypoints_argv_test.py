"""Tests to verify entrypoint functions correctly pass sys.argv to underlying modules."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


class TestCopyEntrypointsArgv:
    """Test copy_* entrypoints pass argv correctly."""

    def test_copy_append_main_passes_argv_with_a_flag(self, monkeypatch):
        """c2ca should prepend -a to sys.argv[1:]."""
        # Simulate: c2ca file1.txt file2.txt
        monkeypatch.setattr(sys, "argv", ["c2ca", "file1.txt", "file2.txt"])

        captured_argv = None

        def mock_run_copy(argv):
            nonlocal captured_argv
            captured_argv = argv
            return 0

        with patch("clipboard_tools.entrypoints._run_copy", side_effect=mock_run_copy):
            with pytest.raises(SystemExit) as exc_info:
                from clipboard_tools.entrypoints import copy_append_main

                copy_append_main()

            assert exc_info.value.code == 0
            assert captured_argv == ["-a", "file1.txt", "file2.txt"]

    def test_copy_recursive_main_passes_argv_with_r_flag(self, monkeypatch):
        """c2cr should prepend -r to sys.argv[1:]."""
        monkeypatch.setattr(sys, "argv", ["c2cr", "file1.txt"])

        captured_argv = None

        def mock_run_copy(argv):
            nonlocal captured_argv
            captured_argv = argv
            return 0

        with patch("clipboard_tools.entrypoints._run_copy", side_effect=mock_run_copy):
            with pytest.raises(SystemExit) as exc_info:
                from clipboard_tools.entrypoints import copy_recursive_main

                copy_recursive_main()

            assert exc_info.value.code == 0
            assert captured_argv == ["-r", "file1.txt"]

    def test_copy_default_main_passes_argv(self, monkeypatch):
        """c2cd should pass sys.argv[1:] directly."""
        monkeypatch.setattr(sys, "argv", ["c2cd", "myfile.py"])

        captured_argv = None

        def mock_run_copy(argv):
            nonlocal captured_argv
            captured_argv = argv
            return 0

        with patch("clipboard_tools.entrypoints._run_copy", side_effect=mock_run_copy):
            with pytest.raises(SystemExit) as exc_info:
                from clipboard_tools.entrypoints import copy_default_main

                copy_default_main()

            assert exc_info.value.code == 0
            assert captured_argv == ["myfile.py"]


class TestOutputToClipboardEntrypointsArgv:
    """Test otc* entrypoints pass argv correctly."""

    def test_output_to_clipboard_main_passes_argv(self, monkeypatch):
        """otc should pass sys.argv[1:] directly."""
        monkeypatch.setattr(sys, "argv", ["otc", "echo", "hello"])

        captured_argv = None

        def mock_main(argv):
            nonlocal captured_argv
            captured_argv = argv
            return 0

        with patch("pyscripts.output_to_clipboard.main", side_effect=mock_main):
            with pytest.raises(SystemExit) as exc_info:
                from clipboard_tools.entrypoints import output_to_clipboard_main

                output_to_clipboard_main()

            assert exc_info.value.code == 0
            assert captured_argv == ["echo", "hello"]

    def test_output_to_clipboard_wrap_main_passes_argv_with_w_flag(self, monkeypatch):
        """otcw should prepend -w to sys.argv[1:]."""
        monkeypatch.setattr(sys, "argv", ["otcw", "ls", "-la"])

        captured_argv = None

        def mock_main(argv):
            nonlocal captured_argv
            captured_argv = argv
            return 0

        with patch("pyscripts.output_to_clipboard.main", side_effect=mock_main):
            with pytest.raises(SystemExit) as exc_info:
                from clipboard_tools.entrypoints import output_to_clipboard_wrap_main

                output_to_clipboard_wrap_main()

            assert exc_info.value.code == 0
            assert captured_argv == ["-w", "ls", "-la"]

    def test_output_to_clipboard_append_main_passes_argv_with_a_flag(self, monkeypatch):
        """otca should prepend -a to sys.argv[1:]."""
        monkeypatch.setattr(sys, "argv", ["otca", "date"])

        captured_argv = None

        def mock_main(argv):
            nonlocal captured_argv
            captured_argv = argv
            return 0

        with patch("pyscripts.output_to_clipboard.main", side_effect=mock_main):
            with pytest.raises(SystemExit) as exc_info:
                from clipboard_tools.entrypoints import output_to_clipboard_append_main

                output_to_clipboard_append_main()

            assert exc_info.value.code == 0
            assert captured_argv == ["-a", "date"]

    def test_output_to_clipboard_wrap_append_main_passes_argv_with_wa_flags(self, monkeypatch):
        """otcwa should prepend -w -a to sys.argv[1:]."""
        monkeypatch.setattr(sys, "argv", ["otcwa", "git", "status"])

        captured_argv = None

        def mock_main(argv):
            nonlocal captured_argv
            captured_argv = argv
            return 0

        with patch("pyscripts.output_to_clipboard.main", side_effect=mock_main):
            with pytest.raises(SystemExit) as exc_info:
                from clipboard_tools.entrypoints import output_to_clipboard_wrap_append_main

                output_to_clipboard_wrap_append_main()

            assert exc_info.value.code == 0
            assert captured_argv == ["-w", "-a", "git", "status"]


class TestCopyBufferEntrypointsArgv:
    """Test cb2c* entrypoints pass argv correctly."""

    def test_copy_buffer_main_passes_argv(self, monkeypatch):
        """cb2c should pass sys.argv[1:] directly."""
        monkeypatch.setattr(sys, "argv", ["cb2c", "--no-stats"])

        captured_argv = None

        def mock_main(argv):
            nonlocal captured_argv
            captured_argv = argv
            return 0

        with patch("pyscripts.copy_buffer_to_clipboard.main", side_effect=mock_main):
            with pytest.raises(SystemExit) as exc_info:
                from clipboard_tools.entrypoints import copy_buffer_main

                copy_buffer_main()

            assert exc_info.value.code == 0
            assert captured_argv == ["--no-stats"]

    def test_copy_buffer_full_main_passes_argv_with_f_flag(self, monkeypatch):
        """cb2cf should prepend -f to sys.argv[1:]."""
        monkeypatch.setattr(sys, "argv", ["cb2cf", "--no-stats"])

        captured_argv = None

        def mock_main(argv):
            nonlocal captured_argv
            captured_argv = argv
            return 0

        with patch("pyscripts.copy_buffer_to_clipboard.main", side_effect=mock_main):
            with pytest.raises(SystemExit) as exc_info:
                from clipboard_tools.entrypoints import copy_buffer_full_main

                copy_buffer_full_main()

            assert exc_info.value.code == 0
            assert captured_argv == ["-f", "--no-stats"]


class TestReplaceWithClipboardEntrypointsArgv:
    """Test rwc* entrypoints pass argv correctly."""

    def test_replace_with_clipboard_from_last_main_passes_argv_with_F_flag(self, monkeypatch):
        """rwcp should prepend -F to sys.argv[1:]."""
        monkeypatch.setattr(sys, "argv", ["rwcp", "override_file.txt"])

        from pyscripts import replace_with_clipboard as rwc

        original_parse_args = rwc.parser.parse_args
        captured_argv = None

        def mock_parse_args(argv=None):
            nonlocal captured_argv
            captured_argv = argv
            # Create a mock args object
            mock_args = MagicMock()
            mock_args.file = "override_file.txt"
            mock_args.no_stats = False
            mock_args.from_last_cld = True
            mock_args.buffer_id = None
            return mock_args

        with patch.object(rwc.parser, "parse_args", side_effect=mock_parse_args):
            with patch.object(rwc, "replace_or_print_clipboard", return_value=None):
                with pytest.raises(SystemExit):
                    from clipboard_tools.entrypoints import replace_with_clipboard_from_last_main

                    replace_with_clipboard_from_last_main()

                assert captured_argv == ["-F", "override_file.txt"]
