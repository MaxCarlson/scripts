"""agent_memory CLI — entry point for the agent-memory command."""
import argparse
import os
import shlex
import subprocess
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


def _root_parser() -> argparse.ArgumentParser:
    """Shared parent parser that provides the -r/--root flag."""
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument(
        "-r", "--root",
        metavar="ROOT",
        help="Notes root directory (overrides AGENT_MEMORY_ROOT env var).",
    )
    return p


def _make_parser() -> argparse.ArgumentParser:
    root_parent = _root_parser()
    parser = argparse.ArgumentParser(
        prog="agent-memory",
        description="Manage persistent AI agent memory notes.",
        parents=[root_parent],
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
    create_p.add_argument("-g", "--tags", default="", help="Comma-separated tags.")
    create_p.add_argument("-L", "--no-llm", action="store_true", help="Disable LLM auto-classification.")
    create_p.add_argument("-n", "--dry-run", action="store_true", help="Print note without writing.")
    create_p.add_argument("-A", "--source-agent", default=None, metavar="AGENT",
                          help="Agent identifier that produced this note (optional).")
    create_p.add_argument("-S", "--session-id", default=None, metavar="ID",
                          help="Session or conversation ID to attach to this note (optional).")
    create_p.add_argument("-F", "--file", action="append", default=[], dest="files", metavar="PATH",
                          help="File path relevant to this note (repeatable).")

    # note list
    list_p = note_sub.add_parser("list", help="List notes.")
    list_p.add_argument("-p", "--project", default=None, help="Filter by project slug.")
    list_p.add_argument("-k", "--kind", default=None, help="Filter by kind.")
    list_p.add_argument("-g", "--tags", default="", help="Comma-separated tags to filter by.")
    list_p.add_argument("-l", "--limit", type=int, default=20, metavar="N", help="Maximum results (default: 20).")
    list_p.add_argument("-s", "--status", default=None,
                        help="Filter by lifecycle status (active, superseded, archived, draft).")
    list_p.add_argument("-y", "--layer", default=None,
                        help="Filter by memory layer (core, working, archival, reflective).")

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


def _handle_note(args: argparse.Namespace, store: NoteStore) -> None:
    if args.note_command is None:
        print("usage: agent-memory note <create|list|show|edit>", file=sys.stderr)
        sys.exit(1)
    if args.note_command == "create":
        _cmd_note_create(args, store)
    elif args.note_command == "list":
        _cmd_note_list(args, store)
    elif args.note_command == "show":
        _cmd_note_show(args, store)
    elif args.note_command == "edit":
        _cmd_note_edit(args, store)
    else:
        print(f"Unknown note action: {args.note_command}", file=sys.stderr)
        sys.exit(1)


def _cmd_note_create(args: argparse.Namespace, store: NoteStore) -> None:
    """Handle the 'note create' subcommand."""
    from agent_memory.note import PROJECT_REQUIRED_KINDS

    if args.kind in PROJECT_REQUIRED_KINDS and not args.project:
        print(
            f"Error: --project is required for kind '{args.kind}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
    auto_classify = not args.no_llm
    files = list(args.files) if args.files else []

    try:
        note = store.create_note(
            kind=args.kind,
            project=args.project,
            title=args.title,
            body=args.body,
            created_by="agent-memory-cli",
            tags=tags,
            auto_classify=auto_classify,
            dry_run=args.dry_run,
            source_agent=args.source_agent or None,
            session_id=args.session_id or None,
            files=files or None,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        from agent_memory.frontmatter import write_frontmatter

        meta: dict[str, object] = {
            "id": note.id,
            "schema_version": note.schema_version,
            "kind": note.kind,
            "project": note.project,
            "title": note.title,
            "created_at": note.created_at,
            "created_by": note.created_by,
            "updated_at": note.updated_at,
            "updated_by": note.updated_by,
            "status": note.status,
            "layer": note.layer,
            "tags": note.tags,
        }
        print(write_frontmatter(meta, note.body))
    else:
        print(f"Created: {note.id}  ({note.path})")


def _cmd_note_list(args: argparse.Namespace, store: NoteStore) -> None:
    """Handle the 'note list' subcommand."""
    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None
    notes = store.list_notes(
        project=args.project,
        kind=args.kind,
        tags=tags,
        limit=args.limit,
        status=args.status or None,
        layer=args.layer or None,
    )
    if not notes:
        print("0 notes found.")
        return
    for note in notes:
        tag_str = f"  [{', '.join(note.tags)}]" if note.tags else ""
        print(f"{note.id}  {note.kind:12s}  {note.project:20s}  {note.title}{tag_str}")


def _cmd_note_show(args: argparse.Namespace, store: NoteStore) -> None:
    """Handle the 'note show' subcommand."""
    note = store.get_note(args.note_id)
    if note is None:
        print(f"Error: Note '{args.note_id}' not found.", file=sys.stderr)
        sys.exit(1)
    print(note.path.read_text(encoding="utf-8"))


def _cmd_note_edit(args: argparse.Namespace, store: NoteStore) -> None:
    """Handle the 'note edit' subcommand."""
    note = store.get_note(args.note_id)
    if note is None:
        print(f"Error: Note '{args.note_id}' not found.", file=sys.stderr)
        sys.exit(1)

    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or ""
    if not editor:
        print("Error: $EDITOR or $VISUAL must be set to edit notes.", file=sys.stderr)
        sys.exit(1)

    try:
        result = subprocess.run([*shlex.split(editor), str(note.path)], check=False)
    except FileNotFoundError as exc:
        print(f"Error: editor command not found: {exc.filename}", file=sys.stderr)
        sys.exit(1)
    if result.returncode != 0:
        sys.exit(result.returncode)


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
        for err in errors:
            print(f"  - {err}")
    else:
        print(f"Unknown index action: {args.index_command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
