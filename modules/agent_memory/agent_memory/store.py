from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from agent_memory.classify import determine_project
from agent_memory.frontmatter import parse_frontmatter, validate_frontmatter, write_frontmatter
from agent_memory.index import NoteIndex
from agent_memory.naming import make_filename, make_note_id
from agent_memory.note import VALID_KINDS, Note

logger = logging.getLogger(__name__)

_DEFAULT_ROOT = Path.home() / "scripts" / "modules" / "agent_memory" / "notes"


def _get_default_root() -> Path:
    env = os.environ.get("AGENT_MEMORY_ROOT")
    return Path(env) if env else _DEFAULT_ROOT


class NoteStore:
    """Read/write interface for Markdown memory notes with SQLite indexing."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root if root is not None else _get_default_root()
        self._index = NoteIndex(self._root / ".index" / "notes.sqlite3")

    def _note_dir(self, project: str, kind: str) -> Path:
        if project == "global":
            return self._root / "global" / kind
        return self._root / "projects" / project / kind

    def _read_note_file(self, path: Path) -> Note:
        text = path.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(text)
        title = ""
        for line in body.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        return Note(
            id=str(meta["id"]),
            path=path,
            kind=str(meta["kind"]),
            project=str(meta["project"]),
            title=title or str(meta.get("id", "")),
            body=body,
            created_at=str(meta["created_at"]),
            created_by=str(meta["created_by"]),
            tags=list(meta.get("tags") or []),
            schema_version=int(meta.get("schema_version", 1)),
        )

    def _known_projects(self) -> list[str]:
        projects_dir = self._root / "projects"
        if not projects_dir.exists():
            return []
        return [p.name for p in sorted(projects_dir.iterdir()) if p.is_dir()]

    def create_note(
        self,
        *,
        kind: str,
        project: str | None,
        title: str,
        body: str,
        created_by: str,
        tags: list[str] | None = None,
        auto_classify: bool = False,
        dry_run: bool = False,
    ) -> Note:
        """Create a new memory note.

        Args:
            kind: Note kind (must be in VALID_KINDS).
            project: Project slug, "global", or None (triggers auto-placement).
            title: Human-readable note title.
            body: Markdown body text.
            created_by: Agent or human identifier (e.g. "claude-code").
            tags: Optional list of tag strings.
            auto_classify: If True and project is None, call llm_local to classify.
            dry_run: If True, return the Note without writing any files.

        Returns:
            The created Note. If dry_run, path will be the expected path but file
            will not exist.
        """
        if kind not in VALID_KINDS:
            raise ValueError(f"Invalid kind '{kind}'. Valid kinds: {sorted(VALID_KINDS)}")

        resolved_project = determine_project(
            kind=kind,
            project=project,
            title=title,
            auto_classify=auto_classify,
            interactive=True,
            body=body,
        )
        note_id = make_note_id()
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        resolved_tags = tags or []

        meta: dict[str, object] = {
            "id": note_id,
            "schema_version": 1,
            "kind": kind,
            "project": resolved_project,
            "created_at": created_at,
            "created_by": created_by,
            "tags": resolved_tags,
        }
        full_body = f"# {title}\n\n{body}"
        content = write_frontmatter(meta, full_body)

        note_dir = self._note_dir(resolved_project, kind)
        filename = make_filename(note_id, title)
        note_path = note_dir / filename

        note = Note(
            id=note_id,
            path=note_path,
            kind=kind,
            project=resolved_project,
            title=title,
            body=full_body,
            created_at=created_at,
            created_by=created_by,
            tags=resolved_tags,
        )

        if dry_run:
            return note

        note_dir.mkdir(parents=True, exist_ok=True)
        tmp = note_path.with_suffix(".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.rename(note_path)

        self._index.upsert(
            note_id=note_id,
            path=str(note_path),
            project=resolved_project,
            kind=kind,
            title=title,
            body=full_body,
            created_at=created_at,
            created_by=created_by,
            tags=resolved_tags,
            full_content=content,
        )
        return note

    def get_note(self, note_id: str) -> Note | None:
        """Return a Note by ID, reading from disk. None if not found."""
        record = self._index.get(note_id)
        if record is None:
            return None
        path = Path(record["path"])
        if not path.exists():
            return None
        return self._read_note_file(path)

    def list_notes(
        self,
        project: str | None = None,
        kind: str | None = None,
        tags: list[str] | None = None,
        limit: int = 20,
    ) -> list[Note]:
        """Return notes matching filters, newest first."""
        records = self._index.list_notes(project=project, kind=kind, tags=tags, limit=limit)
        notes: list[Note] = []
        for rec in records:
            path = Path(rec["path"])
            if path.exists():
                try:
                    notes.append(self._read_note_file(path))
                except Exception as exc:
                    logger.warning("Skipping unreadable note %s: %s", path, exc)
        return notes

    def search(
        self,
        query: str,
        project: str | None = None,
        kind: str | None = None,
    ) -> list[Note]:
        """Full-text search across titles and bodies."""
        records = self._index.search(query, project=project, kind=kind)
        notes: list[Note] = []
        for rec in records:
            path = Path(rec["path"])
            if path.exists():
                try:
                    notes.append(self._read_note_file(path))
                except Exception as exc:
                    logger.warning("Skipping unreadable note %s: %s", path, exc)
        return notes

    def rebuild_index(self) -> int:
        """Scan all .md files under notes root and rebuild SQLite index.

        Returns:
            Number of notes indexed.
        """
        count = 0
        for md_file in sorted(self._root.rglob("*.md")):
            if ".index" in md_file.parts:
                continue
            try:
                text = md_file.read_text(encoding="utf-8")
                meta, body = parse_frontmatter(text)
                if not meta.get("id"):
                    continue
                title = ""
                for line in body.splitlines():
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
                self._index.upsert(
                    note_id=str(meta["id"]),
                    path=str(md_file),
                    project=str(meta.get("project", "global")),
                    kind=str(meta.get("kind", "")),
                    title=title,
                    body=body,
                    created_at=str(meta.get("created_at", "")),
                    created_by=str(meta.get("created_by", "")),
                    tags=list(meta.get("tags") or []),
                    full_content=text,
                )
                count += 1
            except Exception as exc:
                logger.warning("Skipping %s: %s", md_file, exc)
        return count

    def verify(self) -> list[str]:
        """Check all notes for validation errors.

        Returns:
            List of error strings. Empty means all notes are valid.
        """
        errors: list[str] = []
        for md_file in sorted(self._root.rglob("*.md")):
            if ".index" in md_file.parts:
                continue
            try:
                text = md_file.read_text(encoding="utf-8")
                meta, _ = parse_frontmatter(text)
                for err in validate_frontmatter(meta):
                    errors.append(f"{md_file}: {err}")
                if not errors:
                    path_kind = md_file.parent.name
                    if meta.get("kind") and meta["kind"] != path_kind:
                        errors.append(f"{md_file}: frontmatter kind='{meta['kind']}' but directory says '{path_kind}'")
            except Exception as exc:
                errors.append(f"{md_file}: parse error: {exc}")
        return errors
