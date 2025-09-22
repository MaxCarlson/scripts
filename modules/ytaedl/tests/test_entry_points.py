"""Tests for ytaedl entry points and CLI functionality."""

import subprocess
import sys
import pytest
from unittest.mock import patch


class TestEntryPoints:
    """Test entry point scripts defined in pyproject.toml."""

    def test_ytaedl_entry_point_exists(self):
        """Test that ytaedl entry point is properly configured."""
        # Test import of the main function
        from ytaedl.manager import main as manager_main
        assert callable(manager_main)

    def test_ytaedl_download_entry_point_exists(self):
        """Test that ytaedl-download entry point is properly configured."""
        # Test import of the main function
        from ytaedl.downloader import main as downloader_main
        assert callable(downloader_main)

    @pytest.mark.integration
    def test_ytaedl_help(self):
        """Test ytaedl command shows help."""
        # This would test the actual installed command
        # For now, we'll test the module directly
        with patch('sys.argv', ['ytaedl', '--help']):
            with pytest.raises(SystemExit) as exc_info:
                from ytaedl.manager import main
                main()
            # Help should exit with code 0
            assert exc_info.value.code == 0

    @pytest.mark.integration
    def test_ytaedl_download_help(self):
        """Test ytaedl-download command shows help."""
        with patch('sys.argv', ['ytaedl-download', '--help']):
            with pytest.raises(SystemExit) as exc_info:
                from ytaedl.downloader import main
                main()
            # Help should exit with code 0
            assert exc_info.value.code == 0

    def test_module_version_access(self):
        """Test that module version is accessible."""
        import ytaedl
        assert hasattr(ytaedl, '__version__')
        assert isinstance(ytaedl.__version__, str)
        assert len(ytaedl.__version__) > 0

    def test_module_docstring(self):
        """Test that module has proper docstring."""
        import ytaedl
        assert ytaedl.__doc__ is not None
        assert "ytaedl package" in ytaedl.__doc__
        assert "ytaedl.manager:main" in ytaedl.__doc__
        assert "ytaedl.downloader:main" in ytaedl.__doc__


class TestCLIIntegration:
    """Integration tests for CLI functionality."""

    def test_downloader_missing_required_arg(self):
        """Test downloader fails with missing required argument."""
        with patch('sys.argv', ['ytaedl-download']):
            with patch('sys.stderr'):
                with pytest.raises(SystemExit) as exc_info:
                    from ytaedl.downloader import main
                    main()
                # Should fail due to missing -f argument
                assert exc_info.value.code != 0

    def test_manager_default_args(self):
        """Test manager with default arguments."""
        # Manager should work with defaults but will exit quickly due to no files
        with patch('sys.argv', ['ytaedl', '--exit-at-time', '1']):
            with patch('os.get_terminal_size') as mock_term:
                mock_term.return_value.columns = 80
                mock_term.return_value.lines = 24
                with patch('sys.stdout'):
                    from ytaedl.manager import main
                    result = main()
                    assert result == 0

    def test_invalid_arguments(self):
        """Test handling of invalid arguments."""
        with patch('sys.argv', ['ytaedl', '--invalid-argument']):
            with pytest.raises(SystemExit) as exc_info:
                from ytaedl.manager import main
                main()
            # Should exit with non-zero code for invalid args
            assert exc_info.value.code != 0

    @pytest.mark.skipif(sys.platform == "win32", reason="Process handling differs on Windows")
    def test_keyboard_interrupt_handling(self):
        """Test that KeyboardInterrupt is handled gracefully."""
        with patch('sys.argv', ['ytaedl', '--exit-at-time', '10']):
            with patch('time.sleep', side_effect=KeyboardInterrupt):
                with patch('os.get_terminal_size') as mock_term:
                    mock_term.return_value.columns = 80
                    mock_term.return_value.lines = 24
                    with patch('sys.stdout'):
                        from ytaedl.manager import main
                        result = main()
                        assert result == 0


if __name__ == "__main__":
    pytest.main([__file__])