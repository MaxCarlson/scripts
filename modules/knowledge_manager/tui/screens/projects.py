# File: knowledge_manager/tui/screens/projects.py
from pathlib import Path
from typing import Optional
import logging

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll, HorizontalScroll
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Markdown, Button, ListView
from textual.reactive import reactive

from ... import project_ops, task_ops, utils
from ...models import Project
from ..widgets.lists import ProjectList, ProjectListItem
from ..widgets.dialogs import InputDialog
from .tasks import TasksScreen 

log = logging.getLogger(__name__)

class ProjectsScreen(Screen): 
    BINDINGS = [
        Binding("ctrl+r", "reload_projects", "Reload", show=True),
        Binding("ctrl+p", "app.add_project_prompt", "Add Project", show=False),
        Binding("e", "edit_selected_project", "Edit Project", show=False),
        Binding("delete", "delete_selected_project", "Delete Project", show=False),
        Binding("t", "toggle_detail_view", "Toggle Details", show=False), # For toggle button
    ]

    # Reactive variable to control what's shown in the detail pane
    detail_view_mode: reactive[str] = reactive("description")

    def compose(self) -> ComposeResult:
        yield Header(name="KM - Projects")
        with Vertical(id="projects_view_container"):
            with HorizontalScroll(id="project_actions_bar"):
                yield Button("Add (^P)", id="btn_add_project", variant="success")
                yield Button("Edit (E)", id="btn_edit_project", variant="primary")
                yield Button("Delete", id="btn_delete_project", variant="error")
                yield Button("Tasks/Desc (T)", id="btn_toggle_details") # New Toggle Button
            yield Static("Projects:", classes="view_header")
            with VerticalScroll(id="project_list_scroll"): yield ProjectList(id="project_list_view")
            yield Static("Details:", classes="view_header", id="project_detail_header") 
            with VerticalScroll(id="project_detail_scroll"):
                yield Markdown("Highlight a project for details.", id="project_detail_markdown")
        yield Footer()

    async def on_mount(self) -> None: 
        await self.reload_projects_action()
        self.query_one("#project_list_view").focus()

    async def action_reload_projects(self) -> None: 
        await self.reload_projects_action()

    async def reload_projects_action(self) -> None:
        plw = self.query_one(ProjectList)
        await plw.load_projects(self.app.base_data_dir)
        self.query_one(Markdown).update("Highlight project for details.")
        self.app.selected_project = None
        if hasattr(self.app, 'bell'): self.app.bell()

    async def _update_detail_view(self) -> None:
        """Helper to refresh the detail view based on current mode and selection."""
        project = self.app.selected_project
        mdv = self.query_one(Markdown)
        
        if not project:
            mdv.update("No project selected.")
            return

        # Show description if in that mode
        if self.detail_view_mode == "description":
            self.query_one("#project_detail_header", Static).update("Project Details:")
            if project.description_md_path:
                try: 
                    content = utils.read_markdown_file(project.description_md_path)
                    mdv.update(content or "*Description file is empty.*")
                except Exception as e: 
                    mdv.update(f"*Error loading description: {e}*")
            else:
                mdv.update("*Project has no description file.*\n\n(Press 'T' to view tasks)")
        
        # Show task list if in that mode
        elif self.detail_view_mode == "tasks":
            self.query_one("#project_detail_header", Static).update("Top Tasks:")
            try:
                tasks = task_ops.list_all_tasks(
                    project_identifier=project.id,
                    base_data_dir=self.app.base_data_dir,
                    # For now, just get all tasks, could limit later
                )
                if not tasks:
                    mdv.update("*No tasks in this project.*")
                else:
                    # Format tasks as a markdown list
                    task_list_md = "\n".join([f"* {t.title} `[{t.status.value}]`" for t in tasks])
                    mdv.update(task_list_md)
            except Exception as e:
                mdv.update(f"*Error loading tasks: {e}*")

    async def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id == "project_list_view":
            item = event.item
            if isinstance(item, ProjectListItem):
                self.app.selected_project = item.project
                # If there's no description, default to showing tasks instead.
                if not item.project.description_md_path:
                    self.detail_view_mode = "tasks"
                else:
                    self.detail_view_mode = "description"
            else:
                self.app.selected_project = None
                await self._update_detail_view() # Clear view if no project selected

    # This is a "watch" method that automatically runs when self.detail_view_mode changes
    async def watch_detail_view_mode(self, old_mode: str, new_mode: str) -> None:
        await self._update_detail_view()

    # This is a "watch" method for the app-level selected_project
    async def watch_selected_project(self, old_project: Optional[Project], new_project: Optional[Project]) -> None:
        # This is triggered from the main app when self.app.selected_project changes.
        # We need to ensure this screen is active before updating its UI.
        if self.app.screen is self:
            await self._update_detail_view()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_add_project": await self.app.action_add_project_prompt()
        elif event.button.id == "btn_edit_project": await self.action_edit_selected_project()
        elif event.button.id == "btn_delete_project": await self.action_delete_selected_project()
        elif event.button.id == "btn_toggle_details": await self.action_toggle_detail_view()
        event.stop()

    async def action_toggle_detail_view(self) -> None:
        """Toggle between description and task list in the detail pane."""
        if self.detail_view_mode == "description":
            self.detail_view_mode = "tasks"
        else:
            self.detail_view_mode = "description"

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
            if name_check.lower() == selected_project.name.lower():
                try:
                    project_ops.delete_project_permanently(selected_project.id, base_data_dir=self.app.base_data_dir)
                    self.notify(message=f"Project '{selected_project.name}' deleted.", title="Project Deleted")
                    await self.reload_projects_action()
                except Exception as e: self.notify(message=f"Error: {e}", title="Error", severity="error")
        await self.app.push_screen(InputDialog(prompt_text=f"This is permanent. Type '{selected_project.name}' to confirm:"), confirm_cb)
