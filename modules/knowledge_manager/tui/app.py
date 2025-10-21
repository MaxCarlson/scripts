#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Knowledge Manager Textual TUI launcher.

Adds:
- q           → back (pop screen) or quit when at root
- Ctrl+Q      → quit immediately
- Ctrl+P      → print the current project's full task hierarchy to stdout after exit
- --project X → start focused on a project (UUID or name); also reads $KM_OPEN_PROJECT_ID
- -G / --data-dir → override KM base data dir; also reads $KM_BASE_DATA_DIR
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Iterable, List, Dict
import sys
import os
import uuid
import logging

from textual.app import App
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import ListView

from .. import project_ops, task_ops, utils
from ..models import Project, Task, TaskStatus
from .screens.projects import ProjectsScreen
from .screens.tasks import TasksScreen
from .widgets.dialogs import InputDialog

# For footer "button" visibility, we expose bindings at the app level.
APP_BINDINGS = [
    Binding("q", "back_or_quit", "Back", show=True, priority=True),
    Binding("ctrl+q", "quit", "Quit", show=True, priority=True),
    Binding("ctrl+p", "print_project_and_exit", "Print", show=True, priority=True),
]

class KmApp(App[None]):
    TITLE = "Knowledge Manager (km)"
    CSS_PATH = "km_tui.css"
    SCREENS = {"projects": ProjectsScreen, "tasks": TasksScreen}
    MODAL_SCREENS = {"input_dialog": InputDialog}

    # Expose at app level so footer can display them
    BINDINGS = APP_BINDINGS

    base_data_dir: Optional[Path] = None
    selected_project: reactive[Optional[Project]] = reactive(None)
    selected_task: reactive[Optional[Task]] = reactive(None)

    # runtime controls
    _start_project_identifier: Optional[str] = None
    _post_exit_stdout_text: Optional[str] = None

    def on_mount(self) -> None:
        # If a start project is provided, jump straight to tasks
        proj = None
        if self._start_project_identifier:
            try:
                proj = project_ops.find_project(self._start_project_identifier, base_data_dir=self.base_data_dir)
            except Exception:
                proj = None
        if proj:
            self.selected_project = proj
            self.push_screen(TasksScreen(project=proj))
        else:
            self.push_screen("projects")

    # ---------- App-level key actions ----------

    async def action_back_or_quit(self) -> None:
        """Pop the current screen if possible, otherwise quit."""
        try:
            # If we are on a nested screen (Tasks), go back to projects
            if isinstance(self.screen, TasksScreen):
                await self.pop_screen()
                return
        except Exception:
            pass
        await self.action_quit()

    async def action_print_project_and_exit(self) -> None:
        """Collect the current project's tasks, stash printable text, then exit the TUI."""
        project = None
        # Prefer project from the current screen if available
        try:
            if isinstance(self.screen, TasksScreen):
                project = self.screen.current_project  # type: ignore[attr-defined]
        except Exception:
            project = None
        if not project:
            project = self.selected_project
        if not project:
            # Nothing to print
            await self.action_quit()
            return

        # Load tasks and build a tree text
        try:
            tasks = task_ops.list_all_tasks(
                project_identifier=str(project.id),
                status=None,
                parent_task_identifier=None,
                include_subtasks_of_any_parent=True,
                base_data_dir=self.base_data_dir,
            )
            text = self._format_task_tree(tasks)
            header = f"Project: {project.name} ({project.id})"
            self._post_exit_stdout_text = header + "\n" + text
        except Exception as ex:
            self._post_exit_stdout_text = f"Error printing project '{project.name}': {ex}\n"
        await self.action_quit()

    # ---------- Events from list views (preserved) ----------

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        # These class names exist in widgets.lists
        from .widgets.lists import ProjectListItem, TaskListItem  # lazy import to avoid circulars
        from . import links  # Import links module

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
                if isinstance(current_screen, TasksScreen):
                    # Check if task has @project links
                    task = item.task_data
                    project_mentions = links.extract_project_mentions(task.title)

                    if project_mentions:
                        # Task has @mention - navigate to first mentioned project
                        target_project_name = project_mentions[0]
                        target_project = links.resolve_project_link(target_project_name, base_data_dir=self.base_data_dir)
                        if target_project:
                            self.notify(f"Jumping to project: {target_project.name}")
                            self.push_screen(TasksScreen(project=target_project))
                        else:
                            self.notify(f"Project '@{target_project_name}' not found", severity="error")
                    else:
                        # No links - just update detail view
                        current_screen.update_detail_view(item.task_data)

    # ---------- Helpers ----------

    def _format_task_tree(self, tasks: List[Task]) -> str:
        children: Dict[Optional[uuid.UUID], List[Task]] = {}
        for t in tasks:
            children.setdefault(t.parent_task_id, []).append(t)
        for lst in children.values():
            lst.sort(key=lambda z: (z.priority or 0, z.created_at, z.title.lower()))
        roots = children.get(None, [])

        def lines():
            def walk(node: Task, depth: int):
                prefix = "  " * depth + "• "
                yield f"{prefix}{node.title} [{node.status.value}]"
                for ch in children.get(node.id, []):
                    yield from walk(ch, depth + 1)
            for r in roots:
                yield from walk(r, 0)

        return "\n".join(lines()) + ("\n" if tasks else "")

    # ---------- Delegate to dialogs (preserved behavior) ----------

    async def action_add_project_prompt(self) -> None:
        async def cb(name: str):
            if name:
                try:
                    new_project = project_ops.create_new_project(name=name, base_data_dir=self.base_data_dir)
                    self.notify(message=f"Project '{new_project.name}' added.", title="Project Added")
                    if isinstance(self.screen, ProjectsScreen):
                        await self.screen.reload_projects_action()
                except ValueError as ve:
                    self.notify(message=f"Error: {ve}", title="Add Project Error", severity="error", timeout=5.0)
                except Exception as e:
                    self.notify(message=f"Error adding project: {e}", title="Error", severity="error")
        await self.push_screen(InputDialog(prompt_text="New project name:"), cb)


def _parse_args_for_app(argv: List[str]) -> tuple[Optional[Path], Optional[str], Optional[Path], List[str]]:
    """
    Return (data_dir_override, project_identifier, log_file_path, argv_for_textual)
    We strip app-specific args from argv and return the remaining args for Textual.
    """
    data_dir_override: Optional[Path] = None
    project_identifier: Optional[str] = None
    log_file_path: Optional[Path] = None

    # Environment defaults
    if os.getenv("KM_BASE_DATA_DIR"):
        data_dir_override = Path(os.environ["KM_BASE_DATA_DIR"]).expanduser()
    if os.getenv("KM_OPEN_PROJECT_ID"):
        project_identifier = os.environ["KM_OPEN_PROJECT_ID"]

    rest: List[str] = [argv[0]]
    i = 1
    while i < len(argv):
        tok = argv[i]
        if tok in ("-G", "--data-dir") and i + 1 < len(argv):
            data_dir_override = Path(argv[i + 1]).expanduser()
            i += 2
            continue
        if tok == "--project" and i + 1 < len(argv):
            project_identifier = argv[i + 1]
            i += 2
            continue
        if tok == "--log-file" and i + 1 < len(argv):
            log_file_path = Path(argv[i + 1]).expanduser()
            i += 2
            continue
        # Pass through to Textual / Rich
        rest.append(tok)
        i += 1

    return data_dir_override, project_identifier, log_file_path, rest


def main() -> None:
    data_dir_override, project_identifier, log_file_path, args_to_pass_to_textual = _parse_args_for_app(sys.argv)

    # Initialize logging if requested
    if log_file_path:
        utils.setup_logging(log_file=log_file_path, level=logging.INFO)

    main_log = logging.getLogger(__name__)
    main_log.info("KmApp TUI starting up...")

    original_argv = sys.argv
    sys.argv = args_to_pass_to_textual

    app = KmApp()
    app.base_data_dir = data_dir_override
    app._start_project_identifier = project_identifier
    app.run()

    sys.argv = original_argv

    # After the app exits, print any queued stdout text (for Ctrl+P)
    if getattr(app, "_post_exit_stdout_text", None):
        print(app._post_exit_stdout_text, end="")


if __name__ == "__main__":
    main()
