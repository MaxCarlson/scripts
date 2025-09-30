"""
Pytest configuration for argparse_enforcer tests.
"""
import pytest
import sys


@pytest.fixture(autouse=True)
def suppress_argcomplete_warning(monkeypatch):
    """Suppress argcomplete warning during tests."""
    # Redirect stderr to devnull during tests to avoid cluttering test output
    import io
    monkeypatch.setattr(sys, "stderr", io.StringIO())
