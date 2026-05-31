from __future__ import annotations

import hashlib
from pathlib import Path


def parse_checksum_spec(spec: str) -> tuple[str, str]:
    if ":" not in spec:
        return "sha256", spec.strip().lower()
    algo, digest = spec.split(":", 1)
    return algo.strip().lower(), digest.strip().lower()


def hash_file(path: Path, algorithm: str = "sha256", chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.new(algorithm)
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def verify_checksum(path: Path, spec: str) -> bool:
    algorithm, expected = parse_checksum_spec(spec)
    return hash_file(path, algorithm).lower() == expected.lower()
