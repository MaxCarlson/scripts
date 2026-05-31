from __future__ import annotations

import re

from agent_memory.naming import make_note_id, slugify, make_filename

_ID_RE = re.compile(r"^\d{8}T\d{6}Z_[0-9a-f]{8}$")


def test_make_note_id_format() -> None:
    note_id = make_note_id()
    assert _ID_RE.match(note_id), f"Bad ID format: {note_id}"


def test_make_note_id_unique() -> None:
    ids = {make_note_id() for _ in range(100)}
    assert len(ids) == 100


def test_slugify_basic() -> None:
    assert slugify("Use SQLite for index") == "use-sqlite-for-index"


def test_slugify_special_chars() -> None:
    assert slugify("hello! world? (yes)") == "hello-world-yes"


def test_slugify_truncates_at_60() -> None:
    long_title = "a" * 100
    result = slugify(long_title)
    assert len(result) <= 60


def test_slugify_strips_trailing_dashes() -> None:
    result = slugify("hello---")
    assert not result.endswith("-")


def test_make_filename_format() -> None:
    note_id = "20260531T055512Z_a3f9e1b2"
    filename = make_filename(note_id, "Use SQLite for index")
    assert filename == "20260531T055512Z_a3f9e1b2_use-sqlite-for-index.md"


def test_make_filename_ends_with_md() -> None:
    filename = make_filename("20260531T000000Z_aabbccdd", "Some Title")
    assert filename.endswith(".md")
