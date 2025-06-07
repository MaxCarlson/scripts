# File: knowledge_manager/tui/screens/projects.py
from pathlib import Path
from typing import Optional, List as PyList
import logging

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Header, Static, Markdown, ListView
from textual.reactive import reactive

from ... import project_ops, task_ops, utils
from ...models import Project, Task, TaskStatus
from ..widgets.lists import ProjectList, ProjectListItem
from ..widgets.dialogs import InputDialog
from ..widgets.footer import CustomFooter
from .tasks import TasksScreen 

log = logging.getLogger(__name__)

class ProjectsScreen(Screen): 
    BINDINGS = [
        Binding("a", "add_project_prompt", "Add", show=True),
        Binding("e", "edit_selected_project", "Edit", show=True),
        Binding("v", "toggle_detail_view", "View", show=True),
        Binding("ctrl+x", "delete_selected_project", "Delete", show=True),
        Binding("ctrl+r", "reload_projects", "Reload", show=True),
        Binding("q", "app.quit", "Quit", show=True),
    ]

    detail_view_mode: reactive[str] = reactive("tasks")

    def compose(self) -> ComposeResult:
        yield Header(name="KM - Projects")
        with Vertical(id="projects_view_container"):
            yield Static("Projects:", classes="view_header")
            with VerticalScroll(id="project_list_scroll"): yield ProjectList(id="project_list_view")
            yield Static("Details:", classes="view_header", id="project_detail_header") 
            with VerticalScroll(id="project_detail_scroll"):
                yield Markdown("Highlight a project for details.", id="project_detail_markdown")
        yield CustomFooter()

    async def on_mount(self) -> None: 
        await self.reload_projects_action()
        self.query_one("#project_list_view").focus()

    async def action_add_project_prompt(self) -> None:
        """Callback for the 'Add' keybinding."""
        await self.app.action_add_project_prompt()

    async def action_reload_projects(self) -> None: 
        await self.reload_projects_action()

    async def reload_projects_action(self) -> None:
        plw = self.query_one(ProjectList)
        highlighted_project_id = self.app.selected_project.id if self.app.selected_project else None
        
        await plw.load_projects(self.app.base_data_dir)
        
        if len(plw.children) > 0 and isinstance(plw.children[0], ProjectListItem):
            new_index_to_highlight = 0
            if highlighted_project_id:
                for idx, item_widget in enumerate(plw.children):
                    if isinstance(item_widget, ProjectListItem) and item_widget.project.id == highlighted_project_id:
                        new_index_to_highlight = idx
                        break
            plw.index = new_index_to_highlight
        else:
            self.app.selected_project = None
            mdv = self.query_one("#project_detail_markdown", Markdown)
            mdv.update("No project selected.")

        if hasattr(self.app, 'bell'): self.app.bell()

    async def _update_detail_view(self) -> None:
        project = self.app.selected_project
        mdv = self.query_one("#project_detail_markdown", Markdown)
        detail_header = self.query_one("#project_detail_header", Static)
        
        if not project:
            mdv.update("No project selected.")
            detail_header.update("Details:")
            return

        if self.detail_view_mode == "description":
            detail_header.update("Project Details:")
            if project.description_md_path and project.description_md_path.exists():
                try: 
                    content = utils.read_markdown_file(project.description_md_path)
                    mdv.update(content or "*Description file is empty.*")
                except Exception as e: 
                    mdv.update(f"*Error loading description: {e}*")
            else:
                mdv.update("*Project has no description file.*\n\n(Press 'V' to view tasks)")
        
        elif self.detail_view_mode == "tasks":
            detail_header.update("Project Tasks:")
            try:
                tasks = task_ops.list_all_tasks(
                    project_identifier=project.id,
                    include_subtasks_of_any_parent=True,
                    base_data_dir=self.app.base_data_dir,
                )
                if not tasks:
                    mdv.update("*No tasks in this project.*")
                else:
                    tasks_by_id = {task.id: task for task in tasks}
                    children_by_parent = {}
                    root_tasks = []
                    for task in tasks:
                        if task.parent_task_id:
                            children_by_parent.setdefault(task.parent_task_id, []).append(task)
                        else:
                            root_tasks.append(task)

                    md_lines = []
                    def build_md_recursively(tasks_to_render: PyList[Task], level: int):
                        for task in tasks_to_render:
                            indent = "  " * level
                            status_icon = "✓" if task.status == TaskStatus.DONE else ("…" if task.status == TaskStatus.IN_PROGRESS else "☐")
                            md_lines.append(f"{indent}* {status_icon} {task.title} `[{task.status.value}]`")
                            child_tasks = children_by_parent.get(task.id, [])
                            if child_tasks:
                                build_md_recursively(child_tasks, level + 1)
                    
                    build_md_recursively(root_tasks, 0)
                    mdv.update("\n".join(md_lines))

            except Exception as e:
                mdv.update(f"*Error loading tasks: {e}*")

    async def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id == "project_list_view":
            item = event.item
            if isinstance(item, ProjectListItem):
                self.app.selected_project = item.project
                await self._update_detail_view()
            else:
                self.app.selected_project = None
                await self._update_detail_view()

    async def watch_detail_view_mode(self, old_mode: str, new_mode: str) -> None:
        if self.app.screen is self:
            await self._update_detail_view()

    async def action_toggle_detail_view(self) -> None:
        if self.app.selected_project is None:
            self.app.bell()
            return
        self.detail_view_mode = "tasks" if self.detail_view_mode == "description" else "description"

    async def action_edit_selected_project(self) -> None:
        selected_project = self.app.selected_project
        if not selected_project: self.notify(message="No project selected.", title="Edit Project", severity="warning"); return
        async def cb(new_name: str):
            if new_name and new_name != selected_project.name:
                try:
                    project_ops.update_project_details(selected_project.id, new_name=new_name, base_data_dir=self.app.base_data_dir)
                    self.notify(message=f"Renamed to '{new_name}'.", title="Project Updated")
                    await self.reload_projects_action()
                except Exception as e: self.notify(message=f"Error: {e}", title="Error", severity="error")
        await self.app.push_screen(InputDialog(prompt_text="New project name:", initial_value=selected_project.name), cb)
    
    async def action_delete_selected_project(self) -> None:
        selected_project = self.app.selected_project
        if not selected_project: self.notify(message="No project selected.", title="Delete Project", severity="warning"); return
        async def confirm_cb(name_check: str):
            if name_check.lower() == "delete":
                try:
                    project_ops.delete_project_permanently(selected_project.id, base_data_dir=self.app.base_data_dir)
                    self.notify(message=f"Project '{selected_project.name}' deleted.", title="Project Deleted")
                    await self.reload_projects_action()
                except Exception as e: self.notify(message=f"Error: {e}", title="Error", severity="error")
        await self.app.push_screen(InputDialog(prompt_text=f"This is permanent. Type 'delete' to confirm:"), confirm_cb)
