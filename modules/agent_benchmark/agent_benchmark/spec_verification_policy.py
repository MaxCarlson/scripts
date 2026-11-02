"""Frozen, literal specification-verification prompt additions."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .instruction_overlay import load_instruction_append

MAX_POLICY_BYTES = 16384
BASELINE_ID = "sv0-unmodified-v1"
INTERVENTION_ID = "sv1-specification-verification-v1"


def load_policy(path: Path) -> tuple[bytes, bytes, dict[str, str | int]]:
    """Validate a UTF-8 policy and construct a deterministic literal template."""
    addition = load_instruction_append(path)
    raw = addition.text.encode("utf-8")
    if len(raw) > MAX_POLICY_BYTES:
        raise ValueError("prompt policy exceeds 16384 bytes")
    if any(delimiter in addition.text for delimiter in ("{{", "}}", "{%", "%}", "{#", "#}")):
        raise ValueError("prompt policy must not contain Jinja delimiters")
    # Jinja drops a final template newline by default; a final empty expression
    # keeps the source policy's trailing newline in the rendered instruction.
    template = b"{{ instruction }}\n\n" + raw + b"{{ '' }}"
    return raw, template, {
        "id": INTERVENTION_ID,
        "sha256": addition.sha256,
        "byte_length": len(raw),
        "template_sha256": hashlib.sha256(template).hexdigest(),
    }


def verify_frozen_policy(run_dir: Path, metadata: dict) -> Path | None:
    """Verify persisted bytes and return the template for dispatch."""
    if metadata.get("id") == BASELINE_ID:
        if (run_dir / "policy").exists():
            raise ValueError("baseline run unexpectedly contains policy artifacts")
        return None
    if metadata.get("id") != INTERVENTION_ID:
        raise ValueError("unknown prompt policy identity")
    source = run_dir / "policy" / "source.md"
    template_path = run_dir / "policy" / "prompt-template.j2"
    raw, expected, identity = load_policy(source)
    del raw
    if identity != metadata or template_path.read_bytes() != expected:
        raise ValueError("frozen prompt policy or template changed")
    return template_path.resolve(strict=True)
