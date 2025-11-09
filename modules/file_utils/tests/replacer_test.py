"""
Tests for the replacer module.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from file_utils.replacer import (
    Match,
    ReplacementResult,
    apply_replacements,
    find_matches_with_ripgrep,
)


class TestApplyReplacements:
    """Tests for apply_replacements function."""

    def test_simple_replacement(self, tmp_path: Path):
        """Test basic text replacement."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World\nHello Python\nGoodbye World\n")

        result = apply_replacements(
            file_path=test_file,
            pattern="Hello",
            replacement="Hi",
            delete_line=False,
            first_only=False,
            specific_line=None,
            max_per_file=None,
            ignore_case=False,
        )

        assert result.matches_found == 2
        assert result.replacements_made == 2
        assert result.lines_deleted == 0
        assert result.error is None
        assert "Hi World\n" in result.modified_lines
        assert "Hi Python\n" in result.modified_lines

    def test_delete_line(self, tmp_path: Path):
        """Test deleting entire lines containing matches."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Keep this line\nDelete this line\nKeep this too\n")

        result = apply_replacements(
            file_path=test_file,
            pattern="Delete",
            replacement=None,
            delete_line=True,
            first_only=False,
            specific_line=None,
            max_per_file=None,
            ignore_case=False,
        )

        assert result.matches_found == 1
        assert result.lines_deleted == 1
        assert len(result.modified_lines) == 2
        assert "Keep this line\n" in result.modified_lines
        assert "Keep this too\n" in result.modified_lines
        assert "Delete this line\n" not in result.modified_lines

    def test_first_only(self, tmp_path: Path):
        """Test replacing only the first match."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("foo bar\nfoo baz\nfoo qux\n")

        result = apply_replacements(
            file_path=test_file,
            pattern="foo",
            replacement="bar",
            delete_line=False,
            first_only=True,
            specific_line=None,
            max_per_file=None,
            ignore_case=False,
        )

        assert result.matches_found == 3
        assert result.replacements_made == 1
        assert result.modified_lines[0] == "bar bar\n"
        assert result.modified_lines[1] == "foo baz\n"
        assert result.modified_lines[2] == "foo qux\n"

    def test_specific_line(self, tmp_path: Path):
        """Test replacing only on a specific line number."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("foo\nbar\nfoo\n")

        result = apply_replacements(
            file_path=test_file,
            pattern="foo",
            replacement="baz",
            delete_line=False,
            first_only=False,
            specific_line=3,  # 1-indexed
            max_per_file=None,
            ignore_case=False,
        )

        assert result.matches_found == 1  # Only line 3 checked
        assert result.replacements_made == 1
        assert result.modified_lines[0] == "foo\n"
        assert result.modified_lines[1] == "bar\n"
        assert result.modified_lines[2] == "baz\n"

    def test_max_per_file(self, tmp_path: Path):
        """Test limiting replacements per file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("foo\nfoo\nfoo\nfoo\n")

        result = apply_replacements(
            file_path=test_file,
            pattern="foo",
            replacement="bar",
            delete_line=False,
            first_only=False,
            specific_line=None,
            max_per_file=2,
            ignore_case=False,
        )

        # matches_found counts only matches before hitting max_per_file limit
        assert result.matches_found == 2
        assert result.replacements_made == 2
        assert result.modified_lines[0] == "bar\n"
        assert result.modified_lines[1] == "bar\n"
        assert result.modified_lines[2] == "foo\n"
        assert result.modified_lines[3] == "foo\n"

    def test_ignore_case(self, tmp_path: Path):
        """Test case-insensitive matching."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World\nhello world\nHELLO WORLD\n")

        result = apply_replacements(
            file_path=test_file,
            pattern="hello",
            replacement="Hi",
            delete_line=False,
            first_only=False,
            specific_line=None,
            max_per_file=None,
            ignore_case=True,
        )

        assert result.matches_found == 3
        assert result.replacements_made == 3
        assert all("Hi" in line for line in result.modified_lines)

    def test_regex_pattern(self, tmp_path: Path):
        """Test using regex patterns."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("File: test1.txt\nFile: test2.txt\nNo file here\n")

        result = apply_replacements(
            file_path=test_file,
            pattern=r"File: \w+\.txt",
            replacement="Document",
            delete_line=False,
            first_only=False,
            specific_line=None,
            max_per_file=None,
            ignore_case=False,
        )

        assert result.matches_found == 2
        assert result.replacements_made == 2
        assert "Document\n" in result.modified_lines

    def test_delete_line_with_specific_line(self, tmp_path: Path):
        """Test deleting a specific line number."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Line 1\nLine 2 delete\nLine 3\nLine 4 delete\n")

        result = apply_replacements(
            file_path=test_file,
            pattern="delete",
            replacement=None,
            delete_line=True,
            first_only=False,
            specific_line=2,  # Only delete line 2
            max_per_file=None,
            ignore_case=False,
        )

        assert result.lines_deleted == 1
        assert len(result.modified_lines) == 3
        assert "Line 1\n" in result.modified_lines
        assert "Line 3\n" in result.modified_lines
        assert "Line 4 delete\n" in result.modified_lines
        assert "Line 2 delete\n" not in result.modified_lines

    def test_file_not_found(self, tmp_path: Path):
        """Test handling of non-existent file."""
        test_file = tmp_path / "nonexistent.txt"

        result = apply_replacements(
            file_path=test_file,
            pattern="foo",
            replacement="bar",
            delete_line=False,
            first_only=False,
            specific_line=None,
            max_per_file=None,
            ignore_case=False,
        )

        assert result.error is not None
        assert "Failed to read file" in result.error

    def test_no_matches(self, tmp_path: Path):
        """Test file with no matches."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("foo\nbar\nbaz\n")

        result = apply_replacements(
            file_path=test_file,
            pattern="qux",
            replacement="quux",
            delete_line=False,
            first_only=False,
            specific_line=None,
            max_per_file=None,
            ignore_case=False,
        )

        assert result.matches_found == 0
        assert result.replacements_made == 0
        assert result.modified_lines == result.original_lines


class TestMatch:
    """Tests for Match dataclass."""

    def test_match_creation(self):
        """Test creating a Match object."""
        match = Match(
            file_path=Path("test.txt"),
            line_number=42,
            line_content="Hello World",
            column=6,
        )

        assert match.file_path == Path("test.txt")
        assert match.line_number == 42
        assert match.line_content == "Hello World"
        assert match.column == 6


class TestReplacementResult:
    """Tests for ReplacementResult dataclass."""

    def test_result_creation(self):
        """Test creating a ReplacementResult object."""
        result = ReplacementResult(
            file_path=Path("test.txt"),
            matches_found=5,
            replacements_made=3,
            lines_deleted=2,
        )

        assert result.file_path == Path("test.txt")
        assert result.matches_found == 5
        assert result.replacements_made == 3
        assert result.lines_deleted == 2
        assert result.error is None


class TestFindMatchesWithRipgrep:
    """Tests for find_matches_with_ripgrep function."""

    def test_find_matches(self, tmp_path: Path):
        """Test finding matches with ripgrep."""
        # Create test files
        (tmp_path / "file1.txt").write_text("Hello World\n")
        (tmp_path / "file2.txt").write_text("Hello Python\n")
        (tmp_path / "file3.txt").write_text("Goodbye World\n")

        matches = find_matches_with_ripgrep(
            pattern="Hello",
            path=str(tmp_path),
            ignore_case=False,
            glob=None,
            file_type=None,
        )

        assert len(matches) >= 2  # At least file1 and file2
        assert all(isinstance(m, Match) for m in matches)
        assert all("Hello" in m.line_content for m in matches)

    def test_glob_filter(self, tmp_path: Path):
        """Test using glob pattern to filter files."""
        # Create test files
        (tmp_path / "test.py").write_text("import os\n")
        (tmp_path / "test.txt").write_text("import os\n")

        matches = find_matches_with_ripgrep(
            pattern="import",
            path=str(tmp_path),
            ignore_case=False,
            glob="*.py",
            file_type=None,
        )

        # Should only match in .py files
        assert all(m.file_path.suffix == ".py" for m in matches)

    def test_no_matches(self, tmp_path: Path):
        """Test when no matches are found."""
        (tmp_path / "test.txt").write_text("foo bar baz\n")

        matches = find_matches_with_ripgrep(
            pattern="nonexistent",
            path=str(tmp_path),
            ignore_case=False,
            glob=None,
            file_type=None,
        )

        assert len(matches) == 0
