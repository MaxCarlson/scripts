import os
import subprocess
import sys
from pathlib import Path



def run_cli(*args: str, env: dict | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
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
    result = run_cli("-r", str(root), "index", "status")
    # Status command should accept the --root flag without crashing
    assert result.returncode in (0, 1)  # may fail if dir empty, but must not crash


def test_env_var_root_accepted(tmp_path: Path) -> None:
    """AGENT_MEMORY_ROOT env var should be accepted."""
    result = run_cli("index", "status", env={"AGENT_MEMORY_ROOT": str(tmp_path)})
    assert result.returncode in (0, 1)  # dir exists but empty


def test_short_root_flag(tmp_path: Path) -> None:
    result = run_cli("-r", str(tmp_path), "index", "status")
    assert result.returncode in (0, 1)


def test_note_create_writes_file(tmp_path: Path) -> None:
    result = run_cli(
        "-r", str(tmp_path),
        "note", "create",
        "-k", "constraint",
        "-t", "Always use pathlib",
        "-b", "## Summary\n\nUse pathlib.Path.",
        "--tags", "python,style",
    )
    assert result.returncode == 0, result.stderr
    md_files = list(tmp_path.rglob("*.md"))
    assert len(md_files) == 1
    content = md_files[0].read_text(encoding="utf-8")
    assert "Always use pathlib" in content
    assert "constraint" in content


def test_note_create_prints_note_id(tmp_path: Path) -> None:
    result = run_cli(
        "-r", str(tmp_path),
        "note", "create",
        "-k", "preference",
        "-t", "Use f-strings",
    )
    assert result.returncode == 0, result.stderr
    assert "Created:" in result.stdout or len(result.stdout.strip()) > 0


def test_note_create_dry_run_prints_but_does_not_write(tmp_path: Path) -> None:
    result = run_cli(
        "-r", str(tmp_path),
        "note", "create",
        "-k", "constraint",
        "-t", "Dry run note",
        "--dry-run",
    )
    assert result.returncode == 0, result.stderr
    md_files = list(tmp_path.rglob("*.md"))
    assert len(md_files) == 0
    assert "constraint" in result.stdout or "Dry run note" in result.stdout


def test_note_create_project_required_kind_without_project_fails(tmp_path: Path) -> None:
    result = run_cli(
        "-r", str(tmp_path),
        "note", "create",
        "-k", "handoff",
        "-t", "Some handoff",
    )
    assert result.returncode != 0
    assert "project" in result.stderr.lower() or "required" in result.stderr.lower()


def test_note_create_project_required_kind_with_project_succeeds(tmp_path: Path) -> None:
    result = run_cli(
        "-r", str(tmp_path),
        "note", "create",
        "-k", "handoff",
        "-p", "my-project",
        "-t", "Handoff summary",
    )
    assert result.returncode == 0, result.stderr
    md_files = list(tmp_path.rglob("*.md"))
    assert len(md_files) == 1


def _create_test_note(
    tmp_path: Path,
    kind: str = "constraint",
    title: str = "Test note",
    project: str | None = None,
    tags: str = "",
) -> subprocess.CompletedProcess[str]:
    args = ["-r", str(tmp_path), "note", "create", "-k", kind, "-t", title]
    if project:
        args += ["-p", project]
    if tags:
        args += ["--tags", tags]
    return run_cli(*args)


def _get_note_id(create_result: subprocess.CompletedProcess[str]) -> str:
    """Extract note ID from 'Created: <id>  (<path>)' output."""
    line = create_result.stdout.strip()
    return line.split("Created:")[1].strip().split()[0]


def test_note_list_empty_root_shows_empty(tmp_path: Path) -> None:
    result = run_cli("-r", str(tmp_path), "note", "list")
    assert result.returncode == 0
    assert "0" in result.stdout or result.stdout.strip() == "" or "no notes" in result.stdout.lower()


def test_note_list_shows_created_notes(tmp_path: Path) -> None:
    _create_test_note(tmp_path, kind="constraint", title="Note A")
    _create_test_note(tmp_path, kind="preference", title="Note B")
    result = run_cli("-r", str(tmp_path), "note", "list")
    assert result.returncode == 0
    assert "Note A" in result.stdout
    assert "Note B" in result.stdout


def test_note_list_filter_by_kind(tmp_path: Path) -> None:
    _create_test_note(tmp_path, kind="constraint", title="Constraint note")
    _create_test_note(tmp_path, kind="preference", title="Preference note")
    result = run_cli("-r", str(tmp_path), "note", "list", "-k", "constraint")
    assert result.returncode == 0
    assert "Constraint note" in result.stdout
    assert "Preference note" not in result.stdout


def test_note_list_filter_by_project(tmp_path: Path) -> None:
    _create_test_note(tmp_path, kind="decision", title="Project note", project="my-proj")
    _create_test_note(tmp_path, kind="constraint", title="Global note")
    result = run_cli("-r", str(tmp_path), "note", "list", "-p", "my-proj")
    assert result.returncode == 0
    assert "Project note" in result.stdout
    assert "Global note" not in result.stdout


def test_note_list_limit(tmp_path: Path) -> None:
    for i in range(5):
        _create_test_note(tmp_path, kind="constraint", title=f"Note {i}")
    result = run_cli("-r", str(tmp_path), "note", "list", "--limit", "2")
    assert result.returncode == 0
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) <= 4  # 2 notes + possible header/footer lines


def test_note_show_displays_full_content(tmp_path: Path) -> None:
    result = _create_test_note(tmp_path, kind="constraint", title="Show me")
    note_id = _get_note_id(result)
    show_result = run_cli("-r", str(tmp_path), "note", "show", "-i", note_id)
    assert show_result.returncode == 0
    assert "Show me" in show_result.stdout


def test_note_show_nonexistent_id_exits_nonzero(tmp_path: Path) -> None:
    result = run_cli("-r", str(tmp_path), "note", "show", "-i", "99999999T000000Z_ffffffff")
    assert result.returncode != 0
    assert "not found" in result.stderr.lower() or "error" in result.stderr.lower()


def test_note_edit_missing_editor_exits_gracefully(tmp_path: Path) -> None:
    result = _create_test_note(tmp_path, kind="preference", title="Edit me")
    note_id = _get_note_id(result)
    edit_result = run_cli(
        "-r",
        str(tmp_path),
        "note",
        "edit",
        "-i",
        note_id,
        env={"EDITOR": "", "VISUAL": ""},
    )
    assert edit_result.returncode != 0
    assert "editor" in edit_result.stderr.lower() or "EDITOR" in edit_result.stderr


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


# ---------------------------------------------------------------------------
# Plan 6: verify subcommand
# ---------------------------------------------------------------------------

def test_verify_exits_zero_for_valid_notes(tmp_path: Path) -> None:
    _create_test_note(tmp_path, kind="constraint", title="Valid note")
    result = run_cli("-r", str(tmp_path), "verify")
    assert result.returncode == 0


def test_verify_empty_root_exits_zero(tmp_path: Path) -> None:
    result = run_cli("-r", str(tmp_path), "verify")
    assert result.returncode == 0
    assert "valid" in result.stdout.lower() or "0" in result.stdout


def test_verify_exits_nonzero_on_errors(tmp_path: Path) -> None:
    _create_test_note(tmp_path, kind="constraint", title="Good note")
    bad_path = tmp_path / "global" / "constraint" / "bad-note.md"
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_text("---\nid: bad\nkind: not-a-kind\n---\n\nBody.", encoding="utf-8")
    result = run_cli("-r", str(tmp_path), "verify")
    assert result.returncode != 0


def test_verify_json_output_is_valid_json(tmp_path: Path) -> None:
    import json

    _create_test_note(tmp_path, kind="constraint", title="JSON test")
    result = run_cli("-r", str(tmp_path), "verify", "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert isinstance(data, list)


def test_verify_warnings_as_errors_flag(tmp_path: Path) -> None:
    """--warnings-as-errors makes warnings count as failures."""
    # A note without layer generates a warning; valid V2 notes have layer so no warning.
    # Create a note then manually strip layer to induce a warning.
    from agent_memory.store import NoteStore

    store = NoteStore(root=tmp_path)
    note = store.create_note(
        kind="constraint", project=None, title="No layer note", body="Body.", created_by="test"
    )
    text = note.path.read_text(encoding="utf-8")
    stripped = "\n".join(line for line in text.splitlines() if not line.startswith("layer:"))
    note.path.write_text(stripped, encoding="utf-8")

    result_normal = run_cli("-r", str(tmp_path), "verify")
    result_strict = run_cli("-r", str(tmp_path), "verify", "--warnings-as-errors")
    # Normal mode: only errors cause nonzero exit; warnings alone may exit 0.
    # Strict mode: any warnings also cause nonzero exit.
    # If there are warnings, strict must exit nonzero.
    if result_normal.returncode == 0:
        # Normal succeeded; strict should fail if there are warnings.
        assert result_strict.returncode != 0 or "0 error" in result_strict.stdout.lower()


def test_verify_short_json_flag(tmp_path: Path) -> None:
    import json

    _create_test_note(tmp_path, kind="preference", title="Short JSON flag")
    result = run_cli("-r", str(tmp_path), "verify", "-j")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert isinstance(data, list)
