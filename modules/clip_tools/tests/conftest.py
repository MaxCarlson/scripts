# File: pyprjs/clip_tools/tests/conftest.py
import os
import sys
from types import SimpleNamespace
import pytest

# Ensure 'clip_tools' (located under pyprjs/clip_tools) is importable
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PKG_PARENT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
# Insert 'pyprjs' on sys.path so 'clip_tools' can be imported
sys.path.insert(0, os.path.abspath(os.path.join(PROJECT_ROOT, "")))
sys.path.insert(0, os.path.abspath(os.path.join(PKG_PARENT, "")))
sys.path.insert(0, os.path.abspath(os.path.join(PROJECT_ROOT, "..")))

@pytest.fixture
def ns():
    """Shortcut to build argparse-like objects."""
    return lambda **kwargs: SimpleNamespace(**kwargs)

class FakeSysAPI:
    """
    Fake system adapter used by tests.
    Provides: get_clipboard, set_clipboard, is_tmux, tmux_capture_pane
    """
    def __init__(self):
        self._clip = ""
        self._tmux = True
        self._pane = ""
        self.verify_mismatch = False  # when True, get_clipboard will return different content *after* a set
        self._last_set = None

    # Clipboard
    def get_clipboard(self) -> str:
        if self.verify_mismatch and self._last_set is not None:
            # Return content that is different from what was last set to simulate mismatch
            return self._last_set + "_DIFF"
        return self._clip

    def set_clipboard(self, text: str) -> None:
        self._clip = text
        self._last_set = text

    # Tmux
    def is_tmux(self) -> bool:
        return self._tmux

    def tmux_capture_pane(self, start_line: str = "-10000") -> str:
        return self._pane

@pytest.fixture
def fake_sysapi():
    return FakeSysAPI()

@pytest.fixture(autouse=True)
def _set_default_env(tmp_path, monkeypatch):
    """
    Provide a clean HOME and default SHLVL for tests that touch copy-log.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SHLVL", "3")
    return home
