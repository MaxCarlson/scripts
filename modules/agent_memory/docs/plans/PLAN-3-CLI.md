# agent_memory CLI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`
> (recommended) or `superpowers:executing-plans` to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `agent-memory` CLI — a full argparse-based command-line interface
for creating, reading, listing, editing, searching, and indexing memory notes.

**Architecture:** Single `agent_memory/cli.py` module. Top-level parser delegates to
subparsers: `note` (create/list/show/edit), `search`, `index` (rebuild/status).
Every subcommand accepts `-r/--root` to override the notes root. All I/O through
`NoteStore`. Exit code 0 on success, 1 on error.

**Tech Stack:** Python 3.11+, `argparse` (stdlib), `agent_memory.store.NoteStore`,
`uv run pytest` for tests. CLI entry point: `agent_memory.cli:main` (already in
`pyproject.toml`).

**Prerequisites:** Plan 2 complete — `NoteStore`, `Note`, and all core modules
installed and tested.

**Working directory:** `/home/mcarls/scripts/modules/agent_memory/`

---

## File Map

| File | Responsibility |
|---|---|
| `agent_memory/cli.py` | All CLI code — argparse, dispatch, output formatting |
| `tests/cli_test.py` | CLI tests via `subprocess` or direct `main()` call |

---

## Task 1: CLI scaffold — parser, `--root`, `AGENT_MEMORY_ROOT`

**Files:**
- Create: `agent_memory/cli.py`
- Create: `tests/cli_test.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/cli_test.py
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def run_cli(*args: str, env: dict | None = None, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run agent-memory CLI and return CompletedProcess."""
    return subprocess.run(
        [sys.executable, "-m", "agent_memory.cli", *args],
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        cwd=cwd,
    )


def test_no_args_prints_help() -> None:
    result = run_cli()
    assert result.returncode == 0
    assert "usage" in result.stdout.lower() or "usage" in result.stderr.lower()


def test_help_flag_exits_zero() -> None:
    result = run_cli("--help")
    assert result.returncode == 0


def test_unknown_command_exits_nonzero() -> None:
    result = run_cli("nonexistent-command")
    assert result.returncode != 0


def test_root_flag_sets_notes_root(tmp_path: Path) -> None:
    """--root should be accepted and used (even if directory doesn't exist yet)."""
    root = tmp_path / "custom_notes"
    result = run_cli("index", "status", "-r", str(root))
    # Status command should accept the --root flag without crashing
    assert result.returncode in (0, 1)  # may fail if dir empty, but must not crash


def test_env_var_root_accepted(tmp_path: Path) -> None:
    """AGENT_MEMORY_ROOT env var should be accepted."""
    result = run_cli("index", "status", env={"AGENT_MEMORY_ROOT": str(tmp_path)})
    assert result.returncode in (0, 1)  # dir exists but empty


def test_short_root_flag(tmp_path: Path) -> None:
    result = run_cli("index", "status", "-r", str(tmp_path))
    assert result.returncode in (0, 1)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/mcarls/scripts/modules/agent_memory
uv run pytest tests/cli_test.py::test_no_args_prints_help -v --tb=short
```

Expected: `ModuleNotFoundError` or similar — `cli.py` doesn't exist yet.

- [ ] **Step 3: Write `agent_memory/cli.py` scaffold**

```python
"""agent_memory CLI — entry point for the agent-memory command."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from agent_memory.store import NoteStore


def _get_root(args: argparse.Namespace) -> Path | None:
    if hasattr(args, "root") and args.root:
        return Path(args.root)
    env = os.environ.get("AGENT_MEMORY_ROOT")
    if env:
        return Path(env)
    return None


def _make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-memory",
        description="Manage persistent AI agent memory notes.",
    )
    parser.add_argument(
        "-r", "--root",
        metavar="ROOT",
        help="Notes root directory (overrides AGENT_MEMORY_ROOT env var).",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # --- note subcommand ---
    note_p = sub.add_parser("note", help="Manage individual notes.")
    note_sub = note_p.add_subparsers(dest="note_command", metavar="ACTION")

    # note create
    create_p = note_sub.add_parser("create", help="Create a new note.")
    create_p.add_argument("-k", "--kind", required=True, help="Note kind (e.g. decision, constraint).")
    create_p.add_argument("-p", "--project", default=None, help="Project slug or 'global'.")
    create_p.add_argument("-t", "--title", required=True, help="Note title.")
    create_p.add_argument("-b", "--body", default="", help="Note body text.")
    create_p.add_argument("--tags", default="", help="Comma-separated tags.")
    create_p.add_argument("--no-llm", action="store_true", help="Disable LLM auto-classification.")
    create_p.add_argument("-n", "--dry-run", action="store_true", help="Print note without writing.")

    # note list
    list_p = note_sub.add_parser("list", help="List notes.")
    list_p.add_argument("-p", "--project", default=None, help="Filter by project slug.")
    list_p.add_argument("-k", "--kind", default=None, help="Filter by kind.")
    list_p.add_argument("--tags", default="", help="Comma-separated tags to filter by.")
    list_p.add_argument("--limit", type=int, default=20, metavar="N", help="Maximum results (default: 20).")

    # note show
    show_p = note_sub.add_parser("show", help="Show a note's full content.")
    show_p.add_argument("-i", "--id", required=True, dest="note_id", help="Note ID.")

    # note edit
    edit_p = note_sub.add_parser("edit", help="Edit a note in $EDITOR.")
    edit_p.add_argument("-i", "--id", required=True, dest="note_id", help="Note ID.")

    # --- search subcommand ---
    search_p = sub.add_parser("search", help="Full-text search notes.")
    search_p.add_argument("-q", "--query", required=True, help="Search query.")
    search_p.add_argument("-p", "--project", default=None, help="Limit to project slug.")
    search_p.add_argument("-k", "--kind", default=None, help="Limit to kind.")

    # --- index subcommand ---
    index_p = sub.add_parser("index", help="Manage the SQLite index.")
    index_sub = index_p.add_subparsers(dest="index_command", metavar="ACTION")
    index_sub.add_parser("rebuild", help="Rebuild the SQLite index from Markdown files.")
    index_sub.add_parser("status", help="Show index statistics.")

    return parser


def main() -> None:
    parser = _make_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    root = _get_root(args)
    store = NoteStore(root=root)

    if args.command == "note":
        _handle_note(args, store)
    elif args.command == "search":
        _handle_search(args, store)
    elif args.command == "index":
        _handle_index(args, store)
    else:
        parser.print_help()
        sys.exit(1)


def _handle_note(args: argparse.Namespace, store: NoteStore) -> None:
    if args.note_command is None:
        print("usage: agent-memory note <create|list|show|edit>", file=sys.stderr)
        sys.exit(1)
    # Dispatch to individual handlers implemented in later tasks
    print(f"[note {args.note_command}] not yet implemented", file=sys.stderr)
    sys.exit(1)


def _handle_search(args: argparse.Namespace, store: NoteStore) -> None:
    print("[search] not yet implemented", file=sys.stderr)
    sys.exit(1)


def _handle_index(args: argparse.Namespace, store: NoteStore) -> None:
    if args.index_command is None:
        print("usage: agent-memory index <rebuild|status>", file=sys.stderr)
        sys.exit(1)
    print(f"[index {args.index_command}] not yet implemented", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

```bash
cd /home/mcarls/scripts/modules/agent_memory
uv run pytest tests/cli_test.py -v --tb=short
```

Expected: All 6 scaffold tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/mcarls/scripts/modules/agent_memory
git add agent_memory/cli.py tests/cli_test.py
git commit -m "feat(cli): scaffold — argparse parser, root flag, AGENT_MEMORY_ROOT"
```

---

## Task 2: `note create` command

**Files:**
- Modify: `agent_memory/cli.py`
- Modify: `tests/cli_test.py` (append tests)

- [ ] **Step 1: Add failing tests**

Append to `tests/cli_test.py`:

```python
def test_note_create_writes_file(tmp_path: Path) -> None:
    result = run_cli(
        "note", "create",
        "-k", "constraint",
        "-t", "Always use pathlib",
        "-b", "## Summary\n\nUse pathlib.Path.",
        "--tags", "python,style",
        "-r", str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    md_files = list(tmp_path.rglob("*.md"))
    assert len(md_files) == 1
    content = md_files[0].read_text(encoding="utf-8")
    assert "Always use pathlib" in content
    assert "constraint" in content


def test_note_create_prints_note_id(tmp_path: Path) -> None:
    result = run_cli(
        "note", "create",
        "-k", "preference",
        "-t", "Use f-strings",
        "-r", str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert "Created:" in result.stdout or len(result.stdout.strip()) > 0


def test_note_create_dry_run_prints_but_does_not_write(tmp_path: Path) -> None:
    result = run_cli(
        "note", "create",
        "-k", "constraint",
        "-t", "Dry run note",
        "--dry-run",
        "-r", str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    md_files = list(tmp_path.rglob("*.md"))
    assert len(md_files) == 0
    assert "constraint" in result.stdout or "Dry run note" in result.stdout


def test_note_create_project_required_kind_without_project_fails(tmp_path: Path) -> None:
    result = run_cli(
        "note", "create",
        "-k", "handoff",
        "-t", "Some handoff",
        "-r", str(tmp_path),
    )
    assert result.returncode != 0
    assert "project" in result.stderr.lower() or "required" in result.stderr.lower()


def test_note_create_project_required_kind_with_project_succeeds(tmp_path: Path) -> None:
    result = run_cli(
        "note", "create",
        "-k", "handoff",
        "-p", "my-project",
        "-t", "Handoff summary",
        "-r", str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    md_files = list(tmp_path.rglob("*.md"))
    assert len(md_files) == 1
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd /home/mcarls/scripts/modules/agent_memory
uv run pytest tests/cli_test.py::test_note_create_writes_file -v --tb=short
```

Expected: FAIL — `[note create] not yet implemented`.

- [ ] **Step 3: Implement `_cmd_note_create()` in `cli.py`**

Replace the `_handle_note` function and add `_cmd_note_create`:

```python
def _handle_note(args: argparse.Namespace, store: NoteStore) -> None:
    if args.note_command is None:
        print("usage: agent-memory note <create|list|show|edit>", file=sys.stderr)
        sys.exit(1)
    if args.note_command == "create":
        _cmd_note_create(args, store)
    elif args.note_command == "list":
        print("[note list] not yet implemented", file=sys.stderr)
        sys.exit(1)
    elif args.note_command == "show":
        print("[note show] not yet implemented", file=sys.stderr)
        sys.exit(1)
    elif args.note_command == "edit":
        print("[note edit] not yet implemented", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"Unknown note action: {args.note_command}", file=sys.stderr)
        sys.exit(1)


def _cmd_note_create(args: argparse.Namespace, store: NoteStore) -> None:
    from agent_memory.note import PROJECT_REQUIRED_KINDS

    if args.kind in PROJECT_REQUIRED_KINDS and not args.project:
        print(
            f"Error: --project is required for kind '{args.kind}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
    auto_classify = not args.no_llm

    note = store.create_note(
        kind=args.kind,
        project=args.project,
        title=args.title,
        body=args.body,
        created_by="agent-memory-cli",
        tags=tags,
        auto_classify=auto_classify,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        from agent_memory.frontmatter import write_frontmatter
        import dataclasses
        meta = {
            "id": note.id,
            "schema_version": note.schema_version,
            "kind": note.kind,
            "project": note.project,
            "created_at": note.created_at,
            "created_by": note.created_by,
            "tags": note.tags,
        }
        print(write_frontmatter(meta, note.body))
    else:
        print(f"Created: {note.id}  ({note.path})")
```

- [ ] **Step 4: Run tests**

```bash
cd /home/mcarls/scripts/modules/agent_memory
uv run pytest tests/cli_test.py -v --tb=short -k "create"
```

Expected: All 5 create tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/mcarls/scripts/modules/agent_memory
git add agent_memory/cli.py tests/cli_test.py
git commit -m "feat(cli): implement note create command"
```

---

## Task 3: `note list` command

**Files:**
- Modify: `agent_memory/cli.py`
- Modify: `tests/cli_test.py` (append tests)

- [ ] **Step 1: Add failing tests**

Append to `tests/cli_test.py`:

```python
def _create_test_note(tmp_path: Path, kind: str = "constraint", title: str = "Test note",
                      project: str | None = None, tags: str = "") -> subprocess.CompletedProcess:
    args = ["note", "create", "-k", kind, "-t", title, "-r", str(tmp_path)]
    if project:
        args += ["-p", project]
    if tags:
        args += ["--tags", tags]
    return run_cli(*args)


def test_note_list_empty_root_shows_empty(tmp_path: Path) -> None:
    result = run_cli("note", "list", "-r", str(tmp_path))
    assert result.returncode == 0
    # No notes, but no crash
    assert "0" in result.stdout or result.stdout.strip() == "" or "no notes" in result.stdout.lower()


def test_note_list_shows_created_notes(tmp_path: Path) -> None:
    _create_test_note(tmp_path, kind="constraint", title="Note A")
    _create_test_note(tmp_path, kind="preference", title="Note B")
    result = run_cli("note", "list", "-r", str(tmp_path))
    assert result.returncode == 0
    assert "Note A" in result.stdout
    assert "Note B" in result.stdout


def test_note_list_filter_by_kind(tmp_path: Path) -> None:
    _create_test_note(tmp_path, kind="constraint", title="Constraint note")
    _create_test_note(tmp_path, kind="preference", title="Preference note")
    result = run_cli("note", "list", "-k", "constraint", "-r", str(tmp_path))
    assert result.returncode == 0
    assert "Constraint note" in result.stdout
    assert "Preference note" not in result.stdout


def test_note_list_filter_by_project(tmp_path: Path) -> None:
    _create_test_note(tmp_path, kind="decision", title="Project note", project="my-proj")
    _create_test_note(tmp_path, kind="constraint", title="Global note")
    result = run_cli("note", "list", "-p", "my-proj", "-r", str(tmp_path))
    assert result.returncode == 0
    assert "Project note" in result.stdout
    assert "Global note" not in result.stdout


def test_note_list_limit(tmp_path: Path) -> None:
    for i in range(5):
        _create_test_note(tmp_path, kind="constraint", title=f"Note {i}")
    result = run_cli("note", "list", "--limit", "2", "-r", str(tmp_path))
    assert result.returncode == 0
    lines = [l for l in result.stdout.splitlines() if l.strip()]
    assert len(lines) <= 4  # 2 notes + possible header/footer lines
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd /home/mcarls/scripts/modules/agent_memory
uv run pytest tests/cli_test.py::test_note_list_shows_created_notes -v --tb=short
```

Expected: FAIL — `[note list] not yet implemented`.

- [ ] **Step 3: Implement `_cmd_note_list()` in `cli.py`**

Replace `[note list] not yet implemented` branch and add the function:

```python
    elif args.note_command == "list":
        _cmd_note_list(args, store)
```

Add the function:

```python
def _cmd_note_list(args: argparse.Namespace, store: NoteStore) -> None:
    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None
    notes = store.list_notes(
        project=args.project,
        kind=args.kind,
        tags=tags,
        limit=args.limit,
    )
    if not notes:
        print("0 notes found.")
        return
    for note in notes:
        tag_str = f"  [{', '.join(note.tags)}]" if note.tags else ""
        print(f"{note.id}  {note.kind:12s}  {note.project:20s}  {note.title}{tag_str}")
```

- [ ] **Step 4: Run tests**

```bash
cd /home/mcarls/scripts/modules/agent_memory
uv run pytest tests/cli_test.py -v --tb=short -k "list"
```

Expected: All 5 list tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/mcarls/scripts/modules/agent_memory
git add agent_memory/cli.py tests/cli_test.py
git commit -m "feat(cli): implement note list command"
```

---

## Task 4: `note show` and `note edit` commands

**Files:**
- Modify: `agent_memory/cli.py`
- Modify: `tests/cli_test.py` (append tests)

- [ ] **Step 1: Add failing tests**

Append to `tests/cli_test.py`:

```python
def _get_note_id(create_result: subprocess.CompletedProcess) -> str:
    """Extract note ID from 'Created: <id>  (<path>)' output."""
    line = create_result.stdout.strip()
    return line.split("Created:")[1].strip().split()[0]


def test_note_show_displays_full_content(tmp_path: Path) -> None:
    r = _create_test_note(tmp_path, kind="constraint", title="Show me")
    note_id = _get_note_id(r)
    result = run_cli("note", "show", "-i", note_id, "-r", str(tmp_path))
    assert result.returncode == 0
    assert "Show me" in result.stdout


def test_note_show_nonexistent_id_exits_nonzero(tmp_path: Path) -> None:
    result = run_cli("note", "show", "-i", "99999999T000000Z_ffffffff", "-r", str(tmp_path))
    assert result.returncode != 0
    assert "not found" in result.stderr.lower() or "error" in result.stderr.lower()


def test_note_edit_missing_editor_exits_gracefully(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    r = _create_test_note(tmp_path, kind="preference", title="Edit me")
    note_id = _get_note_id(r)
    result = run_cli(
        "note", "edit", "-i", note_id, "-r", str(tmp_path),
        env={"EDITOR": "", "VISUAL": ""},
    )
    assert result.returncode != 0
    assert "editor" in result.stderr.lower() or "EDITOR" in result.stderr
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd /home/mcarls/scripts/modules/agent_memory
uv run pytest tests/cli_test.py::test_note_show_displays_full_content -v --tb=short
```

Expected: FAIL — `[note show] not yet implemented`.

- [ ] **Step 3: Implement `_cmd_note_show()` and `_cmd_note_edit()` in `cli.py`**

Replace `[note show]` and `[note edit]` branches and add functions:

```python
    elif args.note_command == "show":
        _cmd_note_show(args, store)
    elif args.note_command == "edit":
        _cmd_note_edit(args, store)
```

Add functions:

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

- [ ] **Step 4: Run tests**

```bash
cd /home/mcarls/scripts/modules/agent_memory
uv run pytest tests/cli_test.py -v --tb=short -k "show or edit"
```

Expected: All 3 show/edit tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/mcarls/scripts/modules/agent_memory
git add agent_memory/cli.py tests/cli_test.py
git commit -m "feat(cli): implement note show and note edit commands"
```

---

## Task 5: `search` command

**Files:**
- Modify: `agent_memory/cli.py`
- Modify: `tests/cli_test.py` (append tests)

- [ ] **Step 1: Add failing tests**

Append to `tests/cli_test.py`:

```python
def test_search_finds_note_by_title_word(tmp_path: Path) -> None:
    _create_test_note(tmp_path, kind="constraint", title="Always use pathlib")
    _create_test_note(tmp_path, kind="preference", title="Prefer f-strings")
    result = run_cli("search", "-q", "pathlib", "-r", str(tmp_path))
    assert result.returncode == 0
    assert "pathlib" in result.stdout.lower()
    assert "f-strings" not in result.stdout.lower()


def test_search_no_results_exits_zero(tmp_path: Path) -> None:
    _create_test_note(tmp_path, kind="constraint", title="Unrelated note")
    result = run_cli("search", "-q", "xyzxyzxyz", "-r", str(tmp_path))
    assert result.returncode == 0
    assert "0" in result.stdout or "no results" in result.stdout.lower()


def test_search_filter_by_kind(tmp_path: Path) -> None:
    _create_test_note(tmp_path, kind="constraint", title="Constraint with sqlite")
    _create_test_note(tmp_path, kind="preference", title="Preference with sqlite")
    result = run_cli("search", "-q", "sqlite", "-k", "constraint", "-r", str(tmp_path))
    assert result.returncode == 0
    assert "Constraint with sqlite" in result.stdout
    assert "Preference with sqlite" not in result.stdout


def test_search_requires_query_flag(tmp_path: Path) -> None:
    result = run_cli("search", "-r", str(tmp_path))
    assert result.returncode != 0
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd /home/mcarls/scripts/modules/agent_memory
uv run pytest tests/cli_test.py::test_search_finds_note_by_title_word -v --tb=short
```

Expected: FAIL — `[search] not yet implemented`.

- [ ] **Step 3: Implement `_handle_search()` in `cli.py`**

Replace the existing `_handle_search` stub:

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

- [ ] **Step 4: Run tests**

```bash
cd /home/mcarls/scripts/modules/agent_memory
uv run pytest tests/cli_test.py -v --tb=short -k "search"
```

Expected: All 4 search tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/mcarls/scripts/modules/agent_memory
git add agent_memory/cli.py tests/cli_test.py
git commit -m "feat(cli): implement search command"
```

---

## Task 6: `index rebuild` and `index status` commands

**Files:**
- Modify: `agent_memory/cli.py`
- Modify: `tests/cli_test.py` (append tests)

- [ ] **Step 1: Add failing tests**

Append to `tests/cli_test.py`:

```python
def test_index_rebuild_exits_zero(tmp_path: Path) -> None:
    _create_test_note(tmp_path, kind="constraint", title="Rebuild me")
    result = run_cli("index", "rebuild", "-r", str(tmp_path))
    assert result.returncode == 0
    assert "rebuild" in result.stdout.lower() or "indexed" in result.stdout.lower()


def test_index_rebuild_reports_count(tmp_path: Path) -> None:
    _create_test_note(tmp_path, kind="constraint", title="Note 1")
    _create_test_note(tmp_path, kind="preference", title="Note 2")
    result = run_cli("index", "rebuild", "-r", str(tmp_path))
    assert result.returncode == 0
    assert "2" in result.stdout


def test_index_status_exits_zero(tmp_path: Path) -> None:
    _create_test_note(tmp_path, kind="constraint", title="Status test")
    result = run_cli("index", "status", "-r", str(tmp_path))
    assert result.returncode == 0


def test_index_status_shows_note_count(tmp_path: Path) -> None:
    _create_test_note(tmp_path, kind="constraint", title="Count me")
    result = run_cli("index", "status", "-r", str(tmp_path))
    assert result.returncode == 0
    assert "1" in result.stdout


def test_index_status_empty_root(tmp_path: Path) -> None:
    result = run_cli("index", "status", "-r", str(tmp_path))
    assert result.returncode == 0
    assert "0" in result.stdout or "empty" in result.stdout.lower()
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd /home/mcarls/scripts/modules/agent_memory
uv run pytest tests/cli_test.py::test_index_rebuild_exits_zero -v --tb=short
```

Expected: FAIL — `[index rebuild] not yet implemented`.

- [ ] **Step 3: Implement `_handle_index()` in `cli.py`**

Replace the existing `_handle_index` stub:

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

- [ ] **Step 4: Run all CLI tests**

```bash
cd /home/mcarls/scripts/modules/agent_memory
uv run pytest tests/cli_test.py -v --tb=short
```

Expected: All tests pass (scaffold + create + list + show/edit + search + index).

- [ ] **Step 5: Run the full test suite**

```bash
cd /home/mcarls/scripts/modules/agent_memory
uv run pytest tests/ -v --tb=short
```

Expected: All tests pass (Plan 2 tests + CLI tests).

- [ ] **Step 6: Update PROJECT_STATUS.md**

In `/home/mcarls/scripts/modules/agent_memory/docs/PROJECT_STATUS.md`,
change `Phase 3 — CLI ⏳ NOT STARTED` to `✅ COMPLETE`.

- [ ] **Step 7: Commit**

```bash
cd /home/mcarls/scripts/modules/agent_memory
git add agent_memory/cli.py tests/cli_test.py docs/PROJECT_STATUS.md
git commit -m "feat(cli): implement index rebuild and status — CLI complete"
```

---

## Phase 3 Definition of Done

- [ ] `agent-memory note create -k constraint -t "Always use pathlib" -r /tmp/test` writes a `.md` file
- [ ] `agent-memory note list -r /tmp/test` shows the note
- [ ] `agent-memory note show -i <id> -r /tmp/test` prints the full file
- [ ] `agent-memory note edit -i <id> -r /tmp/test` opens `$EDITOR`
- [ ] `agent-memory search -q pathlib -r /tmp/test` finds the note
- [ ] `agent-memory index rebuild -r /tmp/test` re-scans all `.md` files and reports count
- [ ] `agent-memory index status -r /tmp/test` shows note count and index errors
- [ ] All flags have short + long form
- [ ] `--root / -r` and `AGENT_MEMORY_ROOT` both work
- [ ] Exit code 0 on success, nonzero on error
- [ ] All tests pass
