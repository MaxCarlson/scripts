# File: tests/tui/app_test.py
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import asyncio

from textual.widgets import ListView

from knowledge_manager.tui.app import KmApp
from knowledge_manager.tui.screens.projects import ProjectsScreen
from knowledge_manager.tui.screens.tasks import TasksScreen
from knowledge_manager.tui.widgets.lists import ProjectList, ProjectListItem
from knowledge_manager.models import Project, Task, ProjectStatus, TaskStatus
from knowledge_manager.tui.widgets.footer import CustomFooter
from knowledge_manager.tui.widgets.dialogs import LinkSelectionDialog

pytestmark = pytest.mark.asyncio

async def test_app_starts_on_projects_screen(mocker):
    """Test that the app starts and pushes the ProjectsScreen."""
    mocker.patch('knowledge_manager.project_ops.list_all_projects', return_value=[])
    
    app = KmApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        
        # After mount, the first screen pushed is ProjectsScreen
        assert len(app.screen_stack) == 2 # [_default, ProjectsScreen]
        assert isinstance(app.screen, ProjectsScreen)
        
        footer = app.screen.query_one(CustomFooter)
        assert footer is not None

async def test_project_selection_pushes_tasks_screen(mocker):
    """Test that selecting a project pushes the TasksScreen."""
    proj1 = Project(name="Project One")
    task1 = Task(title="Task in P1", project_id=proj1.id)
    
    mocker.patch('knowledge_manager.project_ops.list_all_projects', return_value=[proj1])
    mocker.patch('knowledge_manager.task_ops.list_all_tasks', return_value=[task1])
    
    app = KmApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        
        projects_screen = app.screen
        assert isinstance(projects_screen, ProjectsScreen)
        
        # Simulate the selection message
        project_list_view = projects_screen.query_one(ProjectList)
        project_item = projects_screen.query_one(ProjectListItem)
        app.post_message(ListView.Selected(project_list_view, project_item))
        
        await pilot.pause()
        
        # After pushing TasksScreen, stack size should be 3
        assert len(app.screen_stack) == 3 # [_default, ProjectsScreen, TasksScreen]
        assert isinstance(app.screen, TasksScreen)
        
        # Pop back to projects screen
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.screen_stack) == 2 # [_default, ProjectsScreen]
        assert isinstance(app.screen, ProjectsScreen)


async def test_follow_link_with_multiple_links_shows_dialog(mocker):
    """Test that following a link on a task with multiple links shows the selection dialog."""
    # Create a mock app and screen
    app = KmApp()
    project = Project(name="Test Project")
    screen = TasksScreen(project=project)

    # Mock the app and its push_screen method
    app.push_screen = MagicMock()

    # Create a task with multiple links
    task_with_links = Task(title="This task has @link1 and &link2")
    screen.app.selected_task = task_with_links

    # Mock the extract_links function to return multiple links
    mocker.patch('knowledge_manager.links.extract_links', return_value=[
        ('project', 'link1', 0, 0),
        ('task', 'link2', 0, 0)
    ])

    # Call the action
    await screen.action_follow_link()

    # Assert that push_screen was called with the LinkSelectionDialog
    app.push_screen.assert_called_once()
    dialog = app.push_screen.call_args[0][0]
    assert isinstance(dialog, LinkSelectionDialog)
    assert dialog.links == ['@link1', '&link2']
