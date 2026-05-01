"""
Setuptools install hooks for web-docs-processor.

This module intentionally installs the full runtime by default because it is a
personal scripts module. Playwright's Python package is installed through
pyproject.toml dependencies, while Chromium is a Playwright-managed browser
runtime installed by Playwright's own CLI.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

from setuptools import setup
from setuptools.command.install import install

try:
    from setuptools.command.develop import develop
except ImportError:
    develop = None  # type: ignore[assignment]

try:
    from setuptools.command.editable_wheel import editable_wheel
except ImportError:
    editable_wheel = None  # type: ignore[assignment]


def should_skip_playwright_browser_install() -> bool:
    """
    Return True when browser installation should be skipped.

    Set WDP_SKIP_PLAYWRIGHT_INSTALL=1 for constrained or offline environments.
    """
    value = os.environ.get("WDP_SKIP_PLAYWRIGHT_INSTALL", "").strip().lower()
    return value in {"1", "true", "yes", "y", "on"}


def install_playwright_chromium() -> None:
    """
    Install Playwright's Chromium browser runtime.

    The command is idempotent. If Chromium already exists in Playwright's cache,
    Playwright reuses it.
    """
    if os.environ.get("WDP_BUILD_BACKEND_ACTIVE", "").strip().lower() in {"1", "true", "yes", "y", "on"}:
        return

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


class InstallWithPlaywrightChromium(install):
    """
    Install package and then install Playwright Chromium.
    """

    def run(self) -> None:
        super().run()
        install_playwright_chromium()


if develop is not None:

    class DevelopWithPlaywrightChromium(develop):  # type: ignore[misc, valid-type]
        """
        Editable legacy develop install plus Playwright Chromium.
        """

        def run(self) -> None:
            super().run()
            install_playwright_chromium()

else:
    DevelopWithPlaywrightChromium = None  # type: ignore[assignment]


if editable_wheel is not None:

    class EditableWheelWithPlaywrightChromium(editable_wheel):  # type: ignore[misc, valid-type]
        """
        PEP 660 editable wheel build plus Playwright Chromium.
        """

        def run(self) -> None:
            super().run()
            install_playwright_chromium()

else:
    EditableWheelWithPlaywrightChromium = None  # type: ignore[assignment]


cmdclass: dict[str, Any] = {
    "install": InstallWithPlaywrightChromium,
}

if DevelopWithPlaywrightChromium is not None:
    cmdclass["develop"] = DevelopWithPlaywrightChromium

if EditableWheelWithPlaywrightChromium is not None:
    cmdclass["editable_wheel"] = EditableWheelWithPlaywrightChromium


setup(
    cmdclass=cmdclass,
)
