# File: knowledge_manager/tui.py
from pathlib import Path 
from typing import Optional, List as PyList, cast
import uuid 
import os 
import subprocess 
import logging

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll, Horizontal, Container, HorizontalScroll
from textual.reactive import reactive 
from textual.screen import Screen, ModalScreen 
from textual.widgets import (
    Header, Footer, Static, 
    ListView, ListItem, Label, 
    Markdown, Button, Input
)
from rich.text import Text

from . import project_ops 
from . import task_ops 
from . import utils 
from .models import Project, Task, TaskStatus 

APP_BASE_DATA_DIR: Optional[Path] = None 
log = logging.getLogger(__name__)

# --- List Item Widgets ---
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
        # Use a unique name for the data attribute to avoid conflicts
        self.task_data: Task = task_obj
        self.id = f"task-item-{task_obj.id}"
    
    def compose(self) -> ComposeResult: 
        # Access the data via self.task_data
        status_icon = "✓" if self.task_data.status == TaskStatus.DONE else ("…" if self.task_data.status == TaskStatus.IN_PROGRESS else "☐")
        due_str = f" (Due: {self.task_data.due_date.strftime('%b %d')})" if self.task_data.due_date else ""
        prio_str = f" P{self.task_data.priority}" if self.task_data.priority != 3 else "" 
        display_string = f"{status_icon} {self.task_data.title}{prio_str}{due_str}"
        yield Label(display_string)

# --- List View Widgets ---
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

# --- Input Dialog ---
class InputDialog(ModalScreen[str]):
    DEFAULT_CSS = """
    InputDialog { align: center middle; }
    InputDialog > Vertical { width: 80%; max-width: 60; height: auto; border: thick $primary-background-darken-2; background: $surface; padding: 1 2;}
    InputDialog Input { margin-bottom: 1; border: tall $primary;}
    InputDialog .buttons { width: 100%; align-horizontal: right; padding-top: 1;}
    InputDialog Button { margin-left: 1;}
    """
    def __init__(self, prompt_text: str, initial_value: str = ""): 
        super().__init__()
        self.prompt_text=prompt_text
        self.initial_value=initial_value
    def compose(self) -> ComposeResult:
        with Vertical(): yield Label(self.prompt_text); yield Input(value=self.initial_value, id="text_input_field")
        with Container(classes="buttons"): yield Button("OK", variant="primary", id="ok_button"); yield Button("Cancel", id="cancel_button")
    def on_mount(self) -> None: self.query_one(Input).focus()
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok_button": self.dismiss(self.query_one(Input).value)
        else: self.dismiss("")

# --- Screens ---
class TasksScreen(Screen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True, priority=True), 
        Binding("ctrl+r", "reload_tasks", "Reload", show=True),
        Binding("a", "add_task_prompt", "Add Task", show=False), 
        Binding("e", "edit_selected_task", "Edit Task", show=False), 
        Binding("d", "toggle_selected_task_done", "Done/Todo", show=False), 
    ]
    
    def __init__(self, project: Project, **kwargs): 
        super().__init__(**kwargs)
        self.current_project = project

    def compose(self) -> ComposeResult:
        project_name = self.current_project.name if self.current_project else "N/A"
        yield Header(name=f"Tasks: {project_name}")
        with Vertical(id="tasks_view_container"):
            with HorizontalScroll(id="task_actions_bar"): 
                yield Button("Add (A)", id="btn_add_task", variant="success")
                yield Button("Edit (E)", id="btn_edit_task", variant="primary")
                yield Button("Done/Todo (D)", id="btn_toggle_done", variant="default")
            yield Static(f"Tasks in '{project_name}':", classes="view_header")
            with VerticalScroll(id="task_list_scroll"): yield TaskList(id="task_list_view")
            yield Static("Details:", classes="view_header", id="task_detail_header") 
            with VerticalScroll(id="task_detail_scroll"):
                yield Markdown("Select a task to see its details.", id="task_detail_markdown")
        yield Footer()

    async def on_mount(self) -> None:
        self.app.selected_project = self.current_project
        await self.reload_tasks_action()
        self.query_one("#task_list_view", TaskList).focus()
    
    async def action_reload_tasks(self) -> None: await self.reload_tasks_action()
    async def reload_tasks_action(self, task_id_to_reselect: Optional[uuid.UUID] = None) -> None:
        task_list_widget: TaskList = self.query_one("#task_list_view", TaskList)
        self.app.selected_task = None 
        self.query_one("#task_detail_markdown", Markdown).update("Select a task to see its details.")
        if self.current_project: await task_list_widget.load_tasks(self.current_project, base_data_dir=APP_BASE_DATA_DIR)
        else: await task_list_widget.load_tasks(None, base_data_dir=APP_BASE_DATA_DIR) 
        
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
                if task.details_md_path:
                    try: content = utils.read_markdown_file(task.details_md_path); md_viewer.update(content or "*No details.*")
                    except Exception as e: md_viewer.update(f"*Error: {e}*")
                else: md_viewer.update("*No details file.*")
            elif item is None: self.app.selected_task = None; md_viewer.update("No task selected.")
    
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_add_task": await self.action_add_task_prompt()
        elif event.button.id == "btn_edit_task": await self.action_edit_selected_task()
        elif event.button.id == "btn_toggle_done": await self.action_toggle_selected_task_done()
        event.stop()

    async def action_add_task_prompt(self) -> None: 
        if not self.current_project: self.notify(message="No project context.", title="Error", severity="error"); return
        async def cb(title:str):
            if title: 
                try: 
                    nt=task_ops.create_new_task(title,self.current_project.id if self.current_project else None ,APP_BASE_DATA_DIR)
                    await self.reload_tasks_action(task_id_to_reselect=nt.id)
                    self.notify(message=f"Task '{nt.title}' added.", title="Task Added")
                except Exception as e: 
                    self.notify(message=f"Error: {e}", title="Error", severity="error")
        await self.app.push_screen(InputDialog(prompt_text="New task title:"), cb)

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
            file_path=task_ops.get_task_file_path(task_id_to_edit, APP_BASE_DATA_DIR, True)
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
                    task_identifier=task_id_to_edit, new_details="", base_data_dir=APP_BASE_DATA_DIR
                )
            except Exception as e:
                log.error(f"Failed to update task DB with new details_md_path: {e}")
                self.notify(f"Warning: Could not save details path for {original_title_for_notification}.", "Warning", severity="warning")
        
        await self.reload_tasks_action(task_id_to_reselect=task_id_to_edit) 
        self.notify(message=f"Refreshed after editing '{original_title_for_notification}'.", title="Edit Complete")

    async def action_toggle_selected_task_done(self) -> None: 
        selected_task = self.app.selected_task
        if not selected_task:
            self.notify(message="No task selected.", title="Task Status", severity="warning"); return
        task_id_to_reselect = selected_task.id 
        new_status = TaskStatus.TODO if selected_task.status == TaskStatus.DONE else TaskStatus.DONE
        try: 
            updated_task = task_ops.mark_task_status(selected_task.id, new_status, base_data_dir=APP_BASE_DATA_DIR)
            if updated_task: 
                self.app.selected_task = updated_task
                await self.reload_tasks_action(task_id_to_reselect=task_id_to_reselect)
                self.notify(message=f"Task '{updated_task.title}' marked as {new_status.value}.", title="Status Updated")
            else: 
                self.notify(message="Failed to update task status.", title="Error", severity="error")
        except Exception as e: 
            self.notify(message=f"Error updating status: {e}", title="Error", severity="error")

class ProjectsScreen(Screen): 
    BINDINGS = [
        Binding("ctrl+r", "reload_projects", "Reload", show=True),
        Binding("ctrl+p", "app.add_project_prompt", "Add Project", show=False),
        Binding("e", "edit_selected_project", "Edit Project", show=False),
        Binding("delete", "delete_selected_project", "Delete Project", show=False),
    ]
    def compose(self) -> ComposeResult:
        yield Header(name="KM - Projects")
        with Vertical(id="projects_view_container"):
            with HorizontalScroll(id="project_actions_bar"):
                yield Button("Add (^P)", id="btn_add_project", variant="success")
                yield Button("Edit (E)", id="btn_edit_project", variant="primary")
                yield Button("Delete", id="btn_delete_project", variant="error")
            yield Static("Projects:", classes="view_header")
            with VerticalScroll(id="project_list_scroll"): yield ProjectList(id="project_list_view")
            yield Static("Details:", classes="view_header", id="project_detail_header") 
            with VerticalScroll(id="project_detail_scroll"):
                yield Markdown("Highlight a project for details.", id="project_detail_markdown")
        yield Footer()
    async def on_mount(self) -> None: await self.reload_projects_action(); self.query_one("#project_list_view").focus()
    async def action_reload_projects(self) -> None: await self.reload_projects_action()
    async def reload_projects_action(self) -> None:
        plw = self.query_one(ProjectList); await plw.load_projects(APP_BASE_DATA_DIR)
        self.query_one(Markdown).update("Highlight project for details."); self.app.selected_project=None
        if hasattr(self.app, 'bell'): self.app.bell()
    async def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id == "project_list_view":
            mdv = self.query_one(Markdown)
            item = event.item
            if isinstance(item, ProjectListItem):
                self.app.selected_project = item.project; p = item.project
                if p.description_md_path:
                    try: c=utils.read_markdown_file(p.description_md_path); mdv.update(c or "*No description.*")
                    except Exception as e: mdv.update(f"*Error: {e}*")
                else: mdv.update("*Project has no description file.")
            elif item is None: self.app.selected_project=None; mdv.update("No project selected.")
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_add_project": await self.app.action_add_project_prompt()
        elif event.button.id == "btn_edit_project": await self.action_edit_selected_project()
        elif event.button.id == "btn_delete_project": await self.action_delete_selected_project()
        event.stop()
    async def action_edit_selected_project(self) -> None:
        selected_project = self.app.selected_project
        if not selected_project: self.notify(message="No project selected.", title="Edit Project", severity="warning"); return
        async def cb(new_name: str):
            if new_name and new_name != selected_project.name:
                try:
                    project_ops.update_project_details(selected_project.id, new_name=new_name, base_data_dir=APP_BASE_DATA_DIR)
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
                    project_ops.delete_project_permanently(selected_project.id, base_data_dir=APP_BASE_DATA_DIR)
                    self.notify(message=f"Project '{selected_project.name}' deleted.", title="Project Deleted")
                    await self.reload_projects_action()
                except Exception as e: self.notify(message=f"Error: {e}", title="Error", severity="error")
        await self.app.push_screen(InputDialog(prompt_text=f"This is permanent. Type '{selected_project.name}' to confirm:"), confirm_cb)
    
class KmApp(App[None]): 
    TITLE = "Knowledge Manager (km)"; CSS_PATH = "km_tui.css" 
    SCREENS = {"projects": ProjectsScreen, "tasks": TasksScreen} 
    MODAL_SCREENS = {"input_dialog": InputDialog} 
    selected_project: reactive[Optional[Project]] = reactive(None)
    selected_task: reactive[Optional[Task]] = reactive(None)     
    BINDINGS = [ 
        Binding("q", "quit_or_pop_screen", "Back/Quit", show=True, priority=True),
        Binding("ctrl+p", "add_project_prompt", "Add Proj", show=False), 
    ]
    def on_mount(self) -> None: self.push_screen("projects") 
    def action_quit_or_pop_screen(self) -> None:
        if len(self.screen_stack) > 1: self.pop_screen()
        else: self.exit()
    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "project_list_view":
            item = event.item
            if isinstance(item, ProjectListItem):
                self.selected_project = item.project 
                self.push_screen(TasksScreen(project=item.project)) 
        elif event.list_view.id == "task_list_view":
            item = event.item
            if isinstance(item, TaskListItem) and item.task_data:
                self.selected_task = item.task_data 
                current_screen = self.screen 
                if isinstance(current_screen, TasksScreen): await current_screen.action_edit_selected_task()
    
    async def action_add_project_prompt(self) -> None:
        async def cb(name:str):
            if name:
                try: 
                    new_project=project_ops.create_new_project(name=name, base_data_dir=APP_BASE_DATA_DIR)
                    self.notify(message=f"Project '{new_project.name}' added.", title="Project Added")
                    if isinstance(self.screen, ProjectsScreen): 
                        await self.screen.reload_projects_action()
                except ValueError as ve: 
                    self.notify(message=f"Error: {ve}", title="Add Project Error", severity="error", timeout=5.0)
                except Exception as e: 
                    self.notify(message=f"Error adding project: {e}", title="Error", severity="error")
        await self.app.push_screen(InputDialog(prompt_text="New project name:"), cb)

if __name__ == "__main__":
    import sys
    
    log_file_path = None
    args_to_pass_to_textual = []
    args_to_pass_to_textual.append(sys.argv[0])

    for arg in sys.argv[1:]:
        if arg.startswith("--log-file="):
            log_file_path = Path(arg.split("=", 1)[1])
        elif arg.startswith("--data-dir="):
            try:
                data_dir_str=arg.split("=",1)[1]
                APP_BASE_DATA_DIR=Path(data_dir_str)
                if not APP_BASE_DATA_DIR.is_dir(): 
                    print(f"Error: Data dir not valid: {APP_BASE_DATA_DIR}"); sys.exit(1)
            except Exception as e: 
                print(f"Error parsing --data-dir: {e}"); sys.exit(1)
        else:
            args_to_pass_to_textual.append(arg)
    
    is_dev_mode = "--dev" in args_to_pass_to_textual
    if not is_dev_mode:
        utils.setup_logging(log_file=log_file_path, level=logging.INFO)
    
    main_log = logging.getLogger(__name__)
    main_log.info("KmApp TUI starting up...")

    original_argv = sys.argv
    sys.argv = args_to_pass_to_textual
    app = KmApp(); app.run(); sys.argv = original_argv
