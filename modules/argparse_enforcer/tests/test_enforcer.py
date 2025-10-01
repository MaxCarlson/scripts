"""
Comprehensive tests for EnforcedArgumentParser.
"""
import pytest
import argparse
import sys
from argparse_enforcer import EnforcedArgumentParser


class TestArgumentNamingConventions:
    """Test argument naming convention enforcement."""

    def test_valid_single_char_abbreviated(self):
        """Test valid single character abbreviated arguments."""
        parser = EnforcedArgumentParser()
        parser.add_argument("-f", "--file", help="File argument")
        parser.add_argument("-o", "--output", help="Output argument")
        parser.add_argument("-V", "--verbose", help="Verbose flag")

    def test_valid_full_length_formats(self):
        """Test various valid full-length argument formats."""
        parser = EnforcedArgumentParser()
        parser.add_argument("-f", "--file", help="Single word")
        parser.add_argument("-o", "--output-file", help="Two words")
        parser.add_argument("-c", "--config-file-path", help="Three words")
        parser.add_argument("-n", "--name123", help="With digits")

    def test_reject_missing_abbreviated(self):
        """Test rejection when abbreviated form is missing."""
        parser = EnforcedArgumentParser()
        with pytest.raises(ValueError, match="Must provide exactly 2 argument forms"):
            parser.add_argument("--file-only", help="Missing abbreviated")

    def test_reject_missing_full(self):
        """Test rejection when full form is missing."""
        parser = EnforcedArgumentParser()
        with pytest.raises(ValueError, match="Must provide exactly 2 argument forms"):
            parser.add_argument("-f", help="Missing full")

    def test_reject_abbreviated_non_alpha(self):
        """Test rejection of non-alphabetic abbreviated forms."""
        parser = EnforcedArgumentParser()
        with pytest.raises(ValueError, match="must be alphabetic"):
            parser.add_argument("-1", "--file", help="Numeric abbreviated")

    def test_reject_full_uppercase(self):
        """Test rejection of uppercase in full form."""
        parser = EnforcedArgumentParser()
        with pytest.raises(ValueError, match="must use lowercase"):
            parser.add_argument("-f", "--File", help="Uppercase in full")

    def test_reject_full_underscore(self):
        """Test rejection of underscore in full form."""
        parser = EnforcedArgumentParser()
        with pytest.raises(ValueError, match="must use lowercase"):
            parser.add_argument("-f", "--file_name", help="Underscore separator")

    def test_reject_full_leading_dash(self):
        """Test rejection of leading dash in full form name."""
        parser = EnforcedArgumentParser()
        with pytest.raises(ValueError, match="invalid dash placement"):
            parser.add_argument("-f", "---file", help="Extra leading dash")

    def test_reject_full_trailing_dash(self):
        """Test rejection of trailing dash in full form."""
        parser = EnforcedArgumentParser()
        with pytest.raises(ValueError, match="invalid dash placement"):
            parser.add_argument("-f", "--file-", help="Trailing dash")

    def test_reject_full_double_dash_inside(self):
        """Test rejection of double dash inside full form."""
        parser = EnforcedArgumentParser()
        with pytest.raises(ValueError, match="invalid dash placement"):
            parser.add_argument("-f", "--file--name", help="Double dash inside")

    def test_reject_duplicate_abbreviated_char(self):
        """Test rejection of duplicate abbreviated characters."""
        parser = EnforcedArgumentParser()
        parser.add_argument("-f", "--file", help="First use of f")
        with pytest.raises(ValueError, match="already used"):
            parser.add_argument("-f", "--foo", help="Duplicate f")

    def test_allow_positional_arguments(self):
        """Test that positional arguments pass through without validation."""
        parser = EnforcedArgumentParser()
        parser.add_argument("input_file", help="Input file")
        parser.add_argument("-f", "--file", help="Optional file")


class TestTwoCharAbbreviated:
    """Test two-character abbreviated form rules."""

    def test_reject_two_char_before_threshold(self):
        """Test rejection of two-char abbreviated before threshold."""
        parser = EnforcedArgumentParser(allow_two_char_threshold=15, add_help=False)
        # Add 10 arguments (below threshold)
        for i, char in enumerate("abcdefgijk"):
            parser.add_argument(f"-{char}", f"--arg{i}", help=f"Arg {i}")

        # Should reject two-char before threshold
        with pytest.raises(ValueError, match="Two-char abbreviated form only allowed"):
            parser.add_argument("-ab", "--arg10", help="Two char too early")

    def test_allow_two_char_after_threshold(self):
        """Test allowing two-char abbreviated after threshold."""
        parser = EnforcedArgumentParser(allow_two_char_threshold=15, add_help=False)
        # Add 15 arguments to reach threshold
        chars = "abcdefgijklmnop"
        for i, char in enumerate(chars):
            parser.add_argument(f"-{char}", f"--arg{i}", help=f"Arg {i}")

        # Should allow two-char after threshold
        parser.add_argument("-xy", "--arg15", help="Two char after threshold")
        parser.add_argument("-zz", "--arg16", help="Another two char")

    def test_allow_two_char_when_all_exhausted(self):
        """Test allowing two-char when all single chars are exhausted."""
        import string
        parser = EnforcedArgumentParser(allow_two_char_threshold=100, add_help=False)

        # Use all single characters (excluding h which conflicts with help)
        for i, char in enumerate(string.ascii_letters):
            parser.add_argument(f"-{char}", f"--arg{i}", help=f"Arg {i}")

        # Now two-char should be allowed even though we're under threshold of 100
        parser.add_argument("-ab", "--arg-extra", help="Two char allowed")

    def test_custom_threshold(self):
        """Test custom two-char threshold."""
        parser = EnforcedArgumentParser(allow_two_char_threshold=5)
        # Add 5 arguments
        for i, char in enumerate("abcde"):
            parser.add_argument(f"-{char}", f"--arg{i}", help=f"Arg {i}")

        # Should allow two-char after 5 args
        parser.add_argument("-xy", "--arg5", help="Two char allowed")


class TestArgumentParsing:
    """Test actual argument parsing functionality."""

    def test_parse_simple_args(self):
        """Test parsing simple arguments."""
        parser = EnforcedArgumentParser()
        parser.add_argument("-f", "--file", help="File")
        parser.add_argument("-o", "--output", help="Output")

        # Test abbreviated form
        args = parser.parse_args(["-f", "input.txt", "-o", "output.txt"])
        assert args.file == "input.txt"
        assert args.output == "output.txt"

        # Test full form
        args = parser.parse_args(["--file", "input.txt", "--output", "output.txt"])
        assert args.file == "input.txt"
        assert args.output == "output.txt"

    def test_parse_with_flags(self):
        """Test parsing boolean flags."""
        parser = EnforcedArgumentParser()
        parser.add_argument("-v", "--verbose", action="store_true", help="Verbose")
        parser.add_argument("-q", "--quiet", action="store_true", help="Quiet")

        args = parser.parse_args(["-v"])
        assert args.verbose is True
        assert args.quiet is False

        args = parser.parse_args(["--quiet"])
        assert args.verbose is False
        assert args.quiet is True

    def test_parse_with_choices(self):
        """Test parsing with choices."""
        parser = EnforcedArgumentParser()
        parser.add_argument("-l", "--level", choices=["debug", "info", "error"], help="Log level")

        args = parser.parse_args(["-l", "debug"])
        assert args.level == "debug"

        args = parser.parse_args(["--level", "error"])
        assert args.level == "error"

    def test_parse_with_defaults(self):
        """Test parsing with default values."""
        parser = EnforcedArgumentParser()
        parser.add_argument("-p", "--port", type=int, default=8080, help="Port")

        args = parser.parse_args([])
        assert args.port == 8080

        args = parser.parse_args(["-p", "3000"])
        assert args.port == 3000

    def test_parse_with_multiple_values(self):
        """Test parsing with multiple values (nargs)."""
        parser = EnforcedArgumentParser()
        parser.add_argument("-f", "--files", nargs="+", help="Files")

        args = parser.parse_args(["-f", "a.txt", "b.txt", "c.txt"])
        assert args.files == ["a.txt", "b.txt", "c.txt"]

    def test_parse_with_positional(self):
        """Test parsing with positional and optional arguments."""
        parser = EnforcedArgumentParser()
        parser.add_argument("input", help="Input file")
        parser.add_argument("-o", "--output", help="Output file")

        args = parser.parse_args(["input.txt", "-o", "output.txt"])
        assert args.input == "input.txt"
        assert args.output == "output.txt"


class TestArgcompleteIntegration:
    """Test argcomplete integration."""

    def test_autocomplete_enabled_by_default(self):
        """Test that autocomplete is enabled by default."""
        parser = EnforcedArgumentParser()
        assert parser._enable_autocomplete is True

    def test_autocomplete_can_be_disabled(self):
        """Test that autocomplete can be disabled."""
        parser = EnforcedArgumentParser(enable_autocomplete=False)
        assert parser._enable_autocomplete is False

    def test_parse_args_with_autocomplete(self):
        """Test that parse_args works with autocomplete enabled."""
        parser = EnforcedArgumentParser()
        parser.add_argument("-f", "--file", help="File")

        # Should not raise even if argcomplete is not installed
        args = parser.parse_args(["-f", "test.txt"])
        assert args.file == "test.txt"

    def test_parse_known_args_with_autocomplete(self):
        """Test that parse_known_args works with autocomplete enabled."""
        parser = EnforcedArgumentParser()
        parser.add_argument("-f", "--file", help="File")

        args, remaining = parser.parse_known_args(["-f", "test.txt", "extra"])
        assert args.file == "test.txt"
        assert remaining == ["extra"]


class TestCrossCompatibility:
    """Test cross-platform compatibility aspects."""

    def test_parser_creation_cross_platform(self):
        """Test that parser can be created on any platform."""
        parser = EnforcedArgumentParser(description="Test parser")
        assert parser is not None
        assert isinstance(parser, argparse.ArgumentParser)

    def test_help_generation(self):
        """Test that help text generation works."""
        parser = EnforcedArgumentParser(description="Test CLI")
        parser.add_argument("-f", "--file", help="Input file")
        parser.add_argument("-o", "--output", help="Output file")

        # Get help text
        help_text = parser.format_help()
        assert "-f" in help_text
        assert "--file" in help_text
        assert "-o" in help_text
        assert "--output" in help_text

    def test_error_messages_clear(self):
        """Test that error messages are clear and helpful."""
        parser = EnforcedArgumentParser()

        try:
            parser.add_argument("-f", "--File", help="Bad uppercase")
        except ValueError as e:
            assert "lowercase" in str(e).lower()

        try:
            parser.add_argument("-1", "--file", help="Bad numeric")
        except ValueError as e:
            assert "alphabetic" in str(e).lower()


class TestEdgeCases:
    """Test edge cases and unusual scenarios."""

    def test_empty_parser(self):
        """Test creating parser with no arguments."""
        parser = EnforcedArgumentParser()
        args = parser.parse_args([])
        assert args is not None

    def test_only_help_and_version(self):
        """Test parser with only help (no custom args)."""
        parser = EnforcedArgumentParser()
        help_text = parser.format_help()
        assert "usage:" in help_text.lower()

    def test_argument_with_metavar(self):
        """Test argument with metavar."""
        parser = EnforcedArgumentParser()
        parser.add_argument("-f", "--file", metavar="PATH", help="File path")
        help_text = parser.format_help()
        assert "PATH" in help_text

    def test_argument_with_dest(self):
        """Test argument with custom dest."""
        parser = EnforcedArgumentParser()
        parser.add_argument("-f", "--file", dest="input_file", help="File")
        args = parser.parse_args(["-f", "test.txt"])
        assert args.input_file == "test.txt"

    def test_mutually_exclusive_group(self):
        """Test mutually exclusive groups work."""
        parser = EnforcedArgumentParser()
        group = parser.add_mutually_exclusive_group()
        group.add_argument("-v", "--verbose", action="store_true")
        group.add_argument("-q", "--quiet", action="store_true")

        args = parser.parse_args(["-v"])
        assert args.verbose is True

    def test_subparsers(self):
        """Test that subparsers can be added."""
        parser = EnforcedArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        # Note: subparser add_parser returns regular ArgumentParser
        # so we don't enforce rules on subcommands
        sub = subparsers.add_parser("init")
        assert sub is not None


class TestRealWorldScenarios:
    """Test realistic CLI scenarios."""

    def test_file_processor_cli(self):
        """Test a file processor CLI scenario."""
        parser = EnforcedArgumentParser(description="File Processor")
        parser.add_argument("input", help="Input file")
        parser.add_argument("-o", "--output", help="Output file")
        parser.add_argument("-f", "--format", choices=["json", "xml", "csv"],
                          default="json", help="Output format")
        parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
        parser.add_argument("-q", "--quiet", action="store_true", help="Quiet mode")

        args = parser.parse_args([
            "input.txt",
            "-o", "output.json",
            "-f", "json",
            "-v"
        ])

        assert args.input == "input.txt"
        assert args.output == "output.json"
        assert args.format == "json"
        assert args.verbose is True

    def test_server_cli(self):
        """Test a server configuration CLI scenario."""
        parser = EnforcedArgumentParser(description="Server")
        parser.add_argument("-H", "--host", default="localhost", help="Host")
        parser.add_argument("-p", "--port", type=int, default=8080, help="Port")
        parser.add_argument("-w", "--workers", type=int, default=4, help="Worker count")
        parser.add_argument("-d", "--debug", action="store_true", help="Debug mode")

        args = parser.parse_args(["-p", "3000", "-w", "8", "--debug"])

        assert args.host == "localhost"
        assert args.port == 3000
        assert args.workers == 8
        assert args.debug is True
