# File: knowledge_manager/tui.py
from pathlib import Path 
from typing import Optional, List as PyList, cast
import uuid 
import os 
import subprocess 

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll, Horizontal, Container
from textual.css.query import DOMQuery
from textual.reactive import reactive 
from textual.screen import Screen, ModalScreen 
from textual.widgets import (
    Header, Footer, Static, 
    ListView, ListItem, Label, 
    Markdown, Button, Input, Placeholder
)
from textual import log # For debugging

from . import project_ops 
from . import task_ops 
from . import utils 
from .models import Project, Task, TaskStatus 

APP_BASE_DATA_DIR: Optional[Path] = None 

# --- List Item Widgets ---
class ProjectListItem(ListItem):
    def __init__(self, project: Project) -> None:
        super().__init__(classes="project_list_item") 
        self.project = project
        self.id = f"project-item-{project.id}" 
    def compose(self) -> ComposeResult:
        yield Label(f"{self.project.name} [{self.project.status.value}]")

class TaskListItem(ListItem): 
    def __init__(self, task: Task) -> None:
        super().__init__(classes="task_list_item")
        self.task = task
        self.id = f"task-item-{task.id}"
    def compose(self) -> ComposeResult:
        status_icon = "✓" if self.task.status == TaskStatus.DONE else ("…" if self.task.status == TaskStatus.IN_PROGRESS else "☐")
        due_str = f" (Due: {self.task.due_date.strftime('%b %d')})" if self.task.due_date else ""
        prio_str = f" P{self.task.priority}" if self.task.priority != 3 else "" 
        yield Label(f"{status_icon} {self.task.title}{prio_str}{due_str}")

# --- List View Widgets ---
class ProjectList(ListView):
    def compose(self) -> ComposeResult: yield from [] 
    def load_projects(self, base_data_dir: Optional[Path] = None) -> None:
        self.clear()
        app_instance = self.app if hasattr(self, 'app') else App.get_running_app()
        if app_instance: app_instance.selected_project = None 
        try:
            projects = project_ops.list_all_projects(base_data_dir=base_data_dir)
            if not projects: self.append(ListItem(Label("No projects found. (Add via CLI or future TUI action)", classes="message-label")))
            else:
                for project in projects: self.append(ProjectListItem(project))
        except Exception as e:
            self.append(ListItem(Label(f"Error: {str(e)[:100]}...", classes="message-label"))) 
            if app_instance and hasattr(app_instance, 'bell'): app_instance.bell()

class TaskList(ListView): 
    def compose(self) -> ComposeResult: yield from []
    def load_tasks(self, project: Optional[Project], base_data_dir: Optional[Path] = None) -> None:
        self.clear()
        app_instance = self.app if hasattr(self, 'app') else App.get_running_app()
        if app_instance: app_instance.selected_task = None
        if not project:
            self.append(ListItem(Label("No project selected.", classes="message-label")))
            return
        try:
            tasks = task_ops.list_all_tasks(
                project_identifier=project.id, 
                include_subtasks_of_any_parent=True, 
                base_data_dir=base_data_dir
            )
            if not tasks: self.append(ListItem(Label(f"No tasks in project '{project.name}'. Press (a) to add.", classes="message-label")))
            else:
                for task in tasks: self.append(TaskListItem(task))
        except Exception as e:
            self.append(ListItem(Label(f"Error: {str(e)[:100]}...", classes="message-label")))
            if app_instance and hasattr(app_instance, 'bell'): app_instance.bell()

# --- Input Dialog (ModalScreen) ---
class InputDialog(ModalScreen[str]):
    DEFAULT_CSS = """
    InputDialog { align: center middle; }
    InputDialog > Vertical { width: 80%; max-width: 60; height: auto; border: thick $primary-background-darken-2; background: $surface; padding: 1 2;}
    InputDialog Input { margin-bottom: 1; border: tall $primary;}
    InputDialog .buttons { width: 100%; align-horizontal: right; padding-top: 1;}
    InputDialog Button { margin-left: 1;}
    """
    def __init__(self, prompt_text: str, initial_value: str = "") -> None: # Renamed prompt to prompt_text
        super().__init__()
        self.prompt_text = prompt_text
        self.initial_value = initial_value
    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.prompt_text)
            yield Input(value=self.initial_value, id="text_input_field")
            with Container(classes="buttons"):
                yield Button("OK", variant="primary", id="ok_button")
                yield Button("Cancel", id="cancel_button")
    def on_mount(self) -> None: self.query_one(Input).focus()
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok_button": self.dismiss(self.query_one(Input).value)
        else: self.dismiss("")

# --- Screens ---
class TasksScreen(Screen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back to Projects", show=True, priority=True),
        Binding("ctrl+r", "reload_tasks", "Reload Tasks", show=True),
        Binding("a", "add_task_prompt", "Add Task", show=True),
        Binding("e", "edit_selected_task", "Edit Task", show=True),
        Binding("d", "toggle_selected_task_done", "Done/Undone", show=True),
    ]

    current_project: reactive[Optional[Project]] = reactive(None)

    def __init__(self, project: Project, name: Optional[str] = None, id: Optional[str] = None, classes: Optional[str] = None):
        super().__init__(name=name, id=id, classes=classes)
        self.current_project = project
        # self.app.selected_project = project # App-level selected_project is set by KmApp when pushing

    def compose(self) -> ComposeResult:
        project_name = self.current_project.name if self.current_project else "N/A"
        yield Header(name=f"Tasks for Project: {project_name}")
        with Vertical(id="tasks_view_container"):
            yield Static(f"Tasks in '{project_name}':", classes="view_header")
            with VerticalScroll(id="task_list_scroll"):
                yield TaskList(id="task_list_view") # Ensure this ID is unique if ProjectsScreen also has one
            yield Static("Task Details:", classes="view_header", id="task_detail_header")
            with VerticalScroll(id="task_detail_scroll"):
                yield Markdown("Select a task to see its details.", id="task_detail_markdown")
        yield Footer()

    def on_mount(self) -> None:
        self.app.selected_project = self.current_project # Ensure app knows current project
        self.reload_tasks_action()
        self.query_one("#task_list_view", TaskList).focus()
    
    def action_reload_tasks(self) -> None: self.reload_tasks_action()
    def reload_tasks_action(self) -> None:
        task_list_widget: TaskList = self.query_one("#task_list_view", TaskList)
        if self.current_project:
            task_list_widget.load_tasks(self.current_project, base_data_dir=APP_BASE_DATA_DIR)
        else: 
            task_list_widget.load_tasks(None, base_data_dir=APP_BASE_DATA_DIR) 
        self.query_one("#task_detail_markdown", Markdown).update("Select a task to see its details.")
        self.app.selected_task = None 
        self.app.bell()

    async def on_list_view_highlighted(self, event: ListView.Highlighted) -> None: # Renamed from on_list_view_selected
        """Called when an item in the TaskList is highlighted."""
        if event.list_view.id == "task_list_view": # Ensure this is from the task list
            markdown_viewer = self.query_one("#task_detail_markdown", Markdown)
            if isinstance(event.item, TaskListItem):
                self.app.selected_task = event.item.task 
                task = event.item.task
                if task.details_md_path:
                    try:
                        content = utils.read_markdown_file(task.details_md_path)
                        markdown_viewer.update(content or "*No task details content.*")
                    except Exception as e: markdown_viewer.update(f"*Error loading details: {e}*")
                else: markdown_viewer.update("*Task has no details file.*")
            elif event.item is None: # No item highlighted
                 self.app.selected_task = None
                 markdown_viewer.update("No task selected.")
    
    async def action_add_task_prompt(self) -> None:
        if not self.current_project: 
            self.notify("Cannot add task: No current project context.", title="Error", severity="error")
            return
        def set_new_task_title(title: str) -> None:
            if title: 
                try:
                    new_task = task_ops.create_new_task(
                        title=title, project_identifier=self.current_project.id,
                        base_data_dir=APP_BASE_DATA_DIR
                    )
                    self.reload_tasks_action()
                    self.notify(f"Task '{new_task.title}' added.", title="Task Added")
                except Exception as e:
                    self.notify(f"Error adding task: {e}", title="Error", severity="error")
        await self.app.push_screen(InputDialog(prompt_text="New task title:"), set_new_task_title)

    async def action_edit_selected_task(self) -> None:
        selected_task = self.app.selected_task 
        if not selected_task:
            self.notify("No task selected to edit.", title="Edit Task", severity="warning"); return
        file_path = task_ops.get_task_file_path(
            selected_task.id, base_data_dir=APP_BASE_DATA_DIR, create_if_missing_in_object=True
        )
        if not file_path:
            self.notify(f"Could not get file path for '{selected_task.title}'.", title="Error", severity="error"); return
        editor = os.environ.get("EDITOR", "nvim")
        with self.app.suspend():
            try: subprocess.run([editor, str(file_path)], check=True)
            except Exception as e:
                 print(f"Error with editor '{editor}': {e}\nFile was: {file_path}"); input("Press Enter...")
        self.reload_tasks_action() 
        self.notify(f"Refreshed after editing '{selected_task.title}'.", title="Edit Complete")

    async def action_toggle_selected_task_done(self) -> None:
        selected_task = self.app.selected_task
        if not selected_task:
            self.notify("No task selected.", title="Task Status", severity="warning"); return
        new_status = TaskStatus.TODO if selected_task.status == TaskStatus.DONE else TaskStatus.DONE
        try:
            updated_task = task_ops.mark_task_status(
                selected_task.id, new_status, base_data_dir=APP_BASE_DATA_DIR
            )
            if updated_task:
                self.reload_tasks_action()
                self.notify(f"Task '{updated_task.title}' marked as {new_status.value}.", title="Status Updated")
                self.app.selected_task = updated_task 
            else: self.notify("Failed to update task status.", title="Error", severity="error")
        except Exception as e: self.notify(f"Error updating status: {e}", title="Error", severity="error")

class ProjectsScreen(Screen):
    BINDINGS = [
        Binding("ctrl+r", "reload_projects", "Reload Projects", show=True),
        # ("enter", "select_project", "View Tasks", show=True), # REMOVED - use ListView.Selected
    ]
    # highlighted_project_item: reactive[Optional[ProjectListItem]] = reactive(None) # Using app.selected_project

    def compose(self) -> ComposeResult:
        yield Header(name="Knowledge Manager (km) - Projects")
        with Vertical(id="projects_view_container"):
            yield Static("Projects:", classes="view_header")
            with VerticalScroll(id="project_list_scroll"):
                yield ProjectList(id="project_list_view")
            yield Static("Project Details:", classes="view_header", id="project_detail_header")
            with VerticalScroll(id="project_detail_scroll"):
                yield Markdown("Highlight a project to see its description.", id="project_detail_markdown")
        yield Footer()

    def on_mount(self) -> None:
        self.reload_projects_action() 
        self.query_one("#project_list_view", ProjectList).focus()

    def action_reload_projects(self) -> None: self.reload_projects_action()
    def reload_projects_action(self) -> None:
        project_list_widget: ProjectList = self.query_one("#project_list_view", ProjectList)
        project_list_widget.load_projects(base_data_dir=APP_BASE_DATA_DIR)
        self.query_one("#project_detail_markdown", Markdown).update("Highlight a project to see its description.")
        self.app.selected_project = None 
        if hasattr(self.app, 'bell'): self.app.bell()

    async def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """When a project item is highlighted, update app state and detail view."""
        if event.list_view.id == "project_list_view":
            markdown_viewer = self.query_one("#project_detail_markdown", Markdown)
            if isinstance(event.item, ProjectListItem):
                self.app.selected_project = event.item.project 
                project = event.item.project
                if project.description_md_path:
                    try:
                        content = utils.read_markdown_file(project.description_md_path)
                        markdown_viewer.update(content or "*No description content.*")
                    except Exception as e: markdown_viewer.update(f"*Error loading description: {e}*")
                else: markdown_viewer.update("*Project has no description file.*")
            elif event.item is None:
                 self.app.selected_project = None
                 markdown_viewer.update("No project selected.")
    
    # Note: action_select_project was removed. Selection is handled by KmApp.on_list_view_selected

class KmApp(App[None]): 
    TITLE = "Knowledge Manager (km)"
    CSS_PATH = "km_tui.css" 
    SCREENS = {
        "projects_screen": ProjectsScreen, 
        "tasks_screen": TasksScreen,
    }
    MODAL_SCREENS = {"input_dialog": InputDialog} 

    selected_project: reactive[Optional[Project]] = reactive(None)
    selected_task: reactive[Optional[Task]] = reactive(None)     

    BINDINGS = [ 
        Binding("q", "quit_or_pop_screen", "Back/Quit", show=True, priority=True),
    ]

    def on_mount(self) -> None:
        self.push_screen(ProjectsScreen())

    def action_quit_or_pop_screen(self) -> None:
        if len(self.screen_stack) > 1:
            self.pop_screen()
        else:
            self.exit()

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Called when an item in ANY ListView is selected (Enter pressed)."""
        # log(f"ListView.Selected event from: {event.list_view.id}, item: {event.item}") # Debugging
        if event.list_view.id == "project_list_view":
            if isinstance(event.item, ProjectListItem):
                selected_project = event.item.project
                self.selected_project = selected_project # Update app-level selected project
                self.push_screen(TasksScreen(project=selected_project))
        # Add handling for task selection if needed here, e.g., to open editor directly on Enter
        # elif event.list_view.id == "task_list_view":
        #     if isinstance(event.item, TaskListItem) and self.query_one(TasksScreen, TasksScreen).is_current:
        #         tasks_screen = self.query_one(TasksScreen)
        #         await tasks_screen.action_edit_selected_task()


if __name__ == "__main__":
    import sys
    data_dir_override = None
    args_to_pass_to_textual = []
    for arg in sys.argv[1:]:
        if arg.startswith("--data-dir="):
            try:
                data_dir_str = arg.split("=", 1)[1]
                data_dir_override = Path(data_dir_str)
                if not data_dir_override.is_dir():
                    print(f"Error: Specified data directory is not a valid directory: {data_dir_override}")
                    sys.exit(1)
            except Exception as e:
                print(f"Error: Could not parse --data-dir argument: {e}")
                sys.exit(1)
        else:
            args_to_pass_to_textual.append(arg)

    APP_BASE_DATA_DIR = data_dir_override 
    original_argv = sys.argv
    sys.argv = [original_argv[0]] + args_to_pass_to_textual
    app = KmApp()
    app.run()
    sys.argv = original_argv
