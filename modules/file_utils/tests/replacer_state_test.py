"""
Tests for replacer_state module.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from file_utils.replacer_state import FileContent, FileState


class TestFileContent:
    """Tests for FileContent dataclass."""

    def test_creation(self):
        """Test creating a FileContent object."""
        fc = FileContent(
            path=Path("test.txt"),
            original_lines=["line 1\n", "line 2\n"],
            current_lines=["line 1\n", "line 2\n"],
        )

        assert fc.path == Path("test.txt")
        assert fc.original_lines == ["line 1\n", "line 2\n"]
        assert fc.current_lines == ["line 1\n", "line 2\n"]
        assert not fc.is_modified

    def test_is_modified(self):
        """Test is_modified property."""
        fc = FileContent(
            path=Path("test.txt"),
            original_lines=["line 1\n", "line 2\n"],
            current_lines=["line 1\n", "line 2 modified\n"],
        )

        assert fc.is_modified

    def test_diff_stats_no_changes(self):
        """Test diff_stats with no changes."""
        fc = FileContent(
            path=Path("test.txt"),
            original_lines=["line 1\n", "line 2\n"],
            current_lines=["line 1\n", "line 2\n"],
        )

        additions, deletions = fc.diff_stats
        assert additions == 0
        assert deletions == 0

    def test_diff_stats_with_addition(self):
        """Test diff_stats with additions."""
        fc = FileContent(
            path=Path("test.txt"),
            original_lines=["line 1\n"],
            current_lines=["line 1\n", "line 2\n"],
        )

        additions, deletions = fc.diff_stats
        assert additions == 1
        assert deletions == 0

    def test_diff_stats_with_deletion(self):
        """Test diff_stats with deletions."""
        fc = FileContent(
            path=Path("test.txt"),
            original_lines=["line 1\n", "line 2\n"],
            current_lines=["line 1\n"],
        )

        additions, deletions = fc.diff_stats
        assert additions == 0
        assert deletions == 1

    def test_diff_stats_with_replacement(self):
        """Test diff_stats with replacements."""
        fc = FileContent(
            path=Path("test.txt"),
            original_lines=["line 1\n", "line 2\n"],
            current_lines=["line 1\n", "line 2 modified\n"],
        )

        additions, deletions = fc.diff_stats
        assert additions == 1
        assert deletions == 1

    def test_get_unified_diff(self):
        """Test unified diff generation."""
        fc = FileContent(
            path=Path("test.txt"),
            original_lines=["line 1\n", "line 2\n"],
            current_lines=["line 1\n", "line 2 modified\n"],
        )

        diff = fc.get_unified_diff()
        assert "--- test.txt" in diff
        assert "+++ test.txt" in diff
        assert "-line 2" in diff
        assert "+line 2 modified" in diff

    def test_clone(self):
        """Test cloning FileContent."""
        fc1 = FileContent(
            path=Path("test.txt"),
            original_lines=["line 1\n"],
            current_lines=["line 1 modified\n"],
            modifications=["Op #1: changed line 1"],
        )

        fc2 = fc1.clone()

        # Check it's a different object
        assert fc2 is not fc1
        assert fc2.original_lines is not fc1.original_lines
        assert fc2.current_lines is not fc1.current_lines

        # Check values are equal
        assert fc2.path == fc1.path
        assert fc2.original_lines == fc1.original_lines
        assert fc2.current_lines == fc1.current_lines
        assert fc2.modifications == fc1.modifications

        # Mutate clone and ensure original unchanged
        fc2.current_lines.append("new line\n")
        assert len(fc1.current_lines) == 1
        assert len(fc2.current_lines) == 2


class TestFileState:
    """Tests for FileState class."""

    def test_creation(self):
        """Test creating a FileState."""
        state = FileState()

        assert len(state.files) == 0
        assert len(state.modified) == 0

    def test_add_file_from_disk(self, tmp_path: Path):
        """Test adding a file from disk."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line 1\nline 2\n")

        state = FileState()
        state.add_file(test_file)

        assert test_file in state.files
        file_content = state.get_file(test_file)
        assert file_content is not None
        assert file_content.original_lines == ["line 1\n", "line 2\n"]
        assert file_content.current_lines == ["line 1\n", "line 2\n"]
        assert not file_content.is_modified

    def test_add_file_with_content(self):
        """Test adding a file with FileContent."""
        path = Path("test.txt")
        fc = FileContent(
            path=path,
            original_lines=["line 1\n"],
            current_lines=["line 1 modified\n"],
        )

        state = FileState()
        state.add_file(path, fc)

        assert path in state.files
        assert path in state.modified  # Should be marked as modified

    def test_get_file(self):
        """Test getting a file."""
        path = Path("test.txt")
        fc = FileContent(
            path=path,
            original_lines=["line 1\n"],
            current_lines=["line 1\n"],
        )

        state = FileState()
        state.add_file(path, fc)

        retrieved = state.get_file(path)
        assert retrieved is fc

    def test_get_file_not_found(self):
        """Test getting a non-existent file."""
        state = FileState()
        assert state.get_file(Path("nonexistent.txt")) is None

    def test_set_file_content(self):
        """Test setting file content."""
        path = Path("test.txt")
        fc = FileContent(
            path=path,
            original_lines=["line 1\n"],
            current_lines=["line 1\n"],
        )

        state = FileState()
        state.add_file(path, fc)

        # Modify content
        state.set_file_content(path, ["line 1 modified\n"], "Test modification")

        file_content = state.get_file(path)
        assert file_content.current_lines == ["line 1 modified\n"]
        assert file_content.is_modified
        assert path in state.modified
        assert "Test modification" in file_content.modifications

    def test_get_diff(self):
        """Test getting diff for a file."""
        path = Path("test.txt")
        fc = FileContent(
            path=path,
            original_lines=["line 1\n", "line 2\n"],
            current_lines=["line 1\n", "line 2 modified\n"],
        )

        state = FileState()
        state.add_file(path, fc)

        diff = state.get_diff(path)
        assert "--- test.txt" in diff
        assert "+++ test.txt" in diff
        assert "-line 2" in diff
        assert "+line 2 modified" in diff

    def test_get_all_diffs(self):
        """Test getting all diffs."""
        path1 = Path("test1.txt")
        path2 = Path("test2.txt")

        fc1 = FileContent(
            path=path1,
            original_lines=["line 1\n"],
            current_lines=["line 1 modified\n"],
        )
        fc2 = FileContent(
            path=path2,
            original_lines=["line 1\n"],
            current_lines=["line 1\n"],  # Unmodified
        )

        state = FileState()
        state.add_file(path1, fc1)
        state.add_file(path2, fc2)

        diffs = state.get_all_diffs()
        assert len(diffs) == 1  # Only modified file
        assert path1 in diffs
        assert path2 not in diffs

    def test_get_diff_stats(self):
        """Test getting diff stats for a file."""
        path = Path("test.txt")
        fc = FileContent(
            path=path,
            original_lines=["line 1\n", "line 2\n"],
            current_lines=["line 1\n", "line 2 modified\n", "line 3\n"],
        )

        state = FileState()
        state.add_file(path, fc)

        additions, deletions = state.get_diff_stats(path)
        assert additions == 2
        assert deletions == 1

    def test_clone(self):
        """Test cloning a FileState."""
        path = Path("test.txt")
        fc = FileContent(
            path=path,
            original_lines=["line 1\n"],
            current_lines=["line 1 modified\n"],
        )

        state1 = FileState()
        state1.add_file(path, fc)

        state2 = state1.clone()

        # Check it's a different object
        assert state2 is not state1
        assert state2.files is not state1.files

        # Check values are equal
        assert len(state2.files) == len(state1.files)
        assert path in state2.files

        # Mutate clone and ensure original unchanged
        state2.set_file_content(path, ["completely new\n"])
        assert state1.get_file(path).current_lines == ["line 1 modified\n"]
        assert state2.get_file(path).current_lines == ["completely new\n"]

    def test_write_to_disk(self, tmp_path: Path):
        """Test writing modified files to disk."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("original\n")

        state = FileState()
        state.add_file(test_file)
        state.set_file_content(test_file, ["modified\n"])

        written = state.write_to_disk()

        assert test_file in written
        assert test_file.read_text() == "modified\n"

    def test_get_modified_files(self):
        """Test getting list of modified files."""
        path1 = Path("test1.txt")
        path2 = Path("test2.txt")
        path3 = Path("test3.txt")

        fc1 = FileContent(path=path1, original_lines=["a\n"], current_lines=["b\n"])
        fc2 = FileContent(path=path2, original_lines=["a\n"], current_lines=["a\n"])
        fc3 = FileContent(path=path3, original_lines=["a\n"], current_lines=["c\n"])

        state = FileState()
        state.add_file(path1, fc1)
        state.add_file(path2, fc2)
        state.add_file(path3, fc3)

        modified = state.get_modified_files()
        assert len(modified) == 2
        assert path1 in modified
        assert path3 in modified
        assert path2 not in modified

    def test_has_modifications(self):
        """Test checking if state has modifications."""
        path = Path("test.txt")
        fc = FileContent(
            path=path,
            original_lines=["line 1\n"],
            current_lines=["line 1\n"],
        )

        state = FileState()
        state.add_file(path, fc)

        assert not state.has_modifications()

        # Modify
        state.set_file_content(path, ["line 1 modified\n"])
        assert state.has_modifications()

    def test_get_total_stats(self):
        """Test getting total stats across all files."""
        path1 = Path("test1.txt")
        path2 = Path("test2.txt")

        fc1 = FileContent(
            path=path1,
            original_lines=["line 1\n", "line 2\n"],
            current_lines=["line 1 modified\n"],  # +1, -2
        )
        fc2 = FileContent(
            path=path2,
            original_lines=["line 1\n"],
            current_lines=["line 1\n", "line 2\n", "line 3\n"],  # +2, -0
        )

        state = FileState()
        state.add_file(path1, fc1)
        state.add_file(path2, fc2)

        total_additions, total_deletions = state.get_total_stats()
        assert total_additions == 3
        assert total_deletions == 2

    def test_repr(self):
        """Test string representation."""
        state = FileState()
        state.add_file(
            Path("test.txt"),
            FileContent(
                path=Path("test.txt"),
                original_lines=["a\n"],
                current_lines=["b\n"],
            ),
        )

        repr_str = repr(state)
        assert "FileState" in repr_str
        assert "files=1" in repr_str
        assert "modified=1" in repr_str
