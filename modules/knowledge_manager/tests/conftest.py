#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Test configuration helpers.

Pytest attempts to create its temporary work area under the OS temp directory
(e.g., %LOCALAPPDATA%\\Temp on Windows). In locked-down environments that
location may be inaccessible, causing PermissionError during test collection.

To keep the suite runnable everywhere, we force a writable temp root inside the
repository. All tmp_path/tmpdir allocations and any code that respects standard
TMP/TEMP variables will live under this folder.
"""

from __future__ import annotations

from pathlib import Path
import os

import pytest

_TEST_TEMP_ROOT = Path(__file__).parent / ".pytest_tmp"


def _ensure_temp_root() -> Path:
    _TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    return _TEST_TEMP_ROOT


def pytest_configure(config: pytest.Config) -> None:
    """Force pytest's --basetemp to a repo-local writable directory."""
    base = _ensure_temp_root()
    if not getattr(config.option, "basetemp", None):
        config.option.basetemp = str(base)


@pytest.fixture(scope="session", autouse=True)
def _configure_temp_environment() -> None:
    """
    Ensure TMP/TEMP/TMPDIR point at the repo-local temp root for the duration
    of the test session.
    """
    base = _ensure_temp_root()
    monkey = pytest.MonkeyPatch()
    for var in ("TMPDIR", "TEMP", "TMP", "TMPPATH"):
        monkey.setenv(var, str(base))
    try:
        yield
    finally:
        monkey.undo()


@pytest.fixture(scope="session", autouse=True)
def _configure_test_database() -> None:
    """
    Configure test database to prevent pollution of production database.

    Sets KM_POSTGRES_DB to knowledge_manager_test so tests don't create
    TEST_ artifacts in the production database.
    """
    monkey = pytest.MonkeyPatch()

    # Use separate test database
    monkey.setenv("KM_POSTGRES_DB", "knowledge_manager_test")

    # Also set a marker so tests can detect they're in test mode
    monkey.setenv("KM_TEST_MODE", "1")

    try:
        yield
    finally:
        monkey.undo()
