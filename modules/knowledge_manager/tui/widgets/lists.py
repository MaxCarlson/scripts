# File: knowledge_manager/tui/widgets/lists.py
from pathlib import Path
from typing import Optional, List as PyList
import logging
import uuid
import re

from textual.app import App, ComposeResult
from textual.widgets import ListView, ListItem, Label

from ... import project_ops, task_ops, links
from ...models import Project, Task, TaskStatus

log = logging.getLogger(__name__)

def _format_title_with_links(title: str) -> str:
    """Format task title with blue @mentions using Rich markup."""
    # Use the existing PROJECT_LINK_PATTERN from links module
    def replace_mention(match):
        # Get the full match including @
        full_match = match.group(0)
        return f"[blue]{full_match}[/blue]"

    return links.PROJECT_LINK_PATTERN.sub(replace_mention, title)

class ProjectListItem(ListItem):
    def __init__(self, project: Project) -> None:
        super().__init__() 
        self.project = project
        self.id = f"project-item-{project.id}" 
    def compose(self) -> ComposeResult:
        yield Label(f"{self.project.name} [{self.project.status.value}]", classes="list-item-label")

class TaskListItem(ListItem):
    def __init__(self, task_obj: Task, level: int = 0) -> None:
        super().__init__()
        self.task_data: Task = task_obj
        self.level = level
        self.id = f"task-item-{task_obj.id}"
    def compose(self) -> ComposeResult:
        indent = "  " * self.level
        status_icon = "✓" if self.task_data.status == TaskStatus.DONE else ("…" if self.task_data.status == TaskStatus.IN_PROGRESS else "☐")
        due_str = f" (Due: {self.task_data.due_date.strftime('%b %d')})" if self.task_data.due_date else ""
        prio_str = f" P{self.task_data.priority}" if self.task_data.priority != 3 else ""

        # Format title with blue @mentions
        formatted_title = _format_title_with_links(self.task_data.title)
        display_string = f"{indent}{status_icon} {formatted_title}{prio_str}{due_str}"

        # Enable Rich markup so [blue]...[/blue] renders correctly
        yield Label(display_string, classes="list-item-label", markup=True)

class ProjectList(ListView):
    def compose(self) -> ComposeResult: yield from [] 
    async def load_projects(self, base_data_dir: Optional[Path] = None) -> None:
        await self.query("*").remove()
        self.clear()
        app = self.app
        app.selected_project = None 
        try:
            projects = project_ops.list_all_projects(base_data_dir=base_data_dir)
            if not projects: self.append(ListItem(Label("No projects. (Use 'a' to Add)", classes="message-label")))
            else:
                for project in projects: self.append(ProjectListItem(project))
        except Exception as e: 
            log.exception("Failed to load projects.")
            self.append(ListItem(Label(f"Error: {str(e)[:100]}...", classes="message-label")))
            app.bell()

class TaskList(ListView): 
    def compose(self) -> ComposeResult: yield from []
    async def load_tasks(self, project: Optional[Project], status_filter: Optional[PyList[TaskStatus]] = None, base_data_dir: Optional[Path] = None) -> None:
        await self.query("*").remove()
        self.clear()
        app = self.app
        app.selected_task = None
        if not project:
            self.append(ListItem(Label("No project selected.", classes="message-label")))
            return
        
        try:
            all_tasks = task_ops.list_all_tasks(
                project.id, 
                include_subtasks_of_any_parent=True,
                base_data_dir=base_data_dir
            )
            if not all_tasks:
                self.append(ListItem(Label(f"No tasks in '{project.name}'. (Use 'a' to Add)", classes="message-label")))
                return

            tasks_by_id = {task.id: task for task in all_tasks}
            tasks_to_render = all_tasks

            if status_filter:
                matching_ids = {task.id for task in all_tasks if task.status in status_filter}
                
                final_ids_to_show = set(matching_ids)
                for task_id in matching_ids:
                    current_task = tasks_by_id.get(task_id)
                    while current_task and current_task.parent_task_id:
                        final_ids_to_show.add(current_task.parent_task_id)
                        current_task = tasks_by_id.get(current_task.parent_task_id)
                
                tasks_to_render = [task for task in all_tasks if task.id in final_ids_to_show]

            children_by_parent = {}
            root_tasks = []
            
            tasks_to_render_ids = {task.id for task in tasks_to_render}

            for task in tasks_to_render:
                if task.parent_task_id is None or task.parent_task_id not in tasks_to_render_ids:
                    root_tasks.append(task)
                
                if task.id in tasks_to_render_ids:
                    children_by_parent[task.id] = [
                        child for child in all_tasks 
                        if child.parent_task_id == task.id and child.id in tasks_to_render_ids
                    ]

            def add_items_recursively(tasks_to_add: PyList[Task], level: int):
                for task in tasks_to_add:
                    self.append(TaskListItem(task, level=level))
                    children = children_by_parent.get(task.id, [])
                    if children:
                        add_items_recursively(children, level + 1)

            add_items_recursively(root_tasks, 0)

        except Exception as e: 
            log.exception(f"Failed to load tasks for project {project.id if project else 'None'}.")
            self.append(ListItem(Label(f"Error: {str(e)[:100]}...", classes="message-label")))
            app.bell()
