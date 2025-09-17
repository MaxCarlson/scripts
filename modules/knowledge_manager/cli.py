#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Knowledge Manager CLI: Manage projects, tasks, and LLM assets.

Merged + Extended:
- Preserves original commands & flags.
- Adds:
  * -c/--create-local-project <name>  → write <slug>.kmproj in CWD (ensures project exists)
  * -o/--open <path.kmproj>           → open TUI focused on that project (best-effort)
  * print [project-or-link] [-a|-t|-i|-d ...]  → print indented task tree
      - 'project' is now optional; if omitted we auto-pick the first *.kmproj in CWD.
  * -p/--print <project-or-link>      → alias for `print`
  * db path | db backup [--dest DIR] [--keep N]

Changes vs last cut:
- Fixed: no longer passes unexpected 'status' kwarg to task_ops.list_all_tasks (works with older task_ops).
- print subcommand accepts no positional project and will try ./*.kmproj as fallback.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, List, Iterable, Tuple
import uuid

from . import project_ops
from . import task_ops
from .models import Project, Task, ProjectStatus, TaskStatus
from . import utils
from . import db

from .linkfile import LINK_EXT, create_link_for_project, load_link_file
from .backup import perform_backup

# --- Configuration (preserved) ---
BASE_DATA_DIR: Optional[Path] = None


# --- Logging (added) ---
def _init_logging(verbose: int = 0, log_file: Optional[Path] = None) -> None:
    level = logging.WARNING
    if verbose >= 2:
        level = logging.DEBUG
    elif verbose == 1:
        level = logging.INFO

    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            filename=log_file,
            filemode="a",
        )
    else:
        logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


# --- Tree printer for `km print` (added) ---
def _build_tree(tasks: List[Task]) -> Tuple[dict, List[Task]]:
    children: dict[Optional[uuid.UUID], List[Task]] = {}
    for t in tasks:
        children.setdefault(t.parent_task_id, []).append(t)
    for lst in children.values():
        lst.sort(key=lambda z: (z.priority or 0, z.created_at, z.title.lower()))
    roots = children.get(None, [])
    return children, roots


def _print_task_tree(tasks: List[Task]) -> str:
    children, roots = _build_tree(tasks)

    def lines():
        def walk(node: Task, depth: int):
            prefix = "  " * depth + "• "
            yield f"{prefix}{node.title} [{node.status.value}]"
            for ch in children.get(node.id, []):
                yield from walk(ch, depth + 1)
        for r in roots:
            yield from walk(r, 0)

    text = "\n".join(lines()) + ("\n" if tasks else "")
    return text


def _resolve_project_id(identifier: str, base_data_dir: Optional[Path]) -> Optional[uuid.UUID]:
    proj = project_ops.find_project(identifier, base_data_dir=base_data_dir)
    return proj.id if proj else None


# --- Helper Functions for CLI Output (preserved) ---
def print_project(project: Project, include_description: bool = False, base_data_dir: Optional[Path] = None):
    print(f"ID        : {project.id}")
    print(f"Name      : {project.name}")
    print(f"Status    : {project.status.value}")
    print(f"Created   : {project.created_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Modified  : {project.modified_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    if project.description_md_path:
        print(f"Desc. File: {project.description_md_path.name}")
        if include_description:
            _, content = project_ops.get_project_with_details(str(project.id), base_data_dir=base_data_dir)
            if content:
                print("-" * 20 + " Description " + "-" * 20)
                print(content)
                print("-" * 53)
    else:
        print("Desc. File: None")


def print_task(task: Task, include_details: bool = False, base_data_dir: Optional[Path] = None):
    print(f"ID        : {task.id}")
    print(f"Title     : {task.title}")
    print(f"Status    : {task.status.value}")
    if task.project_id:
        project_name = str(task.project_id)
        try:
            proj = project_ops.find_project(str(task.project_id), base_data_dir=base_data_dir)
            if proj:
                project_name = f"{proj.name} (ID: {task.project_id})"
        except Exception:
            pass
        print(f"Project   : {project_name}")

    if task.parent_task_id:
        print(f"Parent ID : {task.parent_task_id}")
    print(f"Priority  : {task.priority}")
    if task.due_date:
        print(f"Due Date  : {task.due_date.isoformat()}")
    print(f"Created   : {task.created_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Modified  : {task.modified_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    if task.completed_at:
        print(f"Completed : {task.completed_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    if task.details_md_path:
        print(f"Details File: {task.details_md_path.name}")
        if include_details:
            content = utils.read_markdown_file(task.details_md_path)
            if content:
                print("-" * 20 + " Details " + "-" * 20)
                print(content)
                print("-" * 49)
    else:
        print("Details File: None")


# --- Original Handlers (preserved) ---
def handle_init(args: argparse.Namespace):
    db_path = utils.get_db_path(args.data_dir)
    try:
        print(f"Initializing database at: {db_path}...")
        db.init_db(db_path)
        utils.get_project_content_dir(args.data_dir)
        utils.get_task_content_dir(args.data_dir)
        print("Database and content directories initialized successfully.")
    except Exception as e:
        print(f"An error occurred during initialization: {e}", file=sys.stderr)
        sys.exit(1)


def handle_project_add(args: argparse.Namespace):
    try:
        project = project_ops.create_new_project(
            name=args.name, description=args.description, base_data_dir=args.data_dir
        )
        print(f"Project '{project.name}' created successfully with ID: {project.id}")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr); sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr); sys.exit(1)


def handle_project_list(args: argparse.Namespace):
    status_filter = ProjectStatus(args.status) if args.status else None
    try:
        projects = project_ops.list_all_projects(status=status_filter, base_data_dir=args.data_dir)
        if not projects:
            print("No projects found." if not status_filter else f"No projects found with status '{status_filter.value}'.")
            return
        print(f"\n--- Projects ({len(projects)}) ---")
        for p in projects: print_project(p, base_data_dir=args.data_dir); print("---")
    except Exception as e:
        print(f"An error occurred while listing projects: {e}", file=sys.stderr); sys.exit(1)


def handle_project_view(args: argparse.Namespace):
    try:
        result = project_ops.get_project_with_details(args.identifier, base_data_dir=args.data_dir)
        if result:
            project, _ = result; print_project(project, include_description=True, base_data_dir=args.data_dir)
        else:
            print(f"Project with identifier '{args.identifier}' not found.", file=sys.stderr); sys.exit(1)
    except Exception as e:
        print(f"An error occurred: {e}", file=sys.stderr); sys.exit(1)


def handle_task_add(args: argparse.Namespace):
    try:
        task = task_ops.create_new_task(
            title=args.title, project_identifier=args.project_id, parent_task_identifier=args.parent_id,
            details=args.details, priority=args.priority, due_date_iso=args.due_date, base_data_dir=args.data_dir
        )
        print(f"Task '{task.title}' created successfully with ID: {task.id}")
    except ValueError as e: print(f"Error: {e}", file=sys.stderr); sys.exit(1)
    except Exception as e: print(f"An unexpected error occurred: {e}", file=sys.stderr); sys.exit(1)


def handle_task_list(args: argparse.Namespace):
    status_filter = TaskStatus(args.status) if args.status else None
    try:
        tasks = task_ops.list_all_tasks(
            project_identifier=args.project_id, status=status_filter, parent_task_identifier=args.parent_id,
            include_subtasks_of_any_parent=args.all_subtasks if args.parent_id is None else False,
            base_data_dir=args.data_dir
        )
        if not tasks: print("No tasks found matching criteria."); return
        print(f"\n--- Tasks ({len(tasks)}) ---")
        for t in tasks: print_task(t, base_data_dir=args.data_dir); print("---")
    except ValueError as e: print(f"Error: {e}", file=sys.stderr); sys.exit(1)
    except Exception as e: print(f"An error occurred while listing tasks: {e}", file=sys.stderr); sys.exit(1)


def handle_task_view(args: argparse.Namespace):
    try:
        task = task_ops.find_task(
            task_identifier=args.identifier,
            project_identifier=args.project_context,
            base_data_dir=args.data_dir
        )
        if task: print_task(task, include_details=True, base_data_dir=args.data_dir)
        else:
            print(f"Task with identifier '{args.identifier}' not found {('in project context ' + args.project_context) if args.project_context else ''}.", file=sys.stderr)
            sys.exit(1)
    except ValueError as e: print(f"Error: {e}", file=sys.stderr); sys.exit(1)
    except Exception as e: print(f"An unexpected error occurred: {e}", file=sys.stderr); sys.exit(1)


def handle_task_done(args: argparse.Namespace):
    try:
        task = task_ops.mark_task_status(
            task_identifier=args.identifier,
            new_status=TaskStatus.DONE,
            project_identifier_context=args.project_context,
            base_data_dir=args.data_dir
        )
        if task: print(f"Task '{task.title}' (ID: {task.id}) marked as DONE.")
        else:
            print(f"Task with identifier '{args.identifier}' not found or could not be updated.", file=sys.stderr)
            sys.exit(1)
    except ValueError as e: print(f"Error: {e}", file=sys.stderr); sys.exit(1)
    except Exception as e: print(f"An unexpected error occurred: {e}", file=sys.stderr); sys.exit(1)


def handle_task_getpath(args: argparse.Namespace):
    try:
        file_path = task_ops.get_task_file_path(
            task_identifier=args.identifier,
            project_identifier_context=args.project_context,
            base_data_dir=args.data_dir,
            create_if_missing_in_object=True
        )
        if file_path: print(file_path)
        else:
            print(f"Error: Task with identifier '{args.identifier}' not found or path cannot be determined.", file=sys.stderr)
            sys.exit(1)
    except ValueError as e: print(f"Error: {e}", file=sys.stderr); sys.exit(1)
    except Exception as e: print(f"An unexpected error occurred: {e}", file=sys.stderr); sys.exit(1)


def handle_task_update(args: argparse.Namespace):
    update_fields_provided = any([
        args.title is not None, args.status is not None, args.priority is not None,
        args.due_date is not None, args.details is not None,
        args.project_id is not None, args.clear_project
    ])
    if not update_fields_provided:
        print("Error: No update options provided. Use 'km task update <id> --help' for options.", file=sys.stderr)
        sys.exit(1)
    try:
        task = task_ops.update_task_details_and_status(
            task_identifier=args.identifier,
            new_title=args.title,
            new_status=TaskStatus(args.status) if args.status else None,
            new_priority=args.priority,
            new_due_date_iso=args.due_date,
            new_details=args.details,
            new_project_identifier=args.project_id,
            clear_project=args.clear_project,
            current_project_context_for_search=args.project_context,
            base_data_dir=args.data_dir
        )
        if task:
            print(f"Task '{task.title}' (ID: {task.id}) updated successfully.")
            print_task(task, include_details=True, base_data_dir=args.data_dir)
        else:
            print(f"Error: Task with identifier '{args.identifier}' not found or no updates applied.", file=sys.stderr)
            sys.exit(1)
    except ValueError as e: print(f"Error: {e}", file=sys.stderr); sys.exit(1)
    except Exception as e: print(f"An unexpected error occurred: {e}", file=sys.stderr); sys.exit(1)


# --- Added Handlers ---
def handle_create_local_project(args: argparse.Namespace) -> int:
    _, link_path = create_link_for_project(
        project_name=args.create_local_project,
        directory=Path.cwd(),
        base_data_dir=args.data_dir,
    )
    print(str(link_path))
    return 0


def handle_open_link(args: argparse.Namespace) -> int:
    link_path = Path(args.open).expanduser().resolve()
    link = load_link_file(link_path)

    env = os.environ.copy()
    env["KM_OPEN_PROJECT_ID"] = str(link.project_id)
    if link.base_data_dir:
        env["KM_BASE_DATA_DIR"] = str(link.base_data_dir)

    tui_mod = "knowledge_manager.tui.app"
    cmd = [sys.executable, "-m", tui_mod, "--project", str(link.project_id)]
    try:
        rc = subprocess.call(cmd, env=env)
        if rc != 0:
            print("TUI exited with non-zero code. Falling back to printing project info:\n")
            proj = project_ops.find_project(str(link.project_id), base_data_dir=link.base_data_dir)
            if proj:
                print(f"Project: {proj.name} ({proj.id})")
            else:
                print("Project not found in DB.")
        return rc
    except Exception as ex:
        print(f"Could not start TUI ({tui_mod}): {ex}")
        return 1


def handle_print(args: argparse.Namespace) -> int:
    base_dir = args.data_dir

    # Resolve the target project:
    identifier = args.project
    proj_id: Optional[uuid.UUID] = None

    if not identifier:
        # Auto-pick the first *.kmproj in CWD
        matches = sorted(Path.cwd().glob(f"*{LINK_EXT}"))
        if matches:
            link = load_link_file(matches[0])
            base_dir = link.base_data_dir
            proj_id = link.project_id
        else:
            print("No project specified and no *.kmproj found in current directory.")
            return 2
    else:
        link_path = Path(identifier)
        if link_path.suffix.lower() == LINK_EXT and link_path.exists():
            link = load_link_file(link_path)
            base_dir = link.base_data_dir
            proj_id = link.project_id
        else:
            proj_id = _resolve_project_id(identifier, base_dir)
            if not proj_id:
                print(f"Project '{identifier}' was not found.")
                return 2

    # Pull tasks (compat: do NOT pass 'status' kwarg to task_ops)
    tasks = task_ops.list_all_tasks(
        project_identifier=str(proj_id),
        parent_task_identifier=None,
        include_subtasks_of_any_parent=True,
        base_data_dir=base_dir,
    )

    # Filter locally per flags
    wanted: set[TaskStatus] = set()
    if args.todo: wanted.add(TaskStatus.TODO)
    if args.in_progress: wanted.add(TaskStatus.IN_PROGRESS)
    if args.done: wanted.add(TaskStatus.DONE)
    if wanted:
        tasks = [t for t in tasks if t.status in wanted]

    print(_print_task_tree(tasks), end="")
    return 0


def handle_db_path(args: argparse.Namespace) -> int:
    print(utils.get_db_path(args.data_dir))
    return 0


def handle_db_backup(args: argparse.Namespace) -> int:
    out = perform_backup(base_data_dir=args.data_dir, dest_dir=args.dest, keep=args.keep)
    print(out)
    return 0


# --- Argument Parser Setup (merged) ---
def add_common_task_identifier_args(parser: argparse.ArgumentParser):
    parser.add_argument("identifier", type=str, help="ID or title prefix of the task.")
    parser.add_argument(
        "-j", "--project-context", dest="project_context", type=str, default=None,
        help="Optional project ID or name to scope title prefix search for the task."
    )


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="km",
        description="Knowledge Manager CLI",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="Use 'km <command> --help' for more information on a specific command."
    )
    parser.add_argument('-G', '--data-dir', dest='data_dir', type=Path, default=None,
                        help="Override the default base data directory for this command.")
    # Added global options
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase log verbosity.")
    parser.add_argument("--log-file", type=Path, help="Log to a file instead of stderr.")

    # New top-level helpers
    parser.add_argument("-c", "--create-local-project", metavar="NAME", dest="create_local_project",
                        help=f"Create/ensure a project then write a link file `<slug>{LINK_EXT}` in the current directory.")
    parser.add_argument("-o", "--open", metavar=f"PATH{LINK_EXT}", dest="open",
                        help=f"Open the TUI focused on the project referenced by a {LINK_EXT} file.")
    parser.add_argument("-p", "--print", dest="print_project",
                        help="Alias for `print` (project name or link file).")

    subparsers = parser.add_subparsers(title="Commands", dest="command", metavar="<command>")

    init_parser = subparsers.add_parser("init", help="Initialize the knowledge base")
    init_parser.set_defaults(func=handle_init)

    project_parser = subparsers.add_parser("project", help="Manage projects", aliases=['p'])
    project_subparsers = project_parser.add_subparsers(title="Project Actions", dest="project_action", required=True, metavar="<action>")
    proj_add_parser = project_subparsers.add_parser("add", help="Add a new project")
    proj_add_parser.add_argument("-n", "--name", dest="name", type=str, required=True, help="Name of the project")
    proj_add_parser.add_argument("-d", "--description", dest="description", type=str, help="Markdown description")
    proj_add_parser.set_defaults(func=handle_project_add)
    proj_list_parser = project_subparsers.add_parser("list", help="List projects")
    proj_list_parser.add_argument("-s", "--status", dest="status", type=str, choices=[s.value for s in ProjectStatus], help="Filter by status")
    proj_list_parser.set_defaults(func=handle_project_list)
    proj_view_parser = project_subparsers.add_parser("view", help="View a project")
    proj_view_parser.add_argument("identifier", type=str, help="ID or name of the project")
    proj_view_parser.set_defaults(func=handle_project_view)

    task_parser = subparsers.add_parser("task", help="Manage tasks", aliases=['t'])
    task_subparsers = task_parser.add_subparsers(title="Task Actions", dest="task_action", required=True, metavar="<action>")
    task_add_parser = task_subparsers.add_parser("add", help="Add a new task")
    task_add_parser.add_argument("-t", "--title", dest="title", type=str, required=True, help="Title of the task")
    task_add_parser.add_argument("-p", "--project-id", dest="project_id", type=str, help="Associate with project (ID or name)")
    task_add_parser.add_argument("-P", "--parent-id", dest="parent_id", type=str, help="Parent task ID (for subtask)")
    task_add_parser.add_argument("-d", "--details", dest="details", type=str, help="Markdown details")
    task_add_parser.add_argument("-r", "--priority", dest="priority", type=int, default=3, choices=range(1,6), help="Priority (1-5)")
    task_add_parser.add_argument("-U", "--due-date", dest="due_date", type=str, help="Due date (YYYY-MM-DD)")
    task_add_parser.set_defaults(func=handle_task_add)

    task_list_parser = subparsers.add_parser("list", help="List tasks")
    task_list_parser.add_argument("-p", "--project-id", dest="project_id", type=str, help="Filter by project (ID or name)")
    task_list_parser.add_argument("-s", "--status", dest="status", type=str, choices=[s.value for s in TaskStatus], help="Filter by status")
    task_list_parser.add_argument("-P", "--parent-id", dest="parent_id", type=str, help="Filter by parent task ID")
    task_list_parser.add_argument("-a", "--all-subtasks", dest="all_subtasks", action="store_true", help="Include all subtasks (not just top-level)")
    task_list_parser.add_argument("-d", "--details", dest="include_details", action="store_true", help="Include full task details (markdown content)")
    task_list_parser.set_defaults(func=handle_task_list)

    task_view_parser = subparsers.add_parser("view", help="View a task")
    add_common_task_identifier_args(task_view_parser)
    task_view_parser.set_defaults(func=handle_task_view)
    
    task_done_parser = subparsers.add_parser("done", help="Mark a task as done")
    add_common_task_identifier_args(task_done_parser)
    task_done_parser.set_defaults(func=handle_task_done)

    task_getpath_parser = subparsers.add_parser("getpath", help="Get task's details file path")
    add_common_task_identifier_args(task_getpath_parser)
    task_getpath_parser.set_defaults(func=handle_task_getpath)

    task_update_parser = subparsers.add_parser("update", help="Update an existing task")
    add_common_task_identifier_args(task_update_parser) 
    task_update_parser.add_argument("-t", "--title", dest="title", type=str, default=None, help="New title")
    task_update_parser.add_argument("-s", "--status", dest="status", type=str, default=None, choices=[s.value for s in TaskStatus], help="New status")
    task_update_parser.add_argument("-r", "--priority", dest="priority", type=int, default=None, choices=range(1,6), help="New priority")
    task_update_parser.add_argument("-u", "--due-date", dest="due_date", type=str, default=None, help='New due date (YYYY-MM-DD), or "" to clear')
    task_update_parser.add_argument("-d", "--details", dest="details", type=str, default=None, help='New Markdown details, or "" to clear')
    task_update_parser.add_argument("-p", "--project-id", dest="project_id", type=str, default=None, help="Move to new project (ID or name)") # For assigning/moving
    task_update_parser.add_argument("-c", "--clear-project", dest="clear_project", action="store_true", help="Disassociate from any project")
    task_update_parser.set_defaults(func=handle_task_update)

    # New subcommand: print  (project arg optional)
    sp_print = subparsers.add_parser("print", help="Print a project's task hierarchy.")
    sp_print.add_argument("project", nargs="?", help=f"Project name/UUID or a {LINK_EXT} file path. If omitted, the first *.kmproj in CWD is used.")
    sp_print.add_argument("-a", "--all", action="store_true", help="Show all tasks (default).")
    sp_print.add_argument("-t", "--todo", action="store_true", help="Show TODO tasks.")
    sp_print.add_argument("-i", "--in-progress", action="store_true", help="Show IN-PROGRESS tasks.")
    sp_print.add_argument("-d", "--done", action="store_true", help="Show DONE tasks.")
    sp_print.set_defaults(func=handle_print)

    # DB helpers
    sp_db = subparsers.add_parser("db", help="Database utilities.")
    sub_db = sp_db.add_subparsers(dest="db_cmd", required=True)
    sp_db_path = sub_db.add_parser("path", help="Show database path.")
    sp_db_path.set_defaults(func=handle_db_path)
    sp_db_backup = sub_db.add_parser("backup", help="Create a timestamped DB backup.")
    sp_db_backup.add_argument("--dest", type=Path, help="Backup destination directory (default: <dbdir>/backups).")
    sp_db_backup.add_argument("--keep", type=int, default=10, help="Number of backups to keep.")
    sp_db_backup.set_defaults(func=handle_db_backup)

    return parser


def main(argv: Optional[List[str]] = None):
    parser = create_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    _init_logging(getattr(args, "verbose", 0), getattr(args, "log_file", None))

    global BASE_DATA_DIR 
    if hasattr(args, 'data_dir') and args.data_dir is not None:
        BASE_DATA_DIR = args.data_dir

    # Top-level helpers (no subcommand required)
    if getattr(args, "create_local_project", None):
        sys.exit(handle_create_local_project(args))
    if getattr(args, "open", None):
        sys.exit(handle_open_link(args))
    if getattr(args, "print_project", None):
        sys.exit(main(["print", args.print_project] + (["-G", str(args.data_dir)] if args.data_dir else [])))

    if hasattr(args, 'func'):
        try:
            args.func(args)
        except Exception as e:
            print(f"An unhandled error occurred: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
