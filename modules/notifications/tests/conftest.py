"""Pytest configuration and fixtures for notifications tests."""

import sys
from pathlib import Path

# Ensure modules/notifications is on sys.path
package_root = Path(__file__).resolve().parent.parent
if str(package_root) not in sys.path:
    sys.path.insert(0, str(package_root))


def pytest_configure(config):
    """Ensure basetemp is inside this module's .pytest_tmp_root directory."""
    if not config.option.basetemp:
        basetemp = package_root / ".pytest_tmp_root"
        basetemp.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(basetemp)
