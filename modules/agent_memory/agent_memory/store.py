from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from agent_memory.classify import determine_project
from agent_memory.frontmatter import (
    CODE_DUPLICATE_ID,
    CODE_KIND_PATH_MISMATCH,
    CODE_PROJECT_PATH_MISMATCH,
    CODE_UNKNOWN_LAYOUT,
    CURRENT_SCHEMA_VERSION,
    ValidationIssue,
    parse_frontmatter,
    parse_frontmatter_safe,
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


# ---------------------------------------------------------------------------
# Path layout resolver
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NotePathMetadata:
    """Decoded layout information for a note file path."""

    scope: Literal["global", "project", "unknown"]
    project: str | None
    kind: str | None
    layout: Literal["v1", "sharded", "unknown"]


def resolve_note_path_metadata(path: Path, root: Path) -> NotePathMetadata:
    """Decode scope, project, kind, and layout from a note's filesystem path.

    Supported layouts::

        <root>/global/<kind>/<file>.md          → scope=global, layout=v1
        <root>/projects/<project>/<kind>/<file>.md → scope=project, layout=v1

    Any other structure is reported as ``scope=unknown, layout=unknown``.
    """
    try:
        rel = path.relative_to(root)
    except ValueError:
        return NotePathMetadata(scope="unknown", project=None, kind=None, layout="unknown")

    parts = rel.parts  # e.g. ("global", "decision", "file.md")

    if len(parts) >= 3 and parts[0] == "global":
        return NotePathMetadata(scope="global", project="global", kind=parts[1], layout="v1")

    if len(parts) >= 4 and parts[0] == "projects":
        return NotePathMetadata(scope="project", project=parts[1], kind=parts[2], layout="v1")

    # Possible future sharding: <root>/s/<shard>/<kind>/<file>.md
    if len(parts) >= 4 and parts[0] == "s":
        return NotePathMetadata(scope="unknown", project=None, kind=parts[2], layout="sharded")

    return NotePathMetadata(scope="unknown", project=None, kind=None, layout="unknown")


# ---------------------------------------------------------------------------
# Duplicate-ID exception
# ---------------------------------------------------------------------------


class DuplicateNoteIDError(Exception):
    """Raised by rebuild_index() when duplicate note IDs are detected.

    Attributes:
        issues: List of ValidationIssue objects describing each duplicate.
        duplicates: Mapping of note_id → list of conflicting paths (str).
    """

    def __init__(self, issues: list[ValidationIssue], duplicates: dict[str, list[str]]) -> None:
        self.issues = issues
        self.duplicates = duplicates
        pairs = "; ".join(f"{nid}: {paths}" for nid, paths in duplicates.items())
        super().__init__(f"Duplicate note IDs detected: {pairs}")


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

        Pre-scans files for duplicate note IDs and aborts with
        ``DuplicateNoteIDError`` before any upserts if any are found.

        Returns:
            Number of notes indexed.

        Raises:
            DuplicateNoteIDError: If two or more files share the same note ID.
        """
        # --- Phase 1: collect all (id, path) pairs and check for duplicates ---
        file_ids: list[tuple[str, Path]] = []
        for md_file in sorted(self._root.rglob("*.md")):
            if ".index" in md_file.parts:
                continue
            try:
                text = md_file.read_text(encoding="utf-8")
                meta, _ = parse_frontmatter(text)
                note_id = meta.get("id")
                if isinstance(note_id, str) and note_id:
                    file_ids.append((note_id, md_file))
            except Exception:
                pass

        seen: dict[str, list[str]] = {}
        for note_id, path in file_ids:
            seen.setdefault(note_id, []).append(str(path))

        duplicates = {nid: paths for nid, paths in seen.items() if len(paths) > 1}
        if duplicates:
            dup_issues: list[ValidationIssue] = []
            for note_id, paths in duplicates.items():
                for p in paths:
                    dup_issues.append(
                        ValidationIssue(
                            path=Path(p),
                            field="id",
                            code=CODE_DUPLICATE_ID,
                            message=f"Note ID '{note_id}' appears in multiple files: " + ", ".join(paths),
                            severity="error",
                        )
                    )
            raise DuplicateNoteIDError(dup_issues, duplicates)

        # --- Phase 2: upsert all valid notes ---
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

    def verify(self) -> list[ValidationIssue]:
        """Check all notes for validation errors and path/frontmatter consistency.

        Uses ``parse_frontmatter_safe()`` so every file is checked independently
        regardless of whether earlier files have issues.  Also detects duplicate
        note IDs across the vault.

        Returns:
            List of ``ValidationIssue`` objects. Empty means all notes are valid.
        """
        issues: list[ValidationIssue] = []
        seen_ids: dict[str, list[str]] = {}  # id → list[path strings]

        for md_file in sorted(self._root.rglob("*.md")):
            if ".index" in md_file.parts:
                continue
            try:
                text = md_file.read_text(encoding="utf-8")
            except OSError as exc:
                issues.append(
                    ValidationIssue(
                        path=md_file,
                        field=None,
                        code="FILE_READ_ERROR",
                        message=f"Cannot read file: {exc}",
                        severity="error",
                    )
                )
                continue

            result = parse_frontmatter_safe(text, path=md_file)
            issues.extend(result.issues)

            if not result.has_frontmatter or not result.metadata:
                continue

            meta = result.metadata
            note_id = meta.get("id")

            # Track IDs for duplicate detection.
            if isinstance(note_id, str) and note_id:
                seen_ids.setdefault(note_id, []).append(str(md_file))

            # Path layout cross-checks (only when layout is known).
            path_meta = resolve_note_path_metadata(md_file, self._root)
            if path_meta.layout == "unknown":
                issues.append(
                    ValidationIssue(
                        path=md_file,
                        field=None,
                        code=CODE_UNKNOWN_LAYOUT,
                        message=(
                            "File is not under a recognised layout directory "
                            "(global/<kind>/ or projects/<project>/<kind>/)."
                        ),
                        severity="warning",
                    )
                )
            else:
                fm_kind = meta.get("kind") if isinstance(meta.get("kind"), str) else None
                if fm_kind and path_meta.kind and fm_kind != path_meta.kind:
                    issues.append(
                        ValidationIssue(
                            path=md_file,
                            field="kind",
                            code=CODE_KIND_PATH_MISMATCH,
                            message=(
                                f"Frontmatter kind='{fm_kind}' does not match "
                                f"directory kind='{path_meta.kind}'."
                            ),
                            severity="error",
                        )
                    )
                fm_project = meta.get("project") if isinstance(meta.get("project"), str) else None
                if fm_project and path_meta.project and fm_project != path_meta.project:
                    issues.append(
                        ValidationIssue(
                            path=md_file,
                            field="project",
                            code=CODE_PROJECT_PATH_MISMATCH,
                            message=(
                                f"Frontmatter project='{fm_project}' does not match "
                                f"path project='{path_meta.project}'."
                            ),
                            severity="error",
                        )
                    )

        # Report duplicate IDs.
        for note_id, paths in seen_ids.items():
            if len(paths) > 1:
                for p in paths:
                    issues.append(
                        ValidationIssue(
                            path=Path(p),
                            field="id",
                            code=CODE_DUPLICATE_ID,
                            message=(
                                f"Note ID '{note_id}' appears in multiple files: "
                                + ", ".join(paths)
                            ),
                            severity="error",
                        )
                    )

        return issues


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
