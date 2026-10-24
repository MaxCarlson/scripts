from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Optional


_LAYOUT_SCHEMA = 1


class LayoutError(ValueError):
    """Raised when a saved pane layout cannot be safely read or written."""


def default_layout_directory() -> Path:
    """Return the per-user configuration directory for saved pane layouts."""
    override = os.environ.get("CLI_TUI_LAYOUT_DIR")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "cli_tui" / "layouts"


def normalize_launch_root(launch_root: str | os.PathLike[str]) -> str:
    """Normalize a launch directory so layout identity is stable across invocations."""
    return os.path.normcase(str(Path(launch_root).expanduser().resolve()))


class PaneLayoutStore:
    """Read and atomically write pane layouts scoped to launch directory and app."""

    def __init__(self, directory: Optional[str | os.PathLike[str]] = None) -> None:
        self.directory = Path(directory) if directory is not None else default_layout_directory()

    def path_for(self, launch_root: str | os.PathLike[str], app_id: str) -> Path:
        identity = {"launch_root": normalize_launch_root(launch_root), "app_id": str(app_id)}
        digest = hashlib.sha256(
            json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        return self.directory / f"{digest}.json"

    def load(self, launch_root: str | os.PathLike[str], app_id: str) -> Optional[dict[str, Any]]:
        path = self.path_for(launch_root, app_id)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError) as exc:
            raise LayoutError(f"could not read pane layout from {path}: {exc}") from exc

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LayoutError(f"layout JSON is corrupt at {path}: {exc}") from exc
        if not isinstance(data, dict) or data.get("schema") != _LAYOUT_SCHEMA:
            raise LayoutError("layout document has an unsupported schema or format")
        if data.get("launch_root") != normalize_launch_root(launch_root):
            raise LayoutError("layout launch directory does not match")
        if data.get("app_id") != str(app_id) or not isinstance(data.get("layout"), dict):
            raise LayoutError("layout app identity or payload is invalid")
        return data["layout"]

    def save(
        self,
        launch_root: str | os.PathLike[str],
        app_id: str,
        layout: dict[str, Any],
    ) -> Path:
        if not isinstance(layout, dict):
            raise LayoutError("layout must be a dictionary")
        normalized_root = normalize_launch_root(launch_root)
        path = self.path_for(normalized_root, app_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": _LAYOUT_SCHEMA,
            "launch_root": normalized_root,
            "app_id": str(app_id),
            "layout": layout,
        }
        try:
            encoded = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise LayoutError(f"layout contains unsupported values: {exc}") from exc

        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, path)
        except OSError as exc:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise LayoutError(f"could not save pane layout to {path}: {exc}") from exc
        return path
