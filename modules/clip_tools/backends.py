# File: pyprjs/clip_tools/backends.py
# Unifies access to clipboard, history, tmux, and system utils.
# Prefers the upcoming `modules/system_tools` package; falls back to the existing
# `cross_platform.*` modules so this works immediately in your environment.

from __future__ import annotations

from typing import Optional


# --- Clipboard ---

def get_clipboard() -> str:
    impl = _clipboard_impl()
    return impl["get"]()


def set_clipboard(text: str) -> None:
    impl = _clipboard_impl()
    impl["set"](text)


def _clipboard_impl():
    # Try new system_tools first
    try:
        from modules.system_tools.clipboard import get_clipboard as get_cb, set_clipboard as set_cb  # type: ignore
        return {"get": get_cb, "set": set_cb}
    except Exception:
        pass
    # Fall back to cross_platform
    try:
        from cross_platform.clipboard_utils import get_clipboard as get_cb, set_clipboard as set_cb  # type: ignore
        return {"get": get_cb, "set": set_cb}
    except Exception as e:
        raise ImportError(
            "No clipboard backend found. Install modules/system_tools or cross_platform."
        ) from e


# --- System / Tmux ---

class SystemUtilsAdapter:
    def __init__(self):
        self._impl = self._load_impl()

    def is_tmux(self) -> bool:
        return self._impl.is_tmux()

    @staticmethod
    def _load_impl():
        try:
            from modules.system_tools.system import SystemUtils as Impl  # type: ignore
            return Impl()
        except Exception:
            pass
        try:
            from cross_platform.system_utils import SystemUtils as Impl  # type: ignore
            return Impl()
        except Exception as e:
            raise ImportError(
                "No SystemUtils backend found. Install modules/system_tools or cross_platform."
            ) from e


class TmuxManagerAdapter:
    def __init__(self):
        self._impl = self._load_impl()

    def capture_pane(self, start_line: str = "-10000") -> Optional[str]:
        return self._impl.capture_pane(start_line=start_line)

    @staticmethod
    def _load_impl():
        try:
            from modules.system_tools.tmux import TmuxManager as Impl  # type: ignore
            return Impl()
        except Exception:
            pass
        try:
            from cross_platform.tmux_utils import TmuxManager as Impl  # type: ignore
            return Impl()
        except Exception as e:
            raise ImportError(
                "No TmuxManager backend found. Install modules/system_tools or cross_platform."
            ) from e


# --- History ---

class HistoryUtilsAdapter:
    def __init__(self):
        self._impl = self._load_impl()

    @property
    def shell_type(self) -> str:
        return getattr(self._impl, "shell_type", "unknown")

    def get_nth_recent_command(self, n: int) -> Optional[str]:
        return self._impl.get_nth_recent_command(n)

    @staticmethod
    def _load_impl():
        try:
            from modules.system_tools.history import HistoryUtils as Impl  # type: ignore
            return Impl()
        except Exception:
            pass
        try:
            from cross_platform.history_utils import HistoryUtils as Impl  # type: ignore
            return Impl()
        except Exception as e:
            raise ImportError(
                "No HistoryUtils backend found. Install modules/system_tools or cross_platform."
            ) from e
