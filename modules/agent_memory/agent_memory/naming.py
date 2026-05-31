from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone


def make_note_id() -> str:
    """Generate a collision-safe note ID: UTC timestamp + 8 random hex chars.

    Example: 20260531T055512Z_a3f9e1b2
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}_{secrets.token_hex(4)}"


def slugify(text: str, max_len: int = 60) -> str:
    """Convert text to a URL-safe, lowercase slug."""
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:max_len].rstrip("-")


def make_filename(note_id: str, title: str) -> str:
    """Return the .md filename for a note: <id>_<slug>.md"""
    slug = slugify(title)
    return f"{note_id}_{slug}.md"
