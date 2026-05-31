from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from agent_memory.classify import determine_project
from agent_memory.frontmatter import (
    CURRENT_SCHEMA_VERSION,
    parse_frontmatter,
    validate_frontmatter,
    write_frontmatter,
)
from agent_memory.index import NoteIndex
from agent_memory.naming import make_filename, make_note_id
from agent_memory.note import (
    ACTIVE_KINDS,
    DEFAULT_LAYER_BY_KIND,
    DEFAULT_STATUS,
    DEPRECATED_KINDS,
    Note,
)

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
        # Title: prefer frontmatter field (V2), fall back to first H1 in body.
        title = str(meta.get("title", ""))
        if not title:
            for line in body.splitlines():
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
        if not title:
            title = str(meta.get("id", ""))
        return Note(
            id=str(meta["id"]),
            path=path,
            kind=str(meta["kind"]),
            project=str(meta["project"]),
            title=title,
            body=body,
            created_at=str(meta["created_at"]),
            created_by=str(meta["created_by"]),
            tags=list(meta.get("tags") or []),
            schema_version=int(meta.get("schema_version", 1)),
            # V2 optional fields — degrade gracefully when absent
            updated_at=str(meta.get("updated_at", "")),
            updated_by=str(meta.get("updated_by", "")),
            status=str(meta.get("status", DEFAULT_STATUS)),
            layer=str(meta.get("layer", "")),
            source_agent=meta.get("source_agent") or None,
            session_id=meta.get("session_id") or None,
            confidence=_float_or_none(meta.get("confidence")),
            review_required=bool(meta.get("review_required", False)),
            classification_reason=meta.get("classification_reason") or None,
            classification_method=meta.get("classification_method") or None,
            related=list(meta.get("related") or []),
            supersedes=list(meta.get("supersedes") or []),
            superseded_by=list(meta.get("superseded_by") or []),
            evidence_for=list(meta.get("evidence_for") or []),
            files=list(meta.get("files") or []),
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
        # V2 optional metadata
        source_agent: str | None = None,
        session_id: str | None = None,
        review_required: bool = False,
        classification_reason: str | None = None,
        classification_method: str | None = None,
        related: list[str] | None = None,
        supersedes: list[str] | None = None,
        superseded_by: list[str] | None = None,
        evidence_for: list[str] | None = None,
        files: list[str] | None = None,
    ) -> Note:
        """Create a new memory note (always writes V2 frontmatter).

        Args:
            kind: Note kind — must be in ACTIVE_KINDS (deprecated kinds rejected).
            project: Project slug, "global", or None (triggers auto-placement).
            title: Human-readable note title.
            body: Markdown body text.
            created_by: Agent or human identifier (e.g. "claude-code").
            tags: Optional list of tag strings.
            auto_classify: If True and project is None, call llm_local to classify.
            dry_run: If True, return the Note without writing any files.
            source_agent: Agent that produced this note (optional).
            session_id: Session/conversation identifier (optional).
            review_required: Flag for human review (default False).
            classification_reason: Reason code from classifier (optional).
            classification_method: How placement was decided (optional).
            related / supersedes / superseded_by / evidence_for: Relationship IDs.
            files: File paths relevant to this note.

        Returns:
            The created Note. If dry_run, path will be the expected path but file
            will not exist.

        Raises:
            ValueError: For unknown or deprecated kinds.
        """
        if kind in DEPRECATED_KINDS:
            raise ValueError(
                f"Kind '{kind}' is deprecated and cannot be created. "
                f"Use one of: {sorted(ACTIVE_KINDS)}"
            )
        if kind not in ACTIVE_KINDS:
            raise ValueError(f"Invalid kind '{kind}'. Valid kinds: {sorted(ACTIVE_KINDS)}")

        resolved_project = determine_project(
            kind=kind,
            project=project,
            title=title,
            auto_classify=auto_classify,
            interactive=True,
            body=body,
        )
        note_id = make_note_id()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        resolved_tags = tags or []
        layer = DEFAULT_LAYER_BY_KIND.get(kind, "archival")

        meta: dict[str, object] = {
            "id": note_id,
            "schema_version": CURRENT_SCHEMA_VERSION,
            "kind": kind,
            "project": resolved_project,
            "title": title,
            "created_at": now,
            "created_by": created_by,
            "updated_at": now,
            "updated_by": created_by,
            "status": DEFAULT_STATUS,
            "layer": layer,
            "tags": resolved_tags,
        }
        # Optional V2 fields — include only when non-empty/non-None.
        if source_agent:
            meta["source_agent"] = source_agent
        if session_id:
            meta["session_id"] = session_id
        if review_required:
            meta["review_required"] = True
        if classification_reason:
            meta["classification_reason"] = classification_reason
        if classification_method:
            meta["classification_method"] = classification_method
        for field_name, value in [
            ("related", related),
            ("supersedes", supersedes),
            ("superseded_by", superseded_by),
            ("evidence_for", evidence_for),
            ("files", files),
        ]:
            if value:
                meta[field_name] = value

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
            created_at=now,
            created_by=created_by,
            tags=resolved_tags,
            schema_version=CURRENT_SCHEMA_VERSION,
            updated_at=now,
            updated_by=created_by,
            status=DEFAULT_STATUS,
            layer=layer,
            source_agent=source_agent,
            session_id=session_id,
            review_required=review_required,
            classification_reason=classification_reason,
            classification_method=classification_method,
            related=related or [],
            supersedes=supersedes or [],
            superseded_by=superseded_by or [],
            evidence_for=evidence_for or [],
            files=files or [],
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
            created_at=now,
            created_by=created_by,
            tags=resolved_tags,
            full_content=content,
            schema_version=CURRENT_SCHEMA_VERSION,
            updated_at=now,
            updated_by=created_by,
            status=DEFAULT_STATUS,
            layer=layer,
            source_agent=source_agent,
            session_id=session_id,
            review_required=review_required,
            classification_reason=classification_reason,
            classification_method=classification_method,
            related=related or [],
            supersedes=supersedes or [],
            superseded_by=superseded_by or [],
            evidence_for=evidence_for or [],
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
        status: str | None = None,
        layer: str | None = None,
    ) -> list[Note]:
        """Return notes matching filters, newest first."""
        records = self._index.list_notes(
            project=project, kind=kind, tags=tags, limit=limit,
            status=status, layer=layer,
        )
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
                # Title: frontmatter preferred (V2), then H1.
                fm_title = str(meta.get("title", ""))
                if not fm_title:
                    for line in body.splitlines():
                        if line.startswith("# "):
                            fm_title = line[2:].strip()
                            break
                layer = str(meta.get("layer", DEFAULT_LAYER_BY_KIND.get(str(meta.get("kind", "")), "")))
                self._index.upsert(
                    note_id=str(meta["id"]),
                    path=str(md_file),
                    project=str(meta.get("project", "global")),
                    kind=str(meta.get("kind", "")),
                    title=fm_title,
                    body=body,
                    created_at=str(meta.get("created_at", "")),
                    created_by=str(meta.get("created_by", "")),
                    tags=list(meta.get("tags") or []),
                    full_content=text,
                    schema_version=int(meta.get("schema_version", 1)),
                    updated_at=str(meta.get("updated_at", "")),
                    updated_by=str(meta.get("updated_by", "")),
                    status=str(meta.get("status", DEFAULT_STATUS)),
                    layer=layer,
                    source_agent=meta.get("source_agent") or None,
                    session_id=meta.get("session_id") or None,
                    confidence=_float_or_none(meta.get("confidence")),
                    review_required=bool(meta.get("review_required", False)),
                    classification_reason=meta.get("classification_reason") or None,
                    classification_method=meta.get("classification_method") or None,
                    related=list(meta.get("related") or []),
                    supersedes=list(meta.get("supersedes") or []),
                    superseded_by=list(meta.get("superseded_by") or []),
                    evidence_for=list(meta.get("evidence_for") or []),
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
                        errors.append(
                            f"{md_file}: frontmatter kind='{meta['kind']}' but directory says '{path_kind}'"
                        )
            except Exception as exc:
                errors.append(f"{md_file}: parse error: {exc}")
        return errors


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
