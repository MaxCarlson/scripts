#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Link resolution utilities for Knowledge Manager.

Supports inline links in markdown:
- @project-name or @"Project Name" - Links to projects
- &task-title or &"Task Title" - Links to tasks
"""

from __future__ import annotations

import re
from typing import Optional, List, Tuple
from pathlib import Path
import uuid

from . import project_ops, task_ops
from .models import Project, Task


# Link patterns
PROJECT_LINK_PATTERN = re.compile(r'@(?:"([^"]+)"|([^\s@&]+))')
TASK_LINK_PATTERN = re.compile(r'&(?:"([^"]+)"|([^\s@&]+))')


def extract_links(text: str) -> List[Tuple[str, str, int, int]]:
    """
    Extract all links from text.

    Returns list of (link_type, link_target, start_pos, end_pos) tuples.
    link_type is either 'project' or 'task'.
    """
    links = []

    # Find project links
    for match in PROJECT_LINK_PATTERN.finditer(text):
        target = match.group(1) or match.group(2)
        links.append(('project', target, match.start(), match.end()))

    # Find task links
    for match in TASK_LINK_PATTERN.finditer(text):
        target = match.group(1) or match.group(2)
        links.append(('task', target, match.start(), match.end()))

    return links


def extract_project_mentions(text: str) -> List[str]:
    """
    Extract all @project mentions from text (for auto-linking).

    Returns list of project names/identifiers.
    Example: "Fix bug @todo @modules" -> ["todo", "modules"]
    """
    mentions = []
    for match in PROJECT_LINK_PATTERN.finditer(text):
        target = match.group(1) or match.group(2)
        if target:
            mentions.append(target)
    return mentions


def find_link_at_position(text: str, position: int) -> Optional[Tuple[str, str]]:
    """
    Find link at the given character position in text.

    Returns (link_type, link_target) or None if no link at position.
    """
    links = extract_links(text)
    for link_type, target, start, end in links:
        if start <= position < end:
            return (link_type, target)
    return None


def resolve_project_link(
    target: str,
    base_data_dir: Optional[Path] = None
) -> Optional[Project]:
    """
    Resolve a project link target to a Project object.

    Tries to match by:
    1. UUID (if target looks like UUID)
    2. Exact name match
    3. Case-insensitive name match
    """
    try:
        # Try UUID first
        try:
            project_id = uuid.UUID(target)
            return project_ops.find_project(str(project_id), base_data_dir=base_data_dir)
        except ValueError:
            pass

        # Try exact name match
        project = project_ops.find_project(target, base_data_dir=base_data_dir)
        if project:
            return project

        # Try case-insensitive search through all projects
        all_projects = project_ops.list_all_projects(base_data_dir=base_data_dir)
        target_lower = target.lower()
        for proj in all_projects:
            if proj.name.lower() == target_lower:
                return proj

        return None
    except Exception:
        return None


def resolve_task_link(
    target: str,
    project_context: Optional[uuid.UUID] = None,
    base_data_dir: Optional[Path] = None
) -> Optional[Task]:
    """
    Resolve a task link target to a Task object.

    Tries to match by:
    1. UUID (if target looks like UUID)
    2. Title prefix match (scoped to project_context if provided)
    3. Case-insensitive title search
    """
    try:
        # Try UUID first
        try:
            task_id = uuid.UUID(target)
            return task_ops.find_task(str(task_id), base_data_dir=base_data_dir)
        except ValueError:
            pass

        # Try title prefix match
        project_id_str = str(project_context) if project_context else None
        task = task_ops.find_task(
            task_identifier=target,
            project_identifier=project_id_str,
            base_data_dir=base_data_dir
        )
        if task:
            return task

        # Try case-insensitive search
        all_tasks = task_ops.list_all_tasks(
            project_identifier=project_id_str,
            include_subtasks_of_any_parent=True,
            base_data_dir=base_data_dir
        )
        target_lower = target.lower()
        for t in all_tasks:
            if t.title.lower() == target_lower:
                return t
            # Also try prefix match
            if t.title.lower().startswith(target_lower):
                return t

        return None
    except Exception:
        return None


def format_link_help() -> str:
    """Return help text explaining link syntax."""
    return """
Link Syntax:
  @project-name or @"Project Name"  - Link to a project
  &task-title or &"Task Title"      - Link to a task

Navigation:
  Ctrl+G - Follow link under cursor
"""
