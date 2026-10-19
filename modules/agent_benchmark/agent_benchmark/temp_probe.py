"""Trusted public diagnostic probe, copied unchanged to the trial workspace."""

import hashlib
import json
import os
from pathlib import Path
import tempfile


def main() -> None:
    scratch = Path(__file__).resolve().parent / ".agent-bench-scratch"
    if not scratch.is_dir() or scratch.is_symlink() or scratch.is_junction():
        raise RuntimeError("Ordinary trial scratch is required")
    environment = {name: os.environ.get(name) for name in ("TEMP", "TMP", "TMPDIR")}
    if any(not value or Path(value).resolve() != scratch for value in environment.values()):
        raise RuntimeError("Apply command-local TEMP/TMP/TMPDIR before starting this probe")
    tempdir = Path(tempfile.gettempdir()).resolve()
    if tempdir != scratch:
        raise RuntimeError("Runtime selected temporary storage outside trial scratch")
    fd, name = tempfile.mkstemp(prefix="smoke-", suffix=".txt")
    marker = Path(name)
    with os.fdopen(fd, "wb") as target:
        target.write(b"agent-benchmark integration temp marker\n")
    value = {
        "environment": environment,
        "tempdir": str(tempdir),
        "marker_name": marker.name,
        "marker_sha256": hashlib.sha256(marker.read_bytes()).hexdigest(),
    }
    payload = json.dumps(value, sort_keys=True)
    (scratch / "temp-probe.json").write_text(payload, encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
