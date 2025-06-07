# File: tests/tui/test_app.py
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import asyncio

from textual.widgets import ListView, Header

from knowledge_manager.tui.app import KmApp
from knowledge_manager.tui.screens.projects import ProjectsScreen
from knowledge_manager.tui.screens.tasks import TasksScreen
from knowledge_manager.tui.widgets.lists import ProjectList, ProjectListItem
from knowledge_manager.models import Project, Task, ProjectStatus, TaskStatus

pytestmark = pytest.mark.asyncio

async def test_app_starts_on_projects_screen(mocker):
    """Test that the app starts and pushes the ProjectsScreen."""
    mocker.patch('knowledge_manager.project_ops.list_all_projects', return_value=[])
    
    app = KmApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        
        # After mount, the stack should have the default screen and our ProjectsScreen
        assert len(app.screen_stack) == 2
        assert isinstance(app.screen, ProjectsScreen)
        
        header = app.screen.query_one(Header)
        assert header.name == "KM - Projects"

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
        
        project_list_view = projects_screen.query_one(ProjectList)
        project_item = projects_screen.query_one(ProjectListItem)
        
        app.post_message(ListView.Selected(project_list_view, project_item))
        
        await pilot.pause()
        
        # After pushing TasksScreen, stack size should be 3
        assert len(app.screen_stack) == 3
        assert isinstance(app.screen, TasksScreen)
        header = app.screen.query_one(Header)
        assert header.name == "Tasks: Project One"
        
        # Test popping the screen
        await pilot.press("escape")
        await pilot.pause()
        # After popping, stack size should be back to 2
        assert len(app.screen_stack) == 2
        assert isinstance(app.screen, ProjectsScreen)
