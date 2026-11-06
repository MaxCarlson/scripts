"""Build identity captured once when a coordinator process starts."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, Optional


def build_runtime_identity(package_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Return a deterministic source fingerprint for the loaded deployment.

    Callers should capture this at process startup. Status endpoints must return
    the captured value rather than hashing the mutable checkout on each request.
    """
    import resource_coordinator

    root = (package_dir or Path(resource_coordinator.__file__).resolve().parent).resolve()
    digest = hashlib.sha256()
    files = sorted(root.rglob("*.py"))
    for source in files:
        if "__pycache__" in source.parts:
            continue
        relative = source.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        content = source.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return {
        "version": resource_coordinator.__version__,
        "source_path": str(root / "__init__.py"),
        "revision": digest.hexdigest(),
    }
