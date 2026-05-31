# agent_memory — LLM Handoff Document

**Date:** 2026-05-31  
**Project:** `/home/mcarls/scripts/modules/agent_memory/`  
**Status:** PLAN-2 complete, PLAN-3 Tasks 1-3 complete, Tasks 4-6 remaining

---

## What Has Been Built

### Completed Modules

| Module | File | Status |
|--------|------|--------|
| Note dataclass + kind constants | `agent_memory/note.py` | ✅ Complete |
| Frontmatter parse/write/validate | `agent_memory/frontmatter.py` | ✅ Complete |
| Note ID generation + naming | `agent_memory/naming.py` | ✅ Complete |
| SQLite FTS5 index | `agent_memory/index.py` | ✅ Complete |
| NoteStore (core API) | `agent_memory/store.py` | ✅ Complete |
| Classify stub | `agent_memory/classify.py` | ✅ Stub (PLAN-4 wires LLM) |
| CLI scaffold + create + list | `agent_memory/cli.py` | ✅ Tasks 1-3 done |

**Test count:** 42 tests passing (store, note, frontmatter, naming, index) + 16 CLI tests = **58 total**

---

## What Needs to Be Done Next

### PLAN-3: CLI — Tasks 4, 5, 6 (in order)

**Working directory:** `/home/mcarls/scripts/modules/agent_memory/`  
**Run tests:** `uv run pytest tests/ -v --tb=short`

#### Task 4: `note show` and `note edit` commands

Add 3 tests to `tests/cli_test.py`:

```python
def _get_note_id(create_result: subprocess.CompletedProcess[str]) -> str:
    """Extract note ID from 'Created: <id>  (<path>)' output."""
    line = create_result.stdout.strip()
    return line.split("Created:")[1].strip().split()[0]


def test_note_show_displays_full_content(tmp_path: Path) -> None:
    r = _create_test_note(tmp_path, kind="constraint", title="Show me")
    note_id = _get_note_id(r)
    result = run_cli("-r", str(tmp_path), "note", "show", "-i", note_id)
    assert result.returncode == 0
    assert "Show me" in result.stdout


def test_note_show_nonexistent_id_exits_nonzero(tmp_path: Path) -> None:
    result = run_cli("-r", str(tmp_path), "note", "show", "-i", "99999999T000000Z_ffffffff")
    assert result.returncode != 0
    assert "not found" in result.stderr.lower() or "error" in result.stderr.lower()


def test_note_edit_missing_editor_exits_gracefully(tmp_path: Path) -> None:
    r = _create_test_note(tmp_path, kind="preference", title="Edit me")
    note_id = _get_note_id(r)
    result = run_cli(
        "-r", str(tmp_path), "note", "edit", "-i", note_id,
        env={"EDITOR": "", "VISUAL": ""},
    )
    assert result.returncode != 0
    assert "editor" in result.stderr.lower() or "EDITOR" in result.stderr
```

Implement in `cli.py`:

```python
def _cmd_note_show(args: argparse.Namespace, store: NoteStore) -> None:
    note = store.get_note(args.note_id)
    if note is None:
        print(f"Error: Note '{args.note_id}' not found.", file=sys.stderr)
        sys.exit(1)
    print(note.path.read_text(encoding="utf-8"))


def _cmd_note_edit(args: argparse.Namespace, store: NoteStore) -> None:
    import subprocess as sp

    note = store.get_note(args.note_id)
    if note is None:
        print(f"Error: Note '{args.note_id}' not found.", file=sys.stderr)
        sys.exit(1)

    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or ""
    if not editor:
        print("Error: $EDITOR or $VISUAL must be set to edit notes.", file=sys.stderr)
        sys.exit(1)

    sp.run([editor, str(note.path)], check=False)
```

Wire into `_handle_note()`:
```python
    elif args.note_command == "show":
        _cmd_note_show(args, store)
    elif args.note_command == "edit":
        _cmd_note_edit(args, store)
```

Commit: `feat(cli): implement note show and note edit commands`

---

#### Task 5: `search` command

Add 4 tests to `tests/cli_test.py`:

```python
def test_search_finds_note_by_title_word(tmp_path: Path) -> None:
    _create_test_note(tmp_path, kind="constraint", title="Always use pathlib")
    _create_test_note(tmp_path, kind="preference", title="Prefer f-strings")
    result = run_cli("-r", str(tmp_path), "search", "-q", "pathlib")
    assert result.returncode == 0
    assert "pathlib" in result.stdout.lower()
    assert "f-strings" not in result.stdout.lower()


def test_search_no_results_exits_zero(tmp_path: Path) -> None:
    _create_test_note(tmp_path, kind="constraint", title="Unrelated note")
    result = run_cli("-r", str(tmp_path), "search", "-q", "xyzxyzxyz")
    assert result.returncode == 0
    assert "0" in result.stdout or "no results" in result.stdout.lower()


def test_search_filter_by_kind(tmp_path: Path) -> None:
    _create_test_note(tmp_path, kind="constraint", title="Constraint with sqlite")
    _create_test_note(tmp_path, kind="preference", title="Preference with sqlite")
    result = run_cli("-r", str(tmp_path), "search", "-q", "sqlite", "-k", "constraint")
    assert result.returncode == 0
    assert "Constraint with sqlite" in result.stdout
    assert "Preference with sqlite" not in result.stdout


def test_search_requires_query_flag(tmp_path: Path) -> None:
    result = run_cli("-r", str(tmp_path), "search")
    assert result.returncode != 0
```

Implement by replacing `_handle_search` stub:

```python
def _handle_search(args: argparse.Namespace, store: NoteStore) -> None:
    notes = store.search(
        query=args.query,
        project=args.project,
        kind=args.kind,
    )
    if not notes:
        print("0 results.")
        return
    for note in notes:
        print(f"{note.id}  {note.kind:12s}  {note.project:20s}  {note.title}")
```

**Check `store.search()` signature first** — it may not accept `project` and `kind` directly. If not, filter in Python after the call.

Commit: `feat(cli): implement search command`

---

#### Task 6: `index rebuild` and `index status` commands

Add 5 tests to `tests/cli_test.py`:

```python
def test_index_rebuild_exits_zero(tmp_path: Path) -> None:
    _create_test_note(tmp_path, kind="constraint", title="Rebuild me")
    result = run_cli("-r", str(tmp_path), "index", "rebuild")
    assert result.returncode == 0
    assert "rebuild" in result.stdout.lower() or "indexed" in result.stdout.lower()


def test_index_rebuild_reports_count(tmp_path: Path) -> None:
    _create_test_note(tmp_path, kind="constraint", title="Note 1")
    _create_test_note(tmp_path, kind="preference", title="Note 2")
    result = run_cli("-r", str(tmp_path), "index", "rebuild")
    assert result.returncode == 0
    assert "2" in result.stdout


def test_index_status_exits_zero(tmp_path: Path) -> None:
    _create_test_note(tmp_path, kind="constraint", title="Status test")
    result = run_cli("-r", str(tmp_path), "index", "status")
    assert result.returncode == 0


def test_index_status_shows_note_count(tmp_path: Path) -> None:
    _create_test_note(tmp_path, kind="constraint", title="Count me")
    result = run_cli("-r", str(tmp_path), "index", "status")
    assert result.returncode == 0
    assert "1" in result.stdout


def test_index_status_empty_root(tmp_path: Path) -> None:
    result = run_cli("-r", str(tmp_path), "index", "status")
    assert result.returncode == 0
    assert "0" in result.stdout or "empty" in result.stdout.lower()
```

Implement by replacing `_handle_index` stub:

```python
def _handle_index(args: argparse.Namespace, store: NoteStore) -> None:
    if args.index_command is None:
        print("usage: agent-memory index <rebuild|status>", file=sys.stderr)
        sys.exit(1)

    if args.index_command == "rebuild":
        count = store.rebuild_index()
        print(f"Rebuild complete. Indexed {count} note(s).")

    elif args.index_command == "status":
        notes = store.list_notes(limit=10_000)
        errors = store.verify()
        print(f"Notes: {len(notes)}")
        print(f"Index errors: {len(errors)}")
        if errors:
            for err in errors:
                print(f"  - {err}")
    else:
        print(f"Unknown index action: {args.index_command}", file=sys.stderr)
        sys.exit(1)
```

After implementing, also:
1. Update `docs/PROJECT_STATUS.md`: change `Phase 3 — CLI` to `✅ COMPLETE`
2. Run **all** tests: `uv run pytest tests/ -v --tb=short` (should be ~58+ tests all passing)

Commit: `feat(cli): implement index rebuild and status — CLI complete`

---

### After PLAN-3 is Done: PLAN-4 (LLM Classification)

Plan is at: `docs/plans/PLAN-4-CLASSIFY.md`

Summary: Replace the stub `agent_memory/classify.py` with real LLM classification via `llm_local`. 4 tasks:
1. Static rules (PlacementError, determine_project)
2. LLM integration via `_llm_complete` module-level import
3. Interactive fallback when LLM unreachable
4. Wire into NoteStore.create_note()

Key design: `_llm_complete` imported at module level with try/except so tests can patch `agent_memory.classify._llm_complete`.

---

## Key Architectural Notes

### Flag ordering
`-r/--root` is a **top-level** global flag. Always pass it BEFORE the subcommand:
```bash
agent-memory -r /path/to/notes note create -k constraint -t "Title"
```
NOT: `agent-memory note create -r /path/to/notes ...`

### NoteStore API
```python
store = NoteStore(root=Path("/path"))   # root=None uses AGENT_MEMORY_ROOT or default
store.create_note(kind, title, body, created_by, project=None, tags=None, auto_classify=False, dry_run=False) -> Note
store.get_note(note_id: str) -> Note | None
store.list_notes(project=None, kind=None, tags=None, limit=None) -> list[Note]
store.search(query: str, project=None, kind=None) -> list[Note]
store.rebuild_index() -> int
store.verify() -> list[str]
```

### Kind taxonomy
- **GLOBAL_DEFAULT** (constraint, preference) → project defaults to "global"
- **PROJECT_REQUIRED** (handoff, task, bug) → must pass `--project`
- **LLM_CLASSIFY** (decision, code_note, session) → LLM or fallback to "global"

### Test style
- Test files named `<module>_test.py` (never `test_<module>.py`)
- No `from __future__ import annotations`
- `str | None` not `Optional[str]`
- f-strings only
- `subprocess.CompletedProcess[str]` for CLI test helper return type

---

## Files to Attach When Opening in Browser LLM

- `/home/mcarls/scripts/modules/agent_memory/agent_memory/cli.py`
- `/home/mcarls/scripts/modules/agent_memory/tests/cli_test.py`
- `/home/mcarls/scripts/modules/agent_memory/agent_memory/store.py`
- `/home/mcarls/scripts/modules/agent_memory/docs/plans/PLAN-3-CLI.md`
- `/home/mcarls/scripts/modules/agent_memory/docs/plans/PLAN-4-CLASSIFY.md`
