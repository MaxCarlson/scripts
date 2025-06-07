# File: knowledge_manager/tui/screens/tasks.py
from pathlib import Path
from typing import Optional, cast, List
import uuid
import os
import subprocess
import logging
from enum import Enum

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import (
    Header, Static, 
    Markdown, ListView, ListItem
)

from ... import task_ops, utils
from ...models import Project, Task, TaskStatus
from ..widgets.lists import TaskList, TaskListItem
from ..widgets.dialogs import InputDialog
from ..widgets.footer import CustomFooter

log = logging.getLogger(__name__)

class TaskViewFilter(Enum):
    ALL = "All"
    TODO = "Todo"
    IN_PROGRESS = "In-Progress"
    DONE = "Done"

class TasksScreen(Screen):
    BINDINGS = [
        Binding("escape", "cancel_or_pop", "Back/Cancel", show=True, priority=True), 
        Binding("ctrl+r", "reload_tasks", "Reload", show=True),
        Binding("a", "add_task_prompt", "Add Task", show=True), 
        Binding("s", "add_subtask_prompt", "Add Subtask", show=True),
        Binding("e", "edit_selected_task", "Edit Details", show=True), 
        Binding("d", "cycle_task_status", "Cycle Status", show=True),
        Binding("f", "cycle_filter", "Filter", show=True),
        Binding("m", "reparent_task", "Move", show=True),
        Binding("delete", "delete_selected_task", "Delete", show=True),
        Binding("v", "toggle_view", "Toggle View", show=True),
    ]
    
    view_mode: reactive[str] = reactive("split")
    task_filter: reactive[TaskViewFilter] = reactive(TaskViewFilter.ALL)
    reparenting_task: reactive[Optional[Task]] = reactive(None)

    def __init__(self, project: Project, **kwargs): 
        super().__init__(**kwargs)
        self.current_project = project

    def compose(self) -> ComposeResult:
        project_name = self.current_project.name if self.current_project else "N/A"
        yield Header(name=f"Tasks: {project_name}")
        with Vertical(id="tasks_view_container"):
            yield Static(f"Tasks in '{project_name}':", classes="view_header", id="task_list_header")
            with VerticalScroll(id="task_list_scroll"): yield TaskList(id="task_list_view")
            yield Static("Details:", classes="view_header", id="task_detail_header") 
            with VerticalScroll(id="task_detail_scroll"):
                yield Markdown("Select a task to see its details.", id="task_detail_markdown")
        yield CustomFooter()

    async def on_mount(self) -> None:
        self.app.selected_project = self.current_project
        await self.reload_tasks_action()
        self.query_one("#task_list_view", TaskList).focus()
    
    def watch_view_mode(self, old_mode: str, new_mode: str) -> None:
        detail_pane = self.query_one("#task_detail_scroll")
        detail_header = self.query_one("#task_detail_header")
        is_split = new_mode == "split"
        detail_pane.display = is_split
        detail_header.display = is_split

    def watch_task_filter(self, old_filter: TaskViewFilter, new_filter: TaskViewFilter) -> None:
        self.run_worker(self.reload_tasks_action)

    def watch_reparenting_task(self, old_task: Optional[Task], new_task: Optional[Task]) -> None:
        """Update footer when entering/leaving reparenting mode."""
        footer = self.query_one(CustomFooter)
        if new_task:
            footer.update(f"[b]REPARENTING[/b] '{new_task.title}'. Select new parent and press [b]m[/b]. Press [b]escape[/b] to cancel.")
        else:
            footer._update_bindings()

    async def action_cancel_or_pop(self) -> None:
        """Custom escape handler to cancel reparenting mode or pop screen."""
        if self.reparenting_task:
            self.reparenting_task = None
        else:
            await self.app.pop_screen()

    async def action_toggle_view(self) -> None:
        self.view_mode = "full" if self.view_mode == "split" else "split"

    async def action_cycle_filter(self) -> None:
        current_idx = list(TaskViewFilter).index(self.task_filter)
        next_idx = (current_idx + 1) % len(TaskViewFilter)
        self.task_filter = list(TaskViewFilter)[next_idx]
        self.notify(f"View filter set to: {self.task_filter.value}")

    async def action_reload_tasks(self) -> None: await self.reload_tasks_action()
    async def reload_tasks_action(self, task_id_to_reselect: Optional[uuid.UUID] = None) -> None:
        task_list_widget: TaskList = self.query_one("#task_list_view", TaskList)
        task_list_header = self.query_one("#task_list_header", Static)

        project_name = self.current_project.name if self.current_project else "N/A"
        filter_text = f" ({self.task_filter.value})" if self.task_filter != TaskViewFilter.ALL else ""
        task_list_header.update(f"Tasks in '{project_name}':{filter_text}")

        self.app.selected_task = None 
        self.query_one("#task_detail_markdown", Markdown).update("Select a task to see its details.")
        
        status_map = {
            TaskViewFilter.TODO: [TaskStatus.TODO],
            TaskViewFilter.IN_PROGRESS: [TaskStatus.IN_PROGRESS],
            TaskViewFilter.DONE: [TaskStatus.DONE],
        }
        active_filter: Optional[List[TaskStatus]] = status_map.get(self.task_filter)

        if self.current_project: 
            await task_list_widget.load_tasks(self.current_project, status_filter=active_filter, base_data_dir=self.app.base_data_dir)
        else: 
            await task_list_widget.load_tasks(None, status_filter=active_filter, base_data_dir=self.app.base_data_dir) 
        
        if task_id_to_reselect:
            new_index_to_highlight: Optional[int] = None
            for idx, item_widget in enumerate(task_list_widget.children):
                if isinstance(item_widget, TaskListItem) and item_widget.task_data and item_widget.task_data.id == task_id_to_reselect:
                    new_index_to_highlight = idx
                    break
            if new_index_to_highlight is not None:
                task_list_widget.index = new_index_to_highlight
        
        task_list_widget.focus(); self.app.bell()

    async def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id == "task_list_view":
            md_viewer = self.query_one("#task_detail_markdown", Markdown)
            item = event.item 
            if isinstance(item, TaskListItem) and item.task_data:
                self.app.selected_task = item.task_data; task = item.task_data
                if task.details_md_path and task.details_md_path.exists():
                    try: content = utils.read_markdown_file(task.details_md_path); md_viewer.update(content or "*No details.*")
                    except Exception as e: md_viewer.update(f"*Error: {e}*")
                else: md_viewer.update("*No details file.*")
            elif item is None: self.app.selected_task = None; md_viewer.update("No task selected.")
    
    async def action_add_task_prompt(self) -> None: 
        if not self.current_project: self.notify(message="No project context.", title="Error", severity="error"); return
        async def cb(title:str):
            if title: 
                try: 
                    nt=task_ops.create_new_task(title,self.current_project.id if self.current_project else None , base_data_dir=self.app.base_data_dir)
                    await self.reload_tasks_action(task_id_to_reselect=nt.id)
                    self.notify(message=f"Task '{nt.title}' added.", title="Task Added")
                except Exception as e: 
                    self.notify(message=f"Error: {e}", title="Error", severity="error")
        await self.app.push_screen(InputDialog(prompt_text="New task title:"), cb)

    async def action_add_subtask_prompt(self) -> None:
        parent_task = self.app.selected_task
        if not parent_task:
            self.notify("No parent task selected.", title="Add Subtask", severity="warning")
            return
        
        async def cb(title: str):
            if title:
                try:
                    new_task = task_ops.create_new_task(
                        title=title,
                        project_identifier=self.current_project.id if self.current_project else None,
                        parent_task_identifier=parent_task.id,
                        base_data_dir=self.app.base_data_dir
                    )
                    await self.reload_tasks_action(task_id_to_reselect=new_task.id)
                    self.notify(f"Subtask '{new_task.title}' added to '{parent_task.title}'.")
                except Exception as e:
                    self.notify(f"Error: {e}", title="Error", severity="error")
        
        await self.app.push_screen(InputDialog(prompt_text=f"New subtask for '{parent_task.title}':"), cb)

    async def action_delete_selected_task(self) -> None:
        task_to_delete = self.app.selected_task
        if not task_to_delete:
            self.notify("No task selected to delete.", title="Delete Task", severity="warning")
            return
            
        async def confirm_cb(confirm_str: str):
            if confirm_str.lower() == "delete":
                try:
                    deleted = task_ops.delete_task_permanently(
                        task_identifier=task_to_delete.id,
                        base_data_dir=self.app.base_data_dir
                    )
                    if deleted:
                        self.notify(f"Task '{task_to_delete.title}' deleted.")
                        await self.reload_tasks_action()
                    else:
                        self.notify("Failed to delete task.", title="Error", severity="error")
                except Exception as e:
                    self.notify(f"Error: {e}", title="Error", severity="error")
        
        await self.app.push_screen(InputDialog(prompt_text=f"Type 'delete' to confirm deleting '{task_to_delete.title}':"), confirm_cb)

    async def action_edit_selected_task(self) -> None: 
        selected_task_obj = self.app.selected_task
        if not selected_task_obj: 
            self.notify(message="No task selected to edit.", title="Edit Task", severity="warning")
            return
        
        task_id_to_edit = selected_task_obj.id 
        original_title_for_notification = selected_task_obj.title
        path_was_initially_none = selected_task_obj.details_md_path is None
        file_path: Optional[Path] = None
        try:
            file_path=task_ops.get_task_file_path(task_id_to_edit, base_data_dir=self.app.base_data_dir, create_if_missing_in_object=True)
        except Exception as e:
            self.notify(message=f"Error getting path: {e}", title="File Path Error", severity="error"); return
        if not file_path: 
            self.notify(message=f"No path for '{original_title_for_notification}'.",title="Error",severity="error"); return
        editor=os.environ.get("EDITOR","nvim")
        with self.app.suspend():
            try: 
                file_path.parent.mkdir(parents=True, exist_ok=True)
                if not file_path.exists(): file_path.touch()
                process = subprocess.run([editor,str(file_path)], check=False)
                if process.returncode != 0: 
                    print(f"Editor '{editor}' exited with code {process.returncode}. File: {file_path}")
                    input("Press Enter to continue...")
            except FileNotFoundError:
                 print(f"Editor '{editor}' not found. Set $EDITOR or install nvim.")
                 input("Press Enter to continue...")
            except Exception as e: 
                 print(f"Editor error: {e}\nFile: {file_path}"); input("Press Enter...")
        
        file_has_meaningful_content_after_edit = False
        if file_path.exists():
            content_after_edit = utils.read_markdown_file(file_path)
            if content_after_edit: file_has_meaningful_content_after_edit = True
        
        if path_was_initially_none and file_has_meaningful_content_after_edit:
            try:
                task_ops.update_task_details_and_status(
                    task_identifier=task_id_to_edit, new_details_md_path=file_path, base_data_dir=self.app.base_data_dir
                )
            except Exception as e:
                log.error(f"Failed to update task DB with new details_md_path: {e}")
                self.notify(f"Warning: Could not save details path for {original_title_for_notification}.", "Warning", severity="warning")
        
        await self.reload_tasks_action(task_id_to_reselect=task_id_to_edit) 
        self.notify(message=f"Refreshed after editing '{original_title_for_notification}'.", title="Edit Complete")

    async def action_cycle_task_status(self) -> None: 
        selected_task = self.app.selected_task
        if not selected_task:
            self.notify(message="No task selected.", title="Task Status", severity="warning"); return
        
        task_id_to_reselect = selected_task.id 
        current_status = selected_task.status
        
        status_cycle = {
            TaskStatus.TODO: TaskStatus.IN_PROGRESS,
            TaskStatus.IN_PROGRESS: TaskStatus.DONE,
            TaskStatus.DONE: TaskStatus.TODO,
        }
        new_status = status_cycle.get(current_status, TaskStatus.TODO)

        try: 
            updated_task = task_ops.mark_task_status(selected_task.id, new_status, base_data_dir=self.app.base_data_dir)
            if updated_task: 
                self.app.selected_task = updated_task
                await self.reload_tasks_action(task_id_to_reselect=task_id_to_reselect)
                self.notify(message=f"Task '{updated_task.title}' marked as {new_status.value}.", title="Status Updated")
            else: 
                self.notify(message="Failed to update task status.", title="Error", severity="error")
        except Exception as e: 
            self.notify(message=f"Error updating status: {e}", title="Error", severity="error")

    async def action_reparent_task(self) -> None:
        highlighted_task = self.app.selected_task
        if not highlighted_task:
            self.app.bell()
            return

        if not self.reparenting_task:
            self.reparenting_task = highlighted_task
            self.notify(f"Reparenting '{highlighted_task.title}'. Select a new parent and press 'm'.")
        else:
            child_task = self.reparenting_task
            parent_task = highlighted_task

            if child_task.id == parent_task.id:
                self.notify("A task cannot be its own parent.", title="Error", severity="error")
                self.reparenting_task = None
                return

            try:
                task_ops.update_task_details_and_status(
                    task_identifier=child_task.id,
                    new_parent_task_identifier=parent_task.id,
                    base_data_dir=self.app.base_data_dir
                )
                self.notify(f"Moved '{child_task.title}' under '{parent_task.title}'.")
            except Exception as e:
                self.notify(f"Error: {e}", title="Reparenting Error", severity="error")
            finally:
                child_id_to_reselect = child_task.id
                self.reparenting_task = None
                await self.reload_tasks_action(task_id_to_reselect=child_id_to_reselect)
