# File: tests/tui/test_app.py
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from knowledge_manager.tui.app import KmApp
from knowledge_manager.tui.screens.projects import ProjectsScreen
from knowledge_manager.tui.screens.tasks import TasksScreen
from knowledge_manager.models import Project, Task, ProjectStatus, TaskStatus

pytestmark = pytest.mark.asyncio

async def test_app_starts_on_projects_screen(mocker):
    """Test that the app starts and pushes the ProjectsScreen."""
    mocker.patch('knowledge_manager.project_ops.list_all_projects', return_value=[])
    
    app = KmApp()
    async with app.run_test() as pilot:
        # After the app mounts, the current screen should be our ProjectsScreen
        assert isinstance(app.screen, ProjectsScreen)
        # Check that the header text is correct for this screen
        assert "KM - Projects" in str(app.screen.query_one("Header").renderable)
        await pilot.pause()

async def test_project_selection_pushes_tasks_screen(mocker):
    """Test that selecting a project pushes the TasksScreen."""
    proj1 = Project(name="Project One")
    task1 = Task(title="Task in P1", project_id=proj1.id)
    
    mocker.patch('knowledge_manager.project_ops.list_all_projects', return_value=[proj1])
    mocker.patch('knowledge_manager.task_ops.list_all_tasks', return_value=[task1])
    
    app = KmApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, ProjectsScreen) # Verify starting screen
        
        # Simulate pressing Enter on the first project
        await pilot.press("enter")
        
        # Wait until the current screen is the TasksScreen
        await pilot.wait_for_screen(TasksScreen)
        
        # Check that the new screen is the TasksScreen
        assert len(app.screen_stack) == 2
        assert isinstance(app.screen, TasksScreen)
        assert "Tasks: Project One" in str(app.screen.query_one("Header").renderable)
        
        # Check that the task list was populated
        task_list_text = app.screen.query_one("TaskList").children[0].renderable.plain
        assert "Task in P1" in task_list_text

        # Test popping the screen
        await pilot.press("escape")
        await pilot.wait_for_screen(ProjectsScreen)
        assert len(app.screen_stack) == 1
        assert isinstance(app.screen, ProjectsScreen)
