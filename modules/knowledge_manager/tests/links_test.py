#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Tests for links module."""

import pytest
from pathlib import Path
from knowledge_manager import links, project_ops, task_ops, db, utils
from knowledge_manager.models import ProjectStatus, TaskStatus


@pytest.fixture
def init_db(tmp_path: Path):
    """Initialize database for testing."""
    db_path = utils.get_db_path(tmp_path)
    db.init_db(db_path)
    return tmp_path


def test_extract_links_project():
    """Test extracting project links from text."""
    text = "Check out @my-project for details."
    extracted = links.extract_links(text)
    assert len(extracted) == 1
    assert extracted[0][0] == 'project'
    assert extracted[0][1] == 'my-project'


def test_extract_links_task():
    """Test extracting task links from text."""
    text = "See &my-task for more info."
    extracted = links.extract_links(text)
    assert len(extracted) == 1
    assert extracted[0][0] == 'task'
    assert extracted[0][1] == 'my-task'


def test_extract_links_quoted():
    """Test extracting links with quotes."""
    text = 'Check @"My Project" and &"My Task".'
    extracted = links.extract_links(text)
    assert len(extracted) == 2
    assert extracted[0] == ('project', 'My Project', 6, 19)
    assert extracted[1] == ('task', 'My Task', 24, 34)


def test_extract_links_multiple():
    """Test extracting multiple links."""
    text = "See @project1, @project2, and &task1."
    extracted = links.extract_links(text)
    assert len(extracted) == 3
    assert extracted[0][0] == 'project'
    assert extracted[1][0] == 'project'
    assert extracted[2][0] == 'task'


def test_find_link_at_position():
    """Test finding link at specific position."""
    text = "Check @my-project here."
    # Position within the link
    result = links.find_link_at_position(text, 8)
    assert result == ('project', 'my-project')

    # Position outside the link
    result = links.find_link_at_position(text, 0)
    assert result is None


def test_resolve_project_link(init_db):
    """Test resolving a project link."""
    tmp_path = init_db
    # Create a test project
    project = project_ops.create_new_project(
        name="Test Project",
        status=ProjectStatus.ACTIVE,
        base_data_dir=tmp_path
    )

    # Resolve by name
    resolved = links.resolve_project_link("Test Project", base_data_dir=tmp_path)
    assert resolved is not None
    assert resolved.name == "Test Project"

    # Resolve by ID
    resolved_by_id = links.resolve_project_link(str(project.id), base_data_dir=tmp_path)
    assert resolved_by_id is not None
    assert resolved_by_id.id == project.id


def test_resolve_task_link(init_db):
    """Test resolving a task link."""
    tmp_path = init_db
    # Create a test project and task
    project = project_ops.create_new_project(
        name="Test Project",
        status=ProjectStatus.ACTIVE,
        base_data_dir=tmp_path
    )

    task = task_ops.create_new_task(
        title="Test Task",
        project_identifier=str(project.id),
        base_data_dir=tmp_path
    )

    # Resolve by title
    resolved = links.resolve_task_link(
        "Test Task",
        project_context=project.id,
        base_data_dir=tmp_path
    )
    assert resolved is not None
    assert resolved.title == "Test Task"

    # Resolve by ID
    resolved_by_id = links.resolve_task_link(
        str(task.id),
        project_context=project.id,
        base_data_dir=tmp_path
    )
    assert resolved_by_id is not None
    assert resolved_by_id.id == task.id


def test_resolve_nonexistent_project(tmp_path: Path):
    """Test resolving a non-existent project."""
    resolved = links.resolve_project_link("NonExistent", base_data_dir=tmp_path)
    assert resolved is None


def test_resolve_nonexistent_task(tmp_path: Path):
    """Test resolving a non-existent task."""
    resolved = links.resolve_task_link("NonExistent", base_data_dir=tmp_path)
    assert resolved is None


def test_format_link_help():
    """Test that format_link_help returns a string."""
    help_text = links.format_link_help()
    assert isinstance(help_text, str)
    assert "@project-name" in help_text
    assert "&task-title" in help_text
    assert "Ctrl+G" in help_text

def test_extract_links_from_task_title(init_db):
    """Test extracting links from a task title."""
    tmp_path = init_db
    project = project_ops.create_new_project(name="Test Project", base_data_dir=tmp_path)
    task = task_ops.create_new_task(title="This task is about @some-project", project_identifier=project.id, base_data_dir=tmp_path)

    extracted = links.extract_links(task.title)
    assert len(extracted) == 1
    assert extracted[0][0] == 'project'
    assert extracted[0][1] == 'some-project'

def test_extract_links_from_title_and_details(init_db):
    """Test extracting links from both title and details."""
    tmp_path = init_db
    project = project_ops.create_new_project(name="Test Project", base_data_dir=tmp_path)
    task = task_ops.create_new_task(
        title="This task is about @project1",
        project_identifier=project.id,
        base_data_dir=tmp_path
    )
    details_path = task_ops.get_task_file_path(task.id, base_data_dir=tmp_path, create_if_missing_in_object=True)
    details_path.write_text("See also &task1")

    title_links = links.extract_links(task.title)
    details_links = links.extract_links(details_path.read_text())

    all_links = title_links + details_links

    assert len(all_links) == 2
    assert all_links[0][0] == 'project'
    assert all_links[0][1] == 'project1'
    assert all_links[1][0] == 'task'
    assert all_links[1][1] == 'task1'
