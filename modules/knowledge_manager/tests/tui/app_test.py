# File: tests/tui/test_app.py
import pytest
from pathlib import Path
from textual.widgets import ListView
from unittest.mock import MagicMock, patch

from knowledge_manager.tui.app import KmApp
from knowledge_manager.models import Project, Task, ProjectStatus, TaskStatus

# Mark tests in this file as async so pytest-asyncio can run them
pytestmark = pytest.mark.asyncio

async def test_app_starts_on_projects_screen(mocker):
    """Test that the app starts and pushes the ProjectsScreen."""
    # Mock the ops layer to prevent real DB/file access
    mocker.patch('knowledge_manager.project_ops.list_all_projects', return_value=[])
    
    app = KmApp()
    async with app.run_test() as pilot:
        # Check that the initial screen is the ProjectsScreen
        assert app.screen_stack[0].__class__.__name__ == "ProjectsScreen"
        # Check that the header text is correct
        assert "KM - Projects" in str(app.screen.query_one("Header").renderable)
        await pilot.pause()

async def test_project_selection_pushes_tasks_screen(mocker):
    """Test that selecting a project pushes the TasksScreen."""
    # Setup mock data
    proj1 = Project(name="Project One")
    task1 = Task(title="Task in P1", project_id=proj1.id)
    
    mocker.patch('knowledge_manager.project_ops.list_all_projects', return_value=[proj1])
    mocker.patch('knowledge_manager.task_ops.list_all_tasks', return_value=[task1])
    
    app = KmApp()
    async with app.run_test() as pilot:
        # Wait for the UI to settle and projects to load
        await pilot.pause()
        
        # Simulate pressing Enter on the first project
        await pilot.press("enter")
        await pilot.pause()

        # Check that the new screen is the TasksScreen
        assert len(app.screen_stack) == 2
        assert app.screen.__class__.__name__ == "TasksScreen"
        # Check that the header reflects the selected project
        assert "Tasks: Project One" in str(app.screen.query_one("Header").renderable)
        
        # Check that the task list was populated
        task_list_text = app.screen.query_one("TaskList").children[0].renderable.plain
        assert "Task in P1" in task_list_text

        # Test popping the screen
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.screen_stack) == 1
        assert app.screen.__class__.__name__ == "ProjectsScreen"
