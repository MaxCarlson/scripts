"""
Operation management for interactive replacer mode.

Provides operation history, chaining, and execution against FileState.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .replacer_state import FileState


@dataclass
class Operation:
    """
    Encapsulates a single find/replace operation's parameters.

    Operations are immutable once created.
    """
    id: int
    pattern: str
    replacement: Optional[str]
    delete_line: bool
    first_only: bool = False
    specific_line: Optional[int] = None
    max_per_file: Optional[int] = None
    ignore_case: bool = False
    blank_on_delete: bool = False
    timestamp: datetime = datetime.now()

    def execute_on_content(self, file_content: str) -> tuple[str, int, int]:
        """
        Execute this operation on file content.

        Args:
            file_content: Content as a single string

        Returns:
            Tuple of (modified_content, replacements_made, lines_deleted)
        """
        lines = file_content.splitlines(keepends=True)
        modified_lines = []
        replacements_count = 0
        deletions_count = 0

        # Compile regex pattern
        regex_flags = re.IGNORECASE if self.ignore_case else 0
        compiled_pattern = re.compile(self.pattern, regex_flags)

        for line_num, line in enumerate(lines, start=1):
            # Check if we should process this line
            if self.specific_line is not None and line_num != self.specific_line:
                modified_lines.append(line)
                continue

            # Check if we've hit the max replacements
            if self.max_per_file is not None and replacements_count >= self.max_per_file:
                modified_lines.append(line)
                continue

            # Check if line contains the pattern
            if compiled_pattern.search(line):
                if self.delete_line:
                    # Delete the entire line
                    deletions_count += 1
                    replacements_count += 1
                    # Either leave a blank line or don't append at all (pull up)
                    if self.blank_on_delete:
                        modified_lines.append("\n")
                    # else: don't append (pull up)
                    continue
                elif self.replacement is not None:
                    # Replace the pattern
                    if self.first_only and replacements_count > 0:
                        modified_lines.append(line)
                    else:
                        # Replace all occurrences in this line (or just first if first_only)
                        new_line = compiled_pattern.sub(
                            self.replacement, line, count=1 if self.first_only else 0
                        )
                        modified_lines.append(new_line)
                        replacements_count += 1
                else:
                    modified_lines.append(line)
            else:
                modified_lines.append(line)

        return (''.join(modified_lines), replacements_count, deletions_count)

    def __repr__(self) -> str:
        """String representation of operation."""
        action = "delete" if self.delete_line else f"replace with '{self.replacement}'"
        return f"Operation(#{self.id}: '{self.pattern}' -> {action})"


class OperationManager:
    """
    Manages operation history and execution.

    Supports:
    - Adding operations
    - Executing operations on FileState
    - Rewinding to previous states
    - Operation history tracking
    """

    def __init__(self):
        self.operations: List[Operation] = []
        self.current_index: int = 0  # Index of current operation (0 = original state)
        self._next_id: int = 1

    def add_operation(
        self,
        pattern: str,
        replacement: Optional[str] = None,
        delete_line: bool = False,
        first_only: bool = False,
        specific_line: Optional[int] = None,
        max_per_file: Optional[int] = None,
        ignore_case: bool = False,
        blank_on_delete: bool = False,
    ) -> Operation:
        """
        Add a new operation.

        Args:
            pattern: Regex pattern to search for
            replacement: Replacement text (None if deleting)
            delete_line: If True, delete entire line
            first_only: Only replace first match per file
            specific_line: Only replace on this line number
            max_per_file: Maximum replacements per file
            ignore_case: Case insensitive search
            blank_on_delete: Leave blank line when deleting

        Returns:
            The created Operation
        """
        op = Operation(
            id=self._next_id,
            pattern=pattern,
            replacement=replacement,
            delete_line=delete_line,
            first_only=first_only,
            specific_line=specific_line,
            max_per_file=max_per_file,
            ignore_case=ignore_case,
            blank_on_delete=blank_on_delete,
            timestamp=datetime.now(),
        )
        self.operations.append(op)
        self._next_id += 1
        self.current_index = len(self.operations)
        return op

    def execute_operation(self, operation: Operation, state: FileState) -> FileState:
        """
        Execute an operation on a FileState.

        Creates a new FileState with the operation applied to all files.

        Args:
            operation: Operation to execute
            state: Current state

        Returns:
            New FileState with operation applied
        """
        new_state = state.clone()

        for path, file_content in new_state.files.items():
            # Convert lines to string for processing
            content_str = ''.join(file_content.current_lines)

            # Execute operation
            modified_content, replacements, deletions = operation.execute_on_content(content_str)

            # Update state if changes were made
            if replacements > 0 or deletions > 0:
                modified_lines = modified_content.splitlines(keepends=True)
                # Ensure lines end with newline if original did
                if file_content.current_lines and not modified_lines:
                    # File was emptied
                    modified_lines = []
                elif file_content.current_lines and file_content.current_lines[-1].endswith('\n'):
                    # Ensure last line has newline if original did
                    if modified_lines and not modified_lines[-1].endswith('\n'):
                        modified_lines[-1] += '\n'

                modification_note = f"Op #{operation.id}: {replacements} replacements, {deletions} deletions"
                new_state.set_file_content(path, modified_lines, modification_note)

        return new_state

    def execute_all(self, initial_state: FileState, up_to_index: Optional[int] = None) -> FileState:
        """
        Execute all operations up to a certain index.

        Args:
            initial_state: Starting state
            up_to_index: Execute up to this index (exclusive). None = all operations

        Returns:
            Final FileState after all operations
        """
        state = initial_state.clone()
        end_index = up_to_index if up_to_index is not None else len(self.operations)

        for i in range(end_index):
            state = self.execute_operation(self.operations[i], state)

        return state

    def get_operation(self, index: int) -> Optional[Operation]:
        """
        Get operation by index (1-based).

        Args:
            index: Operation index (1-based)

        Returns:
            Operation or None if index invalid
        """
        if 0 < index <= len(self.operations):
            return self.operations[index - 1]
        return None

    def rewind_to(self, index: int, initial_state: FileState) -> FileState:
        """
        Rewind to a specific operation index.

        Args:
            index: Operation index to rewind to (0 = original state)
            initial_state: Original starting state

        Returns:
            FileState at that point in history
        """
        if index < 0 or index > len(self.operations):
            raise ValueError(f"Invalid index: {index}")

        self.current_index = index
        return self.execute_all(initial_state, up_to_index=index)

    def get_current_operation(self) -> Optional[Operation]:
        """Get the current operation (the one most recently applied)."""
        if self.current_index > 0 and self.current_index <= len(self.operations):
            return self.operations[self.current_index - 1]
        return None

    def can_undo(self) -> bool:
        """Check if we can undo (go back one operation)."""
        return self.current_index > 0

    def can_redo(self) -> bool:
        """Check if we can redo (go forward one operation)."""
        return self.current_index < len(self.operations)

    def get_operation_count(self) -> int:
        """Get total number of operations."""
        return len(self.operations)

    def clear(self):
        """Clear all operations and reset state."""
        self.operations.clear()
        self.current_index = 0
        self._next_id = 1

    def __repr__(self) -> str:
        """String representation of manager."""
        return f"OperationManager(operations={len(self.operations)}, current={self.current_index})"
