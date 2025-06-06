# File: knowledge_manager/tui/app.py
from pathlib import Path
from typing import Optional
import sys
import logging

from textual.app import App
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import ListView 

from .. import project_ops, utils
from ..models import Project, Task
from .screens.projects import ProjectsScreen
from .screens.tasks import TasksScreen
from .widgets.dialogs import InputDialog
from .widgets.lists import ProjectListItem, TaskListItem

class KmApp(App[None]): 
    TITLE = "Knowledge Manager (km)"; CSS_PATH = "km_tui.css" 
    SCREENS = {"projects": ProjectsScreen, "tasks": TasksScreen} 
    MODAL_SCREENS = {"input_dialog": InputDialog} 
    
    base_data_dir: Optional[Path] = None 
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
                    new_project=project_ops.create_new_project(name=name, base_data_dir=self.base_data_dir)
                    self.notify(message=f"Project '{new_project.name}' added.", title="Project Added")
                    if isinstance(self.screen, ProjectsScreen): 
                        await self.screen.reload_projects_action()
                except ValueError as ve: 
                    self.notify(message=f"Error: {ve}", title="Add Project Error", severity="error", timeout=5.0)
                except Exception as e: 
                    self.notify(message=f"Error adding project: {e}", title="Error", severity="error")
        await self.app.push_screen(InputDialog(prompt_text="New project name:"), cb)

def main():
    log_file_path = None
    data_dir_override = None
    args_to_pass_to_textual = []
    args_to_pass_to_textual.append(sys.argv[0])

    for arg in sys.argv[1:]:
        if arg.startswith("--log-file="):
            log_file_path = Path(arg.split("=", 1)[1])
        elif arg.startswith("--data-dir="):
            try:
                data_dir_str=arg.split("=",1)[1]
                data_dir_override=Path(data_dir_str)
                if not data_dir_override.is_dir(): 
                    print(f"Error: Data dir not valid: {data_dir_override}"); sys.exit(1)
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
    app = KmApp()
    app.base_data_dir = data_dir_override 
    app.run()
    sys.argv = original_argv

if __name__ == "__main__":
    main()
