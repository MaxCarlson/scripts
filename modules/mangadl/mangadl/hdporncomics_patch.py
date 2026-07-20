"""Repeatable compatibility patch for HDPornComics Windows paths.

The external ``hdporncomics`` executable imports this installed module, so a
durable patch is required rather than an in-process monkey patch.  This keeps
the workaround explicit and safe to reapply after an upstream package update.
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import re
from dataclasses import dataclass
from pathlib import Path

INVALID_WINDOWS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
PATCH_MARKER = "# mangadl Windows path compatibility patch"
OLD_ESCAPE_PATH = """def escape_path(path: str) -> str:
    return path.replace("/", "|")
"""
NEW_ESCAPE_PATH = """def escape_path(path: str) -> str:
    # mangadl Windows path compatibility patch
    import hashlib
    import re

    invalid_windows_chars = re.compile(r'[<>:"/\\\\|?*\\x00-\\x1f]')
    sanitized = invalid_windows_chars.sub("_", path).rstrip(" .") or "_"
    reserved_names = {"CON", "PRN", "AUX", "NUL", *(f"COM{number}" for number in range(1, 10)), *(f"LPT{number}" for number in range(1, 10))}
    if sanitized.split(".", 1)[0].upper() in reserved_names:
        sanitized = f"_{sanitized}"
    if len(sanitized) > 180:
        digest = hashlib.sha256(sanitized.encode("utf-8", errors="surrogatepass")).hexdigest()[:12]
        sanitized = f"{sanitized[:167]}_{digest}".rstrip(" .")
    return sanitized
"""


@dataclass(frozen=True, slots=True)
class PatchStatus:
    state: str
    path: Path | None
    message: str


def sanitize_windows_name(value: str, max_length: int = 180) -> str:
    """Return a Windows-safe filename with a stable collision-resistant suffix."""
    sanitized = INVALID_WINDOWS_CHARS.sub("_", value).rstrip(" .") or "_"
    if sanitized.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES:
        sanitized = f"_{sanitized}"
    if len(sanitized) > max_length:
        digest = hashlib.sha256(sanitized.encode("utf-8", errors="surrogatepass")).hexdigest()[:12]
        sanitized = f"{sanitized[:max_length - len(digest) - 1]}_{digest}".rstrip(" .")
    return sanitized


def _cli_path() -> Path:
    try:
        module = importlib.import_module("hdporncomics.cli")
    except ImportError as exc:
        raise RuntimeError("hdporncomics is not installed; run: python -m pip install --upgrade hdporncomics") from exc
    source_file = inspect.getsourcefile(module)
    if source_file is None:
        raise RuntimeError("could not locate the installed hdporncomics.cli module")
    return Path(source_file).resolve()


def patch_status() -> PatchStatus:
    try:
        path = _cli_path()
        source = path.read_text(encoding="utf-8")
    except (OSError, RuntimeError) as exc:
        return PatchStatus("unavailable", None, str(exc))
    if PATCH_MARKER in source:
        return PatchStatus("patched", path, "mangadl compatibility patch is applied")
    if OLD_ESCAPE_PATH in source:
        return PatchStatus("unpatched", path, "installed package needs the mangadl Windows path compatibility patch")
    return PatchStatus("changed", path, "hdporncomics.cli changed; review and update the mangadl patch before applying")


def apply_patch() -> PatchStatus:
    """Apply the known-safe source replacement and save the original once."""
    status = patch_status()
    if status.state == "patched":
        return status
    if status.state != "unpatched" or status.path is None:
        raise RuntimeError(status.message)
    source = status.path.read_text(encoding="utf-8")
    backup = status.path.with_suffix(status.path.suffix + ".bak")
    if not backup.exists():
        backup.write_text(source, encoding="utf-8")
    status.path.write_text(source.replace(OLD_ESCAPE_PATH, NEW_ESCAPE_PATH, 1), encoding="utf-8")
    return PatchStatus("patched", status.path, f"patched {status.path}; backup: {backup}")


def patch_recovery_hint(output: str) -> str | None:
    """Identify the historical Windows path error in backend output."""
    lowered = output.lower()
    signatures = ("winerror 123", "filename, directory name, or volume label syntax", "invalid filename")
    if any(signature in lowered for signature in signatures):
        return "hdporncomics reported a Windows filename error; run: mangadl patch-hdporncomics -f"
    return None
