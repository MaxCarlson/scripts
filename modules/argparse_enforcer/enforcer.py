"""
Argparse wrapper that enforces strict argument naming conventions.

Conventions:
- Abbreviated: single dash + single char (e.g., -f, -F)
- Full: double dash + words separated by dashes (e.g., --full-length)
- Two-char abbreviated allowed when >15 args or all single chars exhausted
"""
import argparse
import string
from typing import Optional, Any

try:
    import argcomplete
    ARGCOMPLETE_AVAILABLE = True
except ImportError:
    ARGCOMPLETE_AVAILABLE = False


class EnforcedArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that enforces abbreviated and full-length argument pairs."""

    def __init__(self, *args, allow_two_char_threshold: int = 15,
                 enable_autocomplete: bool = True, **kwargs):
        """
        Initialize the parser.

        Args:
            allow_two_char_threshold: Number of arguments after which two-char
                                     abbreviated forms are allowed (default: 15)
            enable_autocomplete: Automatically setup argcomplete if available (default: True)
        """
        super().__init__(*args, **kwargs)
        self._used_single_chars = set()
        self._arg_count = 0
        self._allow_two_char_threshold = allow_two_char_threshold
        self._all_single_chars = set(string.ascii_letters)
        self._enable_autocomplete = enable_autocomplete
        self._autocomplete_setup = False

    def add_argument(self, *args, **kwargs) -> argparse.Action:
        """
        Add an argument with enforced naming conventions.

        Requires both abbreviated and full-length forms.
        Abbreviated: -x (single char) or -xy (two chars if threshold reached)
        Full: --word-separated-by-dashes

        Args:
            *args: Should be exactly 2 strings (abbreviated, full)
            **kwargs: Standard argparse keyword arguments

        Returns:
            The created Action object

        Raises:
            ValueError: If argument naming conventions are violated
        """
        # Allow positional arguments and special cases to pass through
        if not args or not any(arg.startswith('-') for arg in args):
            return super().add_argument(*args, **kwargs)

        # Filter out only the option strings
        option_strings = [arg for arg in args if arg.startswith('-')]

        # Allow built-in help and version arguments to pass through without validation
        if kwargs.get('action') in ['help', 'version']:
            return super().add_argument(*args, **kwargs)

        # Must have exactly 2 option strings
        if len(option_strings) != 2:
            raise ValueError(
                f"Must provide exactly 2 argument forms (abbreviated and full). "
                f"Got: {option_strings}"
            )

        # Sort to identify abbreviated vs full
        abbreviated, full = sorted(option_strings, key=lambda x: len(x))

        # Validate abbreviated form
        self._validate_abbreviated(abbreviated)

        # Validate full form
        self._validate_full(full)

        # Track usage
        if len(abbreviated) == 2:  # Single dash + single char
            char = abbreviated[1]
            if char in self._used_single_chars:
                raise ValueError(f"Character '{char}' already used in another argument")
            self._used_single_chars.add(char)

        self._arg_count += 1

        # Call parent with validated arguments
        return super().add_argument(abbreviated, full, **kwargs)

    def _validate_abbreviated(self, arg: str) -> None:
        """Validate the abbreviated argument form."""
        if not arg.startswith('-') or arg.startswith('--'):
            raise ValueError(
                f"Abbreviated form must start with single dash. Got: {arg}"
            )

        chars = arg[1:]  # Remove leading dash

        # Check length
        if len(chars) == 1:
            # Single char - always allowed
            if not chars.isalpha():
                raise ValueError(
                    f"Abbreviated form must be alphabetic character. Got: {arg}"
                )
        elif len(chars) == 2:
            # Two chars - check if allowed
            all_exhausted = len(self._used_single_chars) >= len(self._all_single_chars)
            threshold_reached = self._arg_count >= self._allow_two_char_threshold

            if not (all_exhausted or threshold_reached):
                raise ValueError(
                    f"Two-char abbreviated form only allowed after {self._allow_two_char_threshold} "
                    f"arguments or when all single chars exhausted. Got: {arg}"
                )

            if not chars.isalpha():
                raise ValueError(
                    f"Abbreviated form must be alphabetic characters. Got: {arg}"
                )
        else:
            raise ValueError(
                f"Abbreviated form must be 1-2 characters. Got: {arg}"
            )

    def _validate_full(self, arg: str) -> None:
        """Validate the full-length argument form."""
        if not arg.startswith('--'):
            raise ValueError(
                f"Full form must start with double dash. Got: {arg}"
            )

        name = arg[2:]  # Remove leading dashes

        if not name:
            raise ValueError(f"Full form cannot be empty. Got: {arg}")

        # Check that it uses dashes for word separation (if multi-word)
        # and contains only lowercase letters, digits, and dashes
        for char in name:
            if not (char.islower() or char.isdigit() or char == '-'):
                raise ValueError(
                    f"Full form must use lowercase letters, digits, and dashes. Got: {arg}"
                )

        # Check for invalid dash patterns
        if name.startswith('-') or name.endswith('-') or '--' in name:
            raise ValueError(
                f"Full form has invalid dash placement. Got: {arg}"
            )

    def parse_args(self, args=None, namespace=None):
        """
        Parse arguments with automatic argcomplete setup.

        Args:
            args: List of strings to parse (default: sys.argv)
            namespace: Object to take attributes (default: new Namespace)

        Returns:
            Namespace object with parsed arguments
        """
        # Setup argcomplete if enabled and available
        if self._enable_autocomplete and ARGCOMPLETE_AVAILABLE and not self._autocomplete_setup:
            argcomplete.autocomplete(self)
            self._autocomplete_setup = True
        elif self._enable_autocomplete and not ARGCOMPLETE_AVAILABLE and not self._autocomplete_setup:
            self._print_argcomplete_info()
            self._autocomplete_setup = True

        return super().parse_args(args, namespace)

    def parse_known_args(self, args=None, namespace=None):
        """
        Parse known arguments with automatic argcomplete setup.

        Args:
            args: List of strings to parse (default: sys.argv)
            namespace: Object to take attributes (default: new Namespace)

        Returns:
            Tuple of (Namespace, remaining args)
        """
        # Setup argcomplete if enabled and available
        if self._enable_autocomplete and ARGCOMPLETE_AVAILABLE and not self._autocomplete_setup:
            argcomplete.autocomplete(self)
            self._autocomplete_setup = True
        elif self._enable_autocomplete and not ARGCOMPLETE_AVAILABLE and not self._autocomplete_setup:
            self._print_argcomplete_info()
            self._autocomplete_setup = True

        return super().parse_known_args(args, namespace)

    def _print_argcomplete_info(self):
        """Print information about argcomplete setup if not installed."""
        import sys
        import os

        # Only print once and only to stderr to avoid interfering with script output
        print("\nNote: argcomplete is not installed. Tab completion is disabled.", file=sys.stderr)
        print("To enable tab completion:", file=sys.stderr)
        print("  1. Install: pip install argcomplete", file=sys.stderr)
        print("  2. Setup:   python -m argparse_enforcer.setup_instructions", file=sys.stderr)
        print("", file=sys.stderr)
