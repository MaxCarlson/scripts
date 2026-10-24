from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Dict, Optional


SCHEMA_VERSION = 1


class LayoutError(ValueError):
    """Raised when a saved pane layout cannot be safely read or written."""


def normalize_launch_dir(path: str | os.PathLike[str]) -> str:
    """Return a stable absolute path for layout identity."""
    resolved = str(Path(path).expanduser().resolve(strict=False))
    return os.path.normcase(resolved)


def default_layout_config_dir() -> Path:
    """Return the platform-appropriate per-user cli_tui config directory."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "cli_tui" / "layouts"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "cli_tui" / "layouts"
    return Path.home() / ".config" / "cli_tui" / "layouts"


class PaneLayoutStore:
    """Versioned, identity-scoped JSON storage for a single app and launch directory."""

    def __init__(
        self,
        config_dir: Optional[str | os.PathLike[str]] = None,
        *,
        launch_dir: Optional[str | os.PathLike[str]] = None,
        app_id: str,
    ) -> None:
        clean_app_id = str(app_id).strip()
        if not clean_app_id:
            raise ValueError("app_id must not be empty")
        self.config_dir = (
            Path(config_dir) if config_dir is not None else default_layout_config_dir()
        )
        self.identity = {
            "launch_dir": normalize_launch_dir(launch_dir or os.getcwd()),
            "app_id": clean_app_id,
        }
        identity_bytes = json.dumps(
            self.identity, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        self.path = (
            self.config_dir / f"{hashlib.sha256(identity_bytes).hexdigest()}.json"
        )

    def save(self, payload: Dict[str, Any]) -> None:
        """Atomically save a JSON-compatible layout payload."""
        if not isinstance(payload, dict):
            raise LayoutError("layout payload must be an object")
        document = {
            "schema_version": SCHEMA_VERSION,
            "identity": self.identity,
            "layout": payload,
        }
        try:
            encoded = json.dumps(
                document, ensure_ascii=False, indent=2, allow_nan=False
            )
        except (TypeError, ValueError) as exc:
            raise LayoutError(f"layout contains unsupported values: {exc}") from exc

        temp_path: Optional[Path] = None
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=self.config_dir,
                prefix=f".{self.path.stem}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                temp_file.write(encoded)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_path, self.path)
        except OSError as exc:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise LayoutError(
                f"could not save pane layout to {self.path}: {exc}"
            ) from exc

    def load(self) -> Optional[Dict[str, Any]]:
        """Read and validate the saved layout, returning None when no layout exists."""
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise LayoutError(
                f"could not read pane layout from {self.path}: {exc}"
            ) from exc

        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LayoutError(f"layout JSON is corrupt at {self.path}: {exc}") from exc
        if not isinstance(document, dict):
            raise LayoutError("layout document must be a JSON object")
        if document.get("schema_version") != SCHEMA_VERSION:
            raise LayoutError(
                f"unsupported layout schema version: {document.get('schema_version')!r}"
            )
        if document.get("identity") != self.identity:
            raise LayoutError(
                "layout identity does not match this app and launch directory"
            )
        layout = document.get("layout")
        if not isinstance(layout, dict):
            raise LayoutError("layout payload must be a JSON object")
        return layout
