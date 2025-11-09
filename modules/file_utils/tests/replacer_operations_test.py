"""
Tests for replacer_operations module.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from file_utils.replacer_operations import Operation, OperationManager
from file_utils.replacer_state import FileContent, FileState


class TestOperation:
    """Tests for Operation dataclass."""

    def test_creation(self):
        """Test creating an Operation."""
        op = Operation(
            id=1,
            pattern="foo",
            replacement="bar",
            delete_line=False,
        )

        assert op.id == 1
        assert op.pattern == "foo"
        assert op.replacement == "bar"
        assert not op.delete_line
        assert not op.first_only
        assert op.specific_line is None
        assert op.max_per_file is None
        assert not op.ignore_case
        assert not op.blank_on_delete

    def test_execute_simple_replacement(self):
        """Test simple text replacement."""
        op = Operation(
            id=1,
            pattern="foo",
            replacement="bar",
            delete_line=False,
        )

        content = "foo is here\nfoo is there\nno match here\n"
        result, replacements, deletions = op.execute_on_content(content)

        assert result == "bar is here\nbar is there\nno match here\n"
        assert replacements == 2
        assert deletions == 0

    def test_execute_delete_line(self):
        """Test deleting lines."""
        op = Operation(
            id=1,
            pattern="delete",
            replacement=None,
            delete_line=True,
        )

        content = "keep this\ndelete this\nkeep this too\n"
        result, replacements, deletions = op.execute_on_content(content)

        assert result == "keep this\nkeep this too\n"
        assert replacements == 1
        assert deletions == 1

    def test_execute_delete_line_blank(self):
        """Test deleting lines with blank placeholder."""
        op = Operation(
            id=1,
            pattern="delete",
            replacement=None,
            delete_line=True,
            blank_on_delete=True,
        )

        content = "keep this\ndelete this\nkeep this too\n"
        result, replacements, deletions = op.execute_on_content(content)

        assert result == "keep this\n\nkeep this too\n"
        assert replacements == 1
        assert deletions == 1

    def test_execute_first_only(self):
        """Test first_only flag."""
        op = Operation(
            id=1,
            pattern="foo",
            replacement="bar",
            delete_line=False,
            first_only=True,
        )

        content = "foo\nfoo\nfoo\n"
        result, replacements, deletions = op.execute_on_content(content)

        assert result == "bar\nfoo\nfoo\n"
        assert replacements == 1
        assert deletions == 0

    def test_execute_specific_line(self):
        """Test specific_line flag."""
        op = Operation(
            id=1,
            pattern="foo",
            replacement="bar",
            delete_line=False,
            specific_line=2,
        )

        content = "foo on line 1\nfoo on line 2\nfoo on line 3\n"
        result, replacements, deletions = op.execute_on_content(content)

        assert result == "foo on line 1\nbar on line 2\nfoo on line 3\n"
        assert replacements == 1
        assert deletions == 0

    def test_execute_max_per_file(self):
        """Test max_per_file flag."""
        op = Operation(
            id=1,
            pattern="foo",
            replacement="bar",
            delete_line=False,
            max_per_file=2,
        )

        content = "foo\nfoo\nfoo\nfoo\n"
        result, replacements, deletions = op.execute_on_content(content)

        assert result == "bar\nbar\nfoo\nfoo\n"
        assert replacements == 2
        assert deletions == 0

    def test_execute_ignore_case(self):
        """Test case-insensitive matching."""
        op = Operation(
            id=1,
            pattern="foo",
            replacement="bar",
            delete_line=False,
            ignore_case=True,
        )

        content = "foo\nFOO\nFoO\n"
        result, replacements, deletions = op.execute_on_content(content)

        assert result == "bar\nbar\nbar\n"
        assert replacements == 3
        assert deletions == 0

    def test_execute_regex_pattern(self):
        """Test using regex patterns."""
        op = Operation(
            id=1,
            pattern=r"\d+",
            replacement="NUM",
            delete_line=False,
        )

        content = "test123\nno numbers\ntest456\n"
        result, replacements, deletions = op.execute_on_content(content)

        assert result == "testNUM\nno numbers\ntestNUM\n"
        assert replacements == 2
        assert deletions == 0

    def test_repr(self):
        """Test string representation."""
        op1 = Operation(
            id=1,
            pattern="foo",
            replacement="bar",
            delete_line=False,
        )

        op2 = Operation(
            id=2,
            pattern="delete",
            replacement=None,
            delete_line=True,
        )

        assert "Operation" in repr(op1)
        assert "#1" in repr(op1)
        assert "foo" in repr(op1)
        assert "replace" in repr(op1)

        assert "Operation" in repr(op2)
        assert "#2" in repr(op2)
        assert "delete" in repr(op2)


class TestOperationManager:
    """Tests for OperationManager class."""

    def test_creation(self):
        """Test creating an OperationManager."""
        manager = OperationManager()

        assert len(manager.operations) == 0
        assert manager.current_index == 0

    def test_add_operation(self):
        """Test adding operations."""
        manager = OperationManager()

        op1 = manager.add_operation(pattern="foo", replacement="bar")
        op2 = manager.add_operation(pattern="baz", replacement="qux")

        assert op1.id == 1
        assert op2.id == 2
        assert len(manager.operations) == 2
        assert manager.current_index == 2

    def test_execute_operation_on_state(self):
        """Test executing an operation on a FileState."""
        manager = OperationManager()
        op = manager.add_operation(pattern="foo", replacement="bar")

        # Create initial state
        state = FileState()
        path = Path("test.txt")
        fc = FileContent(
            path=path,
            original_lines=["foo is here\n", "foo is there\n"],
            current_lines=["foo is here\n", "foo is there\n"],
        )
        state.add_file(path, fc)

        # Execute operation
        new_state = manager.execute_operation(op, state)

        # Check new state
        new_fc = new_state.get_file(path)
        assert new_fc.current_lines == ["bar is here\n", "bar is there\n"]
        assert new_fc.is_modified

        # Original state unchanged
        orig_fc = state.get_file(path)
        assert orig_fc.current_lines == ["foo is here\n", "foo is there\n"]

    def test_execute_operation_multiple_files(self):
        """Test executing operation on multiple files."""
        manager = OperationManager()
        op = manager.add_operation(pattern="foo", replacement="bar")

        # Create state with multiple files
        state = FileState()
        path1 = Path("test1.txt")
        path2 = Path("test2.txt")

        fc1 = FileContent(
            path=path1,
            original_lines=["foo\n"],
            current_lines=["foo\n"],
        )
        fc2 = FileContent(
            path=path2,
            original_lines=["foo foo\n"],
            current_lines=["foo foo\n"],
        )

        state.add_file(path1, fc1)
        state.add_file(path2, fc2)

        # Execute
        new_state = manager.execute_operation(op, state)

        # Check both files modified
        assert new_state.get_file(path1).current_lines == ["bar\n"]
        assert new_state.get_file(path2).current_lines == ["bar bar\n"]

    def test_execute_all(self):
        """Test executing all operations."""
        manager = OperationManager()
        manager.add_operation(pattern="foo", replacement="bar")
        manager.add_operation(pattern="bar", replacement="baz")

        # Create initial state
        state = FileState()
        path = Path("test.txt")
        fc = FileContent(
            path=path,
            original_lines=["foo\n"],
            current_lines=["foo\n"],
        )
        state.add_file(path, fc)

        # Execute all
        final_state = manager.execute_all(state)

        # Should have both operations applied
        assert final_state.get_file(path).current_lines == ["baz\n"]

    def test_execute_all_up_to_index(self):
        """Test executing operations up to a specific index."""
        manager = OperationManager()
        manager.add_operation(pattern="a", replacement="b")
        manager.add_operation(pattern="b", replacement="c")
        manager.add_operation(pattern="c", replacement="d")

        # Create initial state
        state = FileState()
        path = Path("test.txt")
        fc = FileContent(
            path=path,
            original_lines=["a\n"],
            current_lines=["a\n"],
        )
        state.add_file(path, fc)

        # Execute only first 2 operations
        partial_state = manager.execute_all(state, up_to_index=2)

        assert partial_state.get_file(path).current_lines == ["c\n"]

    def test_get_operation(self):
        """Test getting operation by index."""
        manager = OperationManager()
        op1 = manager.add_operation(pattern="foo", replacement="bar")
        op2 = manager.add_operation(pattern="baz", replacement="qux")

        assert manager.get_operation(1) == op1
        assert manager.get_operation(2) == op2
        assert manager.get_operation(0) is None
        assert manager.get_operation(3) is None

    def test_rewind_to(self):
        """Test rewinding to a specific operation."""
        manager = OperationManager()
        manager.add_operation(pattern="a", replacement="b")
        manager.add_operation(pattern="b", replacement="c")
        manager.add_operation(pattern="c", replacement="d")

        # Create initial state
        initial_state = FileState()
        path = Path("test.txt")
        fc = FileContent(
            path=path,
            original_lines=["a\n"],
            current_lines=["a\n"],
        )
        initial_state.add_file(path, fc)

        # Rewind to operation 2
        state_at_2 = manager.rewind_to(2, initial_state)
        assert state_at_2.get_file(path).current_lines == ["c\n"]
        assert manager.current_index == 2

        # Rewind to operation 0 (original)
        state_at_0 = manager.rewind_to(0, initial_state)
        assert state_at_0.get_file(path).current_lines == ["a\n"]
        assert manager.current_index == 0

    def test_rewind_to_invalid_index(self):
        """Test rewinding to invalid index."""
        manager = OperationManager()
        manager.add_operation(pattern="foo", replacement="bar")

        state = FileState()

        with pytest.raises(ValueError):
            manager.rewind_to(-1, state)

        with pytest.raises(ValueError):
            manager.rewind_to(10, state)

    def test_get_current_operation(self):
        """Test getting the current operation."""
        manager = OperationManager()
        assert manager.get_current_operation() is None

        op1 = manager.add_operation(pattern="foo", replacement="bar")
        assert manager.get_current_operation() == op1

        op2 = manager.add_operation(pattern="baz", replacement="qux")
        assert manager.get_current_operation() == op2

        # Rewind
        manager.rewind_to(1, FileState())
        assert manager.get_current_operation() == op1

        manager.rewind_to(0, FileState())
        assert manager.get_current_operation() is None

    def test_can_undo_redo(self):
        """Test undo/redo capability checks."""
        manager = OperationManager()

        # No operations
        assert not manager.can_undo()
        assert not manager.can_redo()

        # Add operations
        manager.add_operation(pattern="foo", replacement="bar")
        manager.add_operation(pattern="baz", replacement="qux")

        # At end of history
        assert manager.can_undo()
        assert not manager.can_redo()

        # Rewind to middle
        manager.rewind_to(1, FileState())
        assert manager.can_undo()
        assert manager.can_redo()

        # Rewind to beginning
        manager.rewind_to(0, FileState())
        assert not manager.can_undo()
        assert manager.can_redo()

    def test_get_operation_count(self):
        """Test getting operation count."""
        manager = OperationManager()
        assert manager.get_operation_count() == 0

        manager.add_operation(pattern="foo", replacement="bar")
        assert manager.get_operation_count() == 1

        manager.add_operation(pattern="baz", replacement="qux")
        assert manager.get_operation_count() == 2

    def test_clear(self):
        """Test clearing operations."""
        manager = OperationManager()
        manager.add_operation(pattern="foo", replacement="bar")
        manager.add_operation(pattern="baz", replacement="qux")

        assert len(manager.operations) == 2

        manager.clear()

        assert len(manager.operations) == 0
        assert manager.current_index == 0
        assert manager._next_id == 1

    def test_operation_chaining(self):
        """Test chaining multiple operations."""
        manager = OperationManager()
        manager.add_operation(pattern="hello", replacement="hi")
        manager.add_operation(pattern="world", replacement="earth")
        manager.add_operation(pattern="hi", replacement="greetings")

        # Create initial state
        state = FileState()
        path = Path("test.txt")
        fc = FileContent(
            path=path,
            original_lines=["hello world\n"],
            current_lines=["hello world\n"],
        )
        state.add_file(path, fc)

        # Execute all operations in sequence
        final_state = manager.execute_all(state)

        # hello -> hi -> greetings, world -> earth
        assert final_state.get_file(path).current_lines == ["greetings earth\n"]

    def test_delete_line_operation(self):
        """Test delete line operation through manager."""
        manager = OperationManager()
        manager.add_operation(pattern="delete", replacement=None, delete_line=True)

        state = FileState()
        path = Path("test.txt")
        fc = FileContent(
            path=path,
            original_lines=["keep\n", "delete this\n", "keep\n"],
            current_lines=["keep\n", "delete this\n", "keep\n"],
        )
        state.add_file(path, fc)

        final_state = manager.execute_all(state)
        assert final_state.get_file(path).current_lines == ["keep\n", "keep\n"]

    def test_repr(self):
        """Test string representation."""
        manager = OperationManager()
        manager.add_operation(pattern="foo", replacement="bar")

        repr_str = repr(manager)
        assert "OperationManager" in repr_str
        assert "operations=1" in repr_str
        assert "current=1" in repr_str


class TestOperationManagerIntegration:
    """Integration tests for OperationManager with FileState."""

    def test_complex_workflow(self):
        """Test a complex workflow with multiple operations and rewinding."""
        manager = OperationManager()

        # Add operations
        op1 = manager.add_operation(pattern="TODO", replacement="DONE")
        op2 = manager.add_operation(pattern="FIXME", replacement="FIXED")
        op3 = manager.add_operation(pattern="DEBUG", delete_line=True)

        # Create initial state with multiple files
        state = FileState()

        file1 = Path("file1.txt")
        fc1 = FileContent(
            path=file1,
            original_lines=["TODO: task 1\n", "FIXME: bug 1\n", "DEBUG: log\n", "normal line\n"],
            current_lines=["TODO: task 1\n", "FIXME: bug 1\n", "DEBUG: log\n", "normal line\n"],
        )

        file2 = Path("file2.txt")
        fc2 = FileContent(
            path=file2,
            original_lines=["TODO: task 2\n"],
            current_lines=["TODO: task 2\n"],
        )

        state.add_file(file1, fc1)
        state.add_file(file2, fc2)

        # Execute all operations
        final_state = manager.execute_all(state)

        # Check file1 results
        file1_lines = final_state.get_file(file1).current_lines
        assert file1_lines == ["DONE: task 1\n", "FIXED: bug 1\n", "normal line\n"]

        # Check file2 results
        file2_lines = final_state.get_file(file2).current_lines
        assert file2_lines == ["DONE: task 2\n"]

        # Rewind to operation 1 (only TODO replaced)
        state_at_1 = manager.rewind_to(1, state)
        file1_at_1 = state_at_1.get_file(file1).current_lines
        assert file1_at_1 == ["DONE: task 1\n", "FIXME: bug 1\n", "DEBUG: log\n", "normal line\n"]

        # Rewind to operation 2 (TODO and FIXME replaced)
        state_at_2 = manager.rewind_to(2, state)
        file1_at_2 = state_at_2.get_file(file1).current_lines
        assert file1_at_2 == ["DONE: task 1\n", "FIXED: bug 1\n", "DEBUG: log\n", "normal line\n"]

    def test_no_matches_operation(self):
        """Test operation that matches nothing."""
        manager = OperationManager()
        manager.add_operation(pattern="nonexistent", replacement="replacement")

        state = FileState()
        path = Path("test.txt")
        fc = FileContent(
            path=path,
            original_lines=["line 1\n", "line 2\n"],
            current_lines=["line 1\n", "line 2\n"],
        )
        state.add_file(path, fc)

        final_state = manager.execute_all(state)

        # Should be unchanged
        assert final_state.get_file(path).current_lines == ["line 1\n", "line 2\n"]
        assert not final_state.get_file(path).is_modified
