"""Smoke fixture: substring grep implementation."""


def grep(pattern: str, lines: list[str], ignore_case: bool = False) -> list[str]:
    """Search for lines containing the literal substring pattern.

    Args:
        pattern: The literal substring to search for (not regex).
        lines: Sequence of input lines to filter.
        ignore_case: Whether to perform case-insensitive matching.

    Returns:
        List of matching lines in their original order.
    """
    raise NotImplementedError("grep is not yet implemented")
