# File: knowledge_manager/tui/widgets/lists.py
from pathlib import Path
from typing import Optional
import logging

from textual.app import App, ComposeResult
from textual.widgets import ListView, ListItem, Label

from ... import project_ops, task_ops
from ...models import Project, Task, TaskStatus

log = logging.getLogger(__name__)

class ProjectListItem(ListItem):
    def __init__(self, project: Project) -> None:
        super().__init__() 
        self.project = project
        self.id = f"project-item-{project.id}" 
    def compose(self) -> ComposeResult:
        yield Label(f"{self.project.name} [{self.project.status.value}]")

class TaskListItem(ListItem): 
    def __init__(self, task_obj: Task) -> None: 
        super().__init__()
        self.task_data: Task = task_obj
        self.id = f"task-item-{task_obj.id}"
    def compose(self) -> ComposeResult: 
        status_icon = "✓" if self.task_data.status == TaskStatus.DONE else ("…" if self.task_data.status == TaskStatus.IN_PROGRESS else "☐")
        due_str = f" (Due: {self.task_data.due_date.strftime('%b %d')})" if self.task_data.due_date else ""
        prio_str = f" P{self.task_data.priority}" if self.task_data.priority != 3 else "" 
        display_string = f"{status_icon} {self.task_data.title}{prio_str}{due_str}"
        yield Label(display_string)

class ProjectList(ListView):
    def compose(self) -> ComposeResult: yield from [] 
    async def load_projects(self, base_data_dir: Optional[Path] = None) -> None:
        await self.query("*").remove()
        self.clear()
        app = self.app
        app.selected_project = None 
        try:
            projects = project_ops.list_all_projects(base_data_dir=base_data_dir)
            if not projects: self.append(ListItem(Label("No projects. (Use buttons or ^P to Add)", classes="message-label")))
            else:
                for project in projects: self.append(ProjectListItem(project))
        except Exception as e: 
            log.exception("Failed to load projects.")
            self.append(ListItem(Label(f"Error: {str(e)[:100]}...", classes="message-label")))
            app.bell()

class TaskList(ListView): 
    def compose(self) -> ComposeResult: yield from []
    async def load_tasks(self, project: Optional[Project], base_data_dir: Optional[Path] = None) -> None:
        await self.query("*").remove()
        self.clear()
        app = self.app
        app.selected_task = None
        if not project: self.append(ListItem(Label("No project selected.", classes="message-label"))); return
        try:
            tasks = task_ops.list_all_tasks(project.id, include_subtasks_of_any_parent=True, base_data_dir=base_data_dir)
            if not tasks: self.append(ListItem(Label(f"No tasks in '{project.name}'. (Use 'Add' button)", classes="message-label")))
            else:
                for task_obj in tasks: self.append(TaskListItem(task_obj))
        except Exception as e: 
            log.exception(f"Failed to load tasks for project {project.id if project else 'None'}.")
            self.append(ListItem(Label(f"Error: {str(e)[:100]}...", classes="message-label")))
            app.bell()
