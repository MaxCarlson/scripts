#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Project link-file utilities for Knowledge Manager.

A small JSON file (<name>.kmproj) that lives alongside your code/work
folder. It references a project in the KM database and the base data dir
so you can `km -o ./<name>.kmproj` to jump straight into that project.

Public API (import-safe):
- LINK_EXT
- ProjectLink (dataclass)
- create_link_for_project(name, directory, base_data_dir=None, file_name=None) -> (ProjectLink, Path)
- load_link_file(path) -> ProjectLink
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple
import json
import uuid
import logging

from . import utils, db, project_ops
from .models import ProjectStatus

LINK_EXT = ".kmproj"


@dataclass(frozen=True)
class ProjectLink:
    version: int
    type: str
    project_id: uuid.UUID
    project_name: str
    base_data_dir: Optional[Path]
    created_at: datetime

    @staticmethod
    def from_json_text(text: str) -> "ProjectLink":
        data = json.loads(text)
        if data.get("type") != "knowledge_manager.project-link" or int(data.get("version", 0)) != 1:
            raise ValueError("Unsupported or invalid project-link file.")
        base_data_dir = data.get("base_data_dir")
        return ProjectLink(
            version=1,
            type="knowledge_manager.project-link",
            project_id=uuid.UUID(data["project_id"]),
            project_name=str(data["project_name"]),
            base_data_dir=Path(base_data_dir) if base_data_dir else None,
            created_at=datetime.fromisoformat(data["created_at"]),
        )

    def to_json_text(self) -> str:
        payload = {
            "version": 1,
            "type": "knowledge_manager.project-link",
            "project_id": str(self.project_id),
            "project_name": self.project_name,
            "base_data_dir": str(self.base_data_dir) if self.base_data_dir else None,
            "created_at": self.created_at.isoformat(),
        }
        return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _slugify(name: str) -> str:
    s = name.strip().replace("/", "-").replace("\\", "-")
    s = " ".join(s.split())
    s = s.replace(" ", "-")
    filtered = "".join(ch for ch in s if ch.isalnum() or ch in "-_.")
    return filtered or "project"


def _ensure_project(name: str, base_data_dir: Optional[Path]) -> uuid.UUID:
    # ensure db exists
    db_path = utils.get_db_path(base_data_dir)
    conn = db.get_db_connection(db_path)
    try:
        existing = db.get_project_by_name(conn, name)
        if existing:
            return existing.id
    finally:
        conn.close()
    # create via ops (keeps md file creation consistent)
    proj = project_ops.create_new_project(name=name, status=ProjectStatus.ACTIVE, base_data_dir=base_data_dir)
    return proj.id


def create_link_for_project(
    project_name: str,
    directory: Path,
    base_data_dir: Optional[Path] = None,
    file_name: Optional[str] = None,
    force: bool = False,
) -> Tuple[ProjectLink, Path]:
    """
    Ensure project exists; write `<slug>.kmproj` to `directory`; return (link, path).

    Args:
        project_name: The name of the project.
        directory: The directory to create the link file in.
        base_data_dir: The base data directory for the project.
        file_name: The name of the link file (without extension).
        force: If True, overwrite an existing link file.

    Raises:
        FileExistsError: If the link file already exists and `force` is False.
    """
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    project_id = _ensure_project(project_name, base_data_dir)

    slug = _slugify(file_name or project_name)
    link_path = directory / f"{slug}{LINK_EXT}"

    if link_path.exists() and not force:
        raise FileExistsError(f"Link file already exists: {link_path}. Use --force to overwrite.")

    link = ProjectLink(
        version=1,
        type="knowledge_manager.project-link",
        project_id=project_id,
        project_name=project_name,
        base_data_dir=(Path(base_data_dir).resolve() if base_data_dir else None),
        created_at=datetime.now(timezone.utc),
    )
    link_path.write_text(link.to_json_text(), encoding="utf-8")
    logging.getLogger(__name__).info("Created project link: %s -> %s", link_path, project_id)
    return link, link_path


def load_link_file(path: Path) -> ProjectLink:
    return ProjectLink.from_json_text(Path(path).read_text(encoding="utf-8"))
