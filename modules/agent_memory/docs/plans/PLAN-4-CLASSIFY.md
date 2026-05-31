# agent_memory LLM Classification — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`
> (recommended) or `superpowers:executing-plans` to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire LLM-based placement classification into `create_note()`. When
`project=None` and the note kind is ambiguous (`decision`, `code_note`, `session`),
call `llm_local.complete()` to determine whether the note should be placed in
`global/` or a specific project. Fall back to interactive prompt (or default to
`global` with `--no-llm`) when the LLM is unreachable.

**Architecture:** New `agent_memory/classify.py` handles all placement logic:
static rules for unambiguous kinds + LLM call for ambiguous ones + interactive
fallback. `store.py` calls `classify.determine_project()` inside `create_note()`
when `auto_classify=True`. The classify module imports `llm_local` but degrades
gracefully when it returns `None`.

**Tech Stack:** Python 3.11+, `llm_local` (Plan 1), `agent_memory.note` kind
constants (Plan 2), `sys.stdin` for interactive fallback. `uv run pytest` for tests.

**Prerequisites:** Plans 1, 2, and 3 complete — `llm_local` installed, `NoteStore`
implemented, CLI working.

**Working directory:** `/home/mcarls/scripts/modules/agent_memory/`

---

## File Map

| File | Responsibility |
|---|---|
| `agent_memory/classify.py` | `determine_project()` — static rules + LLM + interactive fallback |
| `agent_memory/store.py` | Call `classify.determine_project()` inside `create_note()` when `auto_classify=True` |
| `agent_memory/cli.py` | Pass `auto_classify=not args.no_llm` (already done in Plan 3) |
| `tests/classify_test.py` | All classify tests — mocked LLM, all code paths |

---

## Task 1: `classify.py` — static placement rules

**Files:**
- Create: `agent_memory/classify.py`
- Create: `tests/classify_test.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/classify_test.py
from __future__ import annotations

import pytest
from unittest.mock import patch

from agent_memory.classify import determine_project, PlacementError


def test_constraint_always_global() -> None:
    result = determine_project(kind="constraint", project=None, title="my rule", auto_classify=False)
    assert result == "global"


def test_preference_always_global() -> None:
    result = determine_project(kind="preference", project=None, title="my pref", auto_classify=False)
    assert result == "global"


def test_explicit_project_always_returned() -> None:
    result = determine_project(kind="decision", project="my-project", title="some decision", auto_classify=False)
    assert result == "my-project"


def test_explicit_global_always_returned() -> None:
    result = determine_project(kind="decision", project="global", title="some decision", auto_classify=False)
    assert result == "global"


def test_project_required_kind_without_project_raises() -> None:
    with pytest.raises(PlacementError, match="requires a project"):
        determine_project(kind="handoff", project=None, title="handoff", auto_classify=False)


def test_project_required_kind_task_without_project_raises() -> None:
    with pytest.raises(PlacementError, match="requires a project"):
        determine_project(kind="task", project=None, title="my task", auto_classify=False)


def test_project_required_kind_bug_without_project_raises() -> None:
    with pytest.raises(PlacementError, match="requires a project"):
        determine_project(kind="bug", project=None, title="my bug", auto_classify=False)


def test_ambiguous_kind_without_auto_classify_defaults_global() -> None:
    result = determine_project(kind="decision", project=None, title="some decision", auto_classify=False)
    assert result == "global"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/mcarls/scripts/modules/agent_memory
uv run pytest tests/classify_test.py -v --tb=short
```

Expected: `ImportError: cannot import name 'determine_project' from 'agent_memory.classify'`

- [ ] **Step 3: Write `agent_memory/classify.py`**

```python
"""Placement classification for agent_memory notes.

Determines whether a note belongs in global/ or a project directory.
Static rules for unambiguous kinds; LLM call for ambiguous ones.
"""
from __future__ import annotations

import logging
import sys
from typing import Optional

from agent_memory.note import (
    GLOBAL_DEFAULT_KINDS,
    LLM_CLASSIFY_KINDS,
    PROJECT_REQUIRED_KINDS,
)

logger = logging.getLogger(__name__)


class PlacementError(ValueError):
    """Raised when project placement cannot be determined."""


def determine_project(
    *,
    kind: str,
    project: Optional[str],
    title: str,
    auto_classify: bool,
    interactive: bool = True,
    body: str = "",
) -> str:
    """Return the project slug (or 'global') for a note.

    Resolution order:
    1. Explicit project value → return as-is.
    2. kind in GLOBAL_DEFAULT_KINDS → return 'global'.
    3. kind in PROJECT_REQUIRED_KINDS → raise PlacementError.
    4. kind in LLM_CLASSIFY_KINDS:
       a. auto_classify=True  → call LLM, then interactive fallback.
       b. auto_classify=False → return 'global' (safe default).

    Never raises for constraint/preference (always global) or when
    project is explicitly given.
    """
    if project is not None:
        return project

    if kind in GLOBAL_DEFAULT_KINDS:
        return "global"

    if kind in PROJECT_REQUIRED_KINDS:
        raise PlacementError(
            f"Kind '{kind}' requires a project. Pass --project <slug>."
        )

    # LLM_CLASSIFY_KINDS — decision, code_note, session
    if not auto_classify:
        return "global"

    result = _classify_via_llm(kind=kind, title=title, body=body)
    if result is not None:
        logger.info("Classified as: %s (via local LLM). Use --project to override.", result)
        return result

    # LLM unreachable — try interactive fallback
    if interactive and sys.stdin.isatty():
        return _classify_interactively(kind=kind, title=title)

    logger.warning("LLM unreachable and no TTY — defaulting to 'global'. Use --project to override.")
    return "global"


def _classify_via_llm(*, kind: str, title: str, body: str) -> Optional[str]:
    try:
        from llm_local import complete
    except ImportError:
        logger.debug("llm_local not installed — skipping LLM classification")
        return None

    prompt = (
        f"A memory note is being saved. Determine whether it belongs in the 'global' "
        f"scope (cross-project, always applicable) or a specific project (only relevant "
        f"to one project).\n\n"
        f"Kind: {kind}\n"
        f"Title: {title}\n"
        f"Body excerpt: {body[:300]}\n\n"
        f"Respond with only one of:\n"
        f"- 'global' if this note applies across all projects\n"
        f"- '<project-slug>' if this note is specific to one project\n\n"
        f"Response:"
    )

    raw = complete(prompt, timeout=5.0)
    if raw is None:
        return None

    cleaned = raw.strip().lower().strip("'\"")
    if not cleaned or len(cleaned) > 80:
        logger.debug("LLM returned unusable placement: %r", raw)
        return None

    return cleaned


def _classify_interactively(*, kind: str, title: str) -> str:
    print(f"\nCannot auto-classify '{kind}' note: '{title}'")
    print("Where should this note live?")
    print("  [g] global  (cross-project, always applicable)")
    print("  [p] project (enter project slug)")

    while True:
        choice = input("Choice [g/p]: ").strip().lower()
        if choice in ("g", "global"):
            return "global"
        if choice in ("p", "project"):
            slug = input("Project slug: ").strip()
            if slug:
                return slug
            print("Project slug cannot be empty.")
        else:
            print("Please enter 'g' or 'p'.")
```

- [ ] **Step 4: Run tests**

```bash
cd /home/mcarls/scripts/modules/agent_memory
uv run pytest tests/classify_test.py -v --tb=short
```

Expected: All 8 static rule tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/mcarls/scripts/modules/agent_memory
git add agent_memory/classify.py tests/classify_test.py
git commit -m "feat(classify): static placement rules — constraint/preference global, project-required raises"
```

---

## Task 2: LLM integration path

**Files:**
- Modify: `tests/classify_test.py` (append tests)
- No code changes needed — LLM path already in `classify.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/classify_test.py`:

```python
def test_auto_classify_calls_llm_for_ambiguous_kind() -> None:
    with patch("agent_memory.classify.complete", return_value="my-project") as mock_llm:
        result = determine_project(
            kind="decision", project=None, title="Use SQLite", auto_classify=True, interactive=False
        )
    assert result == "my-project"
    mock_llm.assert_called_once()


def test_auto_classify_returns_global_when_llm_says_global() -> None:
    with patch("agent_memory.classify.complete", return_value="global"):
        result = determine_project(
            kind="code_note", project=None, title="How routing works", auto_classify=True, interactive=False
        )
    assert result == "global"


def test_auto_classify_strips_quotes_from_llm_response() -> None:
    with patch("agent_memory.classify.complete", return_value="'my-project'"):
        result = determine_project(
            kind="session", project=None, title="Session summary", auto_classify=True, interactive=False
        )
    assert result == "my-project"


def test_auto_classify_returns_global_when_llm_unreachable_no_tty() -> None:
    with patch("agent_memory.classify.complete", return_value=None):
        result = determine_project(
            kind="decision", project=None, title="Some decision",
            auto_classify=True, interactive=False
        )
    assert result == "global"


def test_auto_classify_returns_global_on_unusable_llm_response() -> None:
    with patch("agent_memory.classify.complete", return_value="   "):
        result = determine_project(
            kind="decision", project=None, title="Some decision",
            auto_classify=True, interactive=False
        )
    assert result == "global"


def test_auto_classify_returns_global_on_oversized_llm_response() -> None:
    long_response = "x" * 100
    with patch("agent_memory.classify.complete", return_value=long_response):
        result = determine_project(
            kind="decision", project=None, title="Some decision",
            auto_classify=True, interactive=False
        )
    assert result == "global"
```

- [ ] **Step 2: Fix `_classify_via_llm` to patch correctly**

The tests patch `agent_memory.classify.complete`, but the current code does
`from llm_local import complete` inside the function. The patch target must be
`agent_memory.classify.complete` — but the current import is local. Fix this by
importing at module level with a fallback:

Replace the `_classify_via_llm` function in `classify.py`:

```python
# At module level, after imports, before PlacementError:
try:
    from llm_local import complete as _llm_complete
except ImportError:
    _llm_complete = None  # type: ignore[assignment]
```

And update `_classify_via_llm`:

```python
def _classify_via_llm(*, kind: str, title: str, body: str) -> Optional[str]:
    if _llm_complete is None:
        logger.debug("llm_local not installed — skipping LLM classification")
        return None

    prompt = (
        f"A memory note is being saved. Determine whether it belongs in the 'global' "
        f"scope (cross-project, always applicable) or a specific project (only relevant "
        f"to one project).\n\n"
        f"Kind: {kind}\n"
        f"Title: {title}\n"
        f"Body excerpt: {body[:300]}\n\n"
        f"Respond with only one of:\n"
        f"- 'global' if this note applies across all projects\n"
        f"- '<project-slug>' if this note is specific to one project\n\n"
        f"Response:"
    )

    raw = _llm_complete(prompt, timeout=5.0)
    if raw is None:
        return None

    cleaned = raw.strip().lower().strip("'\"")
    if not cleaned or len(cleaned) > 80:
        logger.debug("LLM returned unusable placement: %r", raw)
        return None

    return cleaned
```

The test patches `agent_memory.classify._llm_complete`. Update test patches:

```python
# In classify_test.py, the correct patch target is:
with patch("agent_memory.classify._llm_complete", return_value="my-project") as mock_llm:
```

Update all 6 test patches in `tests/classify_test.py` to use
`agent_memory.classify._llm_complete` instead of `agent_memory.classify.complete`.

Full corrected tests:

```python
def test_auto_classify_calls_llm_for_ambiguous_kind() -> None:
    with patch("agent_memory.classify._llm_complete", return_value="my-project") as mock_llm:
        result = determine_project(
            kind="decision", project=None, title="Use SQLite", auto_classify=True, interactive=False
        )
    assert result == "my-project"
    mock_llm.assert_called_once()


def test_auto_classify_returns_global_when_llm_says_global() -> None:
    with patch("agent_memory.classify._llm_complete", return_value="global"):
        result = determine_project(
            kind="code_note", project=None, title="How routing works", auto_classify=True, interactive=False
        )
    assert result == "global"


def test_auto_classify_strips_quotes_from_llm_response() -> None:
    with patch("agent_memory.classify._llm_complete", return_value="'my-project'"):
        result = determine_project(
            kind="session", project=None, title="Session summary", auto_classify=True, interactive=False
        )
    assert result == "my-project"


def test_auto_classify_returns_global_when_llm_unreachable_no_tty() -> None:
    with patch("agent_memory.classify._llm_complete", return_value=None):
        result = determine_project(
            kind="decision", project=None, title="Some decision",
            auto_classify=True, interactive=False
        )
    assert result == "global"


def test_auto_classify_returns_global_on_unusable_llm_response() -> None:
    with patch("agent_memory.classify._llm_complete", return_value="   "):
        result = determine_project(
            kind="decision", project=None, title="Some decision",
            auto_classify=True, interactive=False
        )
    assert result == "global"


def test_auto_classify_returns_global_on_oversized_llm_response() -> None:
    long_response = "x" * 100
    with patch("agent_memory.classify._llm_complete", return_value=long_response):
        result = determine_project(
            kind="decision", project=None, title="Some decision",
            auto_classify=True, interactive=False
        )
    assert result == "global"
```

- [ ] **Step 3: Run tests**

```bash
cd /home/mcarls/scripts/modules/agent_memory
uv run pytest tests/classify_test.py -v --tb=short
```

Expected: All 14 tests pass (8 static + 6 LLM).

- [ ] **Step 4: Commit**

```bash
cd /home/mcarls/scripts/modules/agent_memory
git add agent_memory/classify.py tests/classify_test.py
git commit -m "feat(classify): LLM integration — _llm_complete, response parsing, fallback to global"
```

---

## Task 3: Interactive fallback

**Files:**
- Modify: `tests/classify_test.py` (append tests)
- No code changes needed — interactive path already in `classify.py`

- [ ] **Step 1: Add tests for interactive fallback**

Append to `tests/classify_test.py`:

```python
def test_interactive_fallback_global_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = iter(["g"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    with patch("agent_memory.classify._llm_complete", return_value=None), \
         patch("sys.stdin.isatty", return_value=True):
        result = determine_project(
            kind="decision", project=None, title="Some decision",
            auto_classify=True, interactive=True
        )
    assert result == "global"


def test_interactive_fallback_project_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = iter(["p", "my-project"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    with patch("agent_memory.classify._llm_complete", return_value=None), \
         patch("sys.stdin.isatty", return_value=True):
        result = determine_project(
            kind="session", project=None, title="Session end",
            auto_classify=True, interactive=True
        )
    assert result == "my-project"


def test_interactive_fallback_retries_on_invalid_input(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = iter(["x", "bad", "g"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    with patch("agent_memory.classify._llm_complete", return_value=None), \
         patch("sys.stdin.isatty", return_value=True):
        result = determine_project(
            kind="code_note", project=None, title="Some code note",
            auto_classify=True, interactive=True
        )
    assert result == "global"


def test_no_interactive_no_llm_defaults_global() -> None:
    with patch("agent_memory.classify._llm_complete", return_value=None):
        result = determine_project(
            kind="decision", project=None, title="Something",
            auto_classify=True, interactive=False
        )
    assert result == "global"
```

- [ ] **Step 2: Run tests**

```bash
cd /home/mcarls/scripts/modules/agent_memory
uv run pytest tests/classify_test.py -v --tb=short
```

Expected: All 18 tests pass (14 prior + 4 interactive).

- [ ] **Step 3: Commit**

```bash
cd /home/mcarls/scripts/modules/agent_memory
git add tests/classify_test.py
git commit -m "test(classify): interactive fallback tests — 18 classify tests passing"
```

---

## Task 4: Wire `classify` into `NoteStore.create_note()`

**Files:**
- Modify: `agent_memory/store.py`
- Modify: `tests/store_test.py` (append tests)

The stub `classify.py` used in Plan 2's Task 5 Step 3 must be replaced with the
real `classify.determine_project()` call.

- [ ] **Step 1: Add failing tests**

Append to `tests/store_test.py`:

```python
def test_create_note_auto_classify_calls_determine_project(tmp_path: Path) -> None:
    store = NoteStore(root=tmp_path)
    with patch("agent_memory.store.determine_project", return_value="global") as mock_classify:
        note = store.create_note(
            kind="decision",
            project=None,
            title="Auto classify me",
            body="## Summary\n\nDetails.",
            created_by="test",
            auto_classify=True,
        )
    mock_classify.assert_called_once()
    assert note.project == "global"


def test_create_note_no_auto_classify_skips_llm(tmp_path: Path) -> None:
    store = NoteStore(root=tmp_path)
    with patch("agent_memory.store.determine_project") as mock_classify:
        # Without auto_classify, determine_project is called with auto_classify=False
        mock_classify.return_value = "global"
        note = store.create_note(
            kind="decision",
            project=None,
            title="No classify",
            body="## Summary\n\nContent.",
            created_by="test",
            auto_classify=False,
        )
    # It's called (for placement resolution), but auto_classify=False is passed
    call_kwargs = mock_classify.call_args.kwargs
    assert call_kwargs.get("auto_classify") is False


def test_create_note_project_required_kind_raises_placement_error(tmp_path: Path) -> None:
    from agent_memory.classify import PlacementError
    store = NoteStore(root=tmp_path)
    with pytest.raises(PlacementError):
        store.create_note(
            kind="handoff",
            project=None,
            title="Missing project",
            body="",
            created_by="test",
        )
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd /home/mcarls/scripts/modules/agent_memory
uv run pytest tests/store_test.py::test_create_note_auto_classify_calls_determine_project -v --tb=short
```

Expected: FAIL — `determine_project` not imported in `store.py` yet.

- [ ] **Step 3: Update `store.py` to use `classify.determine_project()`**

In `agent_memory/store.py`, replace the classify stub with the real call.
Find the section in `create_note()` where project is resolved. Replace it:

```python
# At the top of store.py, add this import:
from agent_memory.classify import determine_project

# Inside create_note(), replace any existing project-resolution logic with:
resolved_project = determine_project(
    kind=kind,
    project=project,
    title=title,
    auto_classify=auto_classify,
    interactive=True,
    body=body,
)
```

The full updated `create_note()` signature and body (replace the existing stub):

```python
def create_note(
    self,
    *,
    kind: str,
    project: Optional[str],
    title: str,
    body: str,
    created_by: str,
    tags: Optional[list[str]] = None,
    auto_classify: bool = False,
    dry_run: bool = False,
) -> Note:
    """Create and persist a new Note.

    Resolves project via classify.determine_project(), writes the Markdown
    file atomically, upserts the SQLite index, and returns the Note.
    Raises PlacementError if project cannot be resolved.
    If dry_run=True, builds and returns the Note without writing to disk.
    """
    if kind not in VALID_KINDS:
        raise ValueError(f"Invalid kind: {kind!r}. Valid: {sorted(VALID_KINDS)}")

    resolved_project = determine_project(
        kind=kind,
        project=project,
        title=title,
        auto_classify=auto_classify,
        interactive=True,
        body=body,
    )

    note_id = make_note_id()
    filename = make_filename(note_id, title)
    note_tags = tags or []

    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    meta: dict = {
        "id": note_id,
        "schema_version": 1,
        "kind": kind,
        "project": resolved_project,
        "created_at": now,
        "created_by": created_by,
        "tags": note_tags,
    }
    full_body = write_frontmatter(meta, body)

    if resolved_project == "global":
        note_dir = self._root / "global" / kind
    else:
        note_dir = self._root / "projects" / resolved_project / kind

    note_path = note_dir / filename

    note = Note(
        id=note_id,
        path=note_path,
        kind=kind,
        project=resolved_project,
        title=title,
        body=body,
        created_at=now,
        created_by=created_by,
        tags=note_tags,
        schema_version=1,
    )

    if dry_run:
        return note

    note_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = note_path.with_suffix(".tmp")
    tmp_path.write_text(full_body, encoding="utf-8")
    tmp_path.rename(note_path)

    import hashlib
    content_hash = hashlib.sha256(full_body.encode("utf-8")).hexdigest()
    self._index.upsert(
        note_id=note_id,
        path=str(note_path),
        project=resolved_project,
        kind=kind,
        title=title,
        body=body[:2000],
        created_at=now,
        created_by=created_by,
        tags=note_tags,
        full_content=full_body,
    )

    return note
```

- [ ] **Step 4: Run all store tests**

```bash
cd /home/mcarls/scripts/modules/agent_memory
uv run pytest tests/store_test.py -v --tb=short
```

Expected: All store tests pass (Plan 2 tests + 3 new classify-wired tests).

- [ ] **Step 5: Run the full test suite**

```bash
cd /home/mcarls/scripts/modules/agent_memory
uv run pytest tests/ -v --tb=short
```

Expected: All tests pass across all modules.

- [ ] **Step 6: Update PROJECT_STATUS.md**

In `/home/mcarls/scripts/modules/agent_memory/docs/PROJECT_STATUS.md`,
change `Phase 4 — LLM classification ⏳ NOT STARTED` to `✅ COMPLETE`.

- [ ] **Step 7: Commit**

```bash
cd /home/mcarls/scripts/modules/agent_memory
git add agent_memory/store.py agent_memory/classify.py tests/store_test.py \
    tests/classify_test.py docs/PROJECT_STATUS.md
git commit -m "feat(classify): wire determine_project into NoteStore.create_note() — Phase 4 complete"
```

---

## Phase 4 Definition of Done

- [ ] `store.create_note(kind="constraint", ...)` → places in `global/constraint/` without LLM call
- [ ] `store.create_note(kind="handoff", project=None)` → raises `PlacementError`
- [ ] `store.create_note(kind="decision", project=None, auto_classify=True)` → calls LLM
- [ ] LLM unreachable (returns `None`) → falls back to interactive if TTY, else `global`
- [ ] `--no-llm` flag → `auto_classify=False` → skips LLM, defaults to `global` for ambiguous kinds
- [ ] `--project my-proj` → overrides classification entirely
- [ ] All 18 classify tests passing
- [ ] Full test suite passing (all Plans combined)
