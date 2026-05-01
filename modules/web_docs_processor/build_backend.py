"""
PEP 517 build backend wrapper for web-docs-processor.

The project uses setuptools for normal package building, then installs
Playwright's Chromium runtime as part of the normal editable/wheel build path.
This preserves the repo's expected install command:

    python -m pip install -e modules/web_docs_processor
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from typing import Any

from setuptools import build_meta as _setuptools_build_meta


def should_skip_playwright_browser_install() -> bool:
    """
    Return True when browser installation should be skipped.
    """
    value = os.environ.get("WDP_SKIP_PLAYWRIGHT_INSTALL", "").strip().lower()
    return value in {"1", "true", "yes", "y", "on"}


def install_playwright_chromium() -> None:
    """
    Install Playwright's Chromium browser runtime.
    """
    if should_skip_playwright_browser_install():
        print(
            "[web-docs-processor] Skipping Playwright Chromium install because "
            "WDP_SKIP_PLAYWRIGHT_INSTALL is set.",
            file=sys.stderr,
        )
        return

    command = [
        sys.executable,
        "-m",
        "playwright",
        "install",
        "chromium",
    ]

    print(
        "[web-docs-processor] Installing Playwright Chromium runtime...",
        file=sys.stderr,
    )
    subprocess.run(command, check=True)
    print(
        "[web-docs-processor] Playwright Chromium runtime is installed.",
        file=sys.stderr,
    )


def run_with_setuppy_browser_hook_disabled(build_call: Callable[[], str]) -> str:
    """
    Run a setuptools build while preventing duplicate setup.py browser installs.
    """
    previous_value = os.environ.get("WDP_BUILD_BACKEND_ACTIVE")
    os.environ["WDP_BUILD_BACKEND_ACTIVE"] = "1"
    try:
        return build_call()
    finally:
        if previous_value is None:
            os.environ.pop("WDP_BUILD_BACKEND_ACTIVE", None)
        else:
            os.environ["WDP_BUILD_BACKEND_ACTIVE"] = previous_value


def build_wheel(
    wheel_directory: str,
    config_settings: dict[str, Any] | None = None,
    metadata_directory: str | None = None,
) -> str:
    """
    Build a wheel, then install Playwright Chromium.
    """
    wheel_name = run_with_setuppy_browser_hook_disabled(
        lambda: _setuptools_build_meta.build_wheel(
            wheel_directory,
            config_settings=config_settings,
            metadata_directory=metadata_directory,
        )
    )
    install_playwright_chromium()
    return wheel_name


def build_editable(
    wheel_directory: str,
    config_settings: dict[str, Any] | None = None,
    metadata_directory: str | None = None,
) -> str:
    """
    Build an editable wheel, then install Playwright Chromium.
    """
    wheel_name = run_with_setuppy_browser_hook_disabled(
        lambda: _setuptools_build_meta.build_editable(
            wheel_directory,
            config_settings=config_settings,
            metadata_directory=metadata_directory,
        )
    )
    install_playwright_chromium()
    return wheel_name


def get_requires_for_build_wheel(config_settings: dict[str, Any] | None = None) -> list[str]:
    """
    Return additional wheel-build requirements from setuptools.
    """
    return _setuptools_build_meta.get_requires_for_build_wheel(config_settings=config_settings)


def get_requires_for_build_editable(config_settings: dict[str, Any] | None = None) -> list[str]:
    """
    Return additional editable-build requirements from setuptools.
    """
    return _setuptools_build_meta.get_requires_for_build_editable(config_settings=config_settings)


def prepare_metadata_for_build_wheel(
    metadata_directory: str,
    config_settings: dict[str, Any] | None = None,
) -> str:
    """
    Prepare wheel metadata through setuptools.
    """
    return _setuptools_build_meta.prepare_metadata_for_build_wheel(
        metadata_directory,
        config_settings=config_settings,
    )


def prepare_metadata_for_build_editable(
    metadata_directory: str,
    config_settings: dict[str, Any] | None = None,
) -> str:
    """
    Prepare editable metadata through setuptools.
    """
    return _setuptools_build_meta.prepare_metadata_for_build_editable(
        metadata_directory,
        config_settings=config_settings,
    )
