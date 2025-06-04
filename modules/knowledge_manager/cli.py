# File: knowledge_manager/cli.py
import argparse
import sys
from pathlib import Path
from typing import Optional, List

from . import project_ops
from . import task_ops
from .models import Project, Task, ProjectStatus, TaskStatus
from . import utils
from . import db 

# --- Configuration ---
BASE_DATA_DIR: Optional[Path] = None 

# --- Helper Functions for CLI Output ---
def print_project(project: Project, include_description: bool = False, base_data_dir: Optional[Path] = None):
    """Prints project details to the console."""
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
    """Prints task details to the console."""
    print(f"ID        : {task.id}")
    print(f"Title     : {task.title}")
    print(f"Status    : {task.status.value}")
    if task.project_id:
        print(f"Project ID: {task.project_id}")
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

# --- Init Command Handler ---
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

# --- Project Command Handlers ---
def handle_project_add(args: argparse.Namespace):
    try:
        project = project_ops.create_new_project(
            name=args.name,
            description=args.description,
            base_data_dir=args.data_dir
        )
        print(f"Project '{project.name}' created successfully with ID: {project.id}")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)

def handle_project_list(args: argparse.Namespace):
    status_filter = ProjectStatus(args.status) if args.status else None
    try:
        projects = project_ops.list_all_projects(status=status_filter, base_data_dir=args.data_dir)
        if not projects:
            print("No projects found." if not status_filter else f"No projects found with status '{status_filter.value}'.")
            return
        print(f"\n--- Projects ({len(projects)}) ---")
        for p in projects:
            print_project(p, base_data_dir=args.data_dir)
            print("---")
    except Exception as e:
        print(f"An error occurred while listing projects: {e}", file=sys.stderr)
        sys.exit(1)

def handle_project_view(args: argparse.Namespace):
    try:
        result = project_ops.get_project_with_details(args.identifier, base_data_dir=args.data_dir)
        if result:
            project, _ = result
            print_project(project, include_description=True, base_data_dir=args.data_dir)
        else:
            print(f"Project with identifier '{args.identifier}' not found.", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"An error occurred: {e}", file=sys.stderr)
        sys.exit(1)

# --- Task Command Handlers ---
def handle_task_add(args: argparse.Namespace):
    try:
        task = task_ops.create_new_task(
            title=args.title,
            project_identifier=args.project_id,
            parent_task_identifier=args.parent_id,
            details=args.details,
            priority=args.priority,
            due_date_iso=args.due_date,
            base_data_dir=args.data_dir
        )
        print(f"Task '{task.title}' created successfully with ID: {task.id}")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)

def handle_task_list(args: argparse.Namespace):
    status_filter = TaskStatus(args.status) if args.status else None
    try:
        tasks = task_ops.list_all_tasks(
            project_identifier=args.project_id,
            status=status_filter,
            parent_task_identifier=args.parent_id,
            include_subtasks_of_any_parent=args.all_subtasks if args.parent_id is None else False,
            base_data_dir=args.data_dir
        )
        if not tasks:
            print("No tasks found matching criteria.")
            return
        print(f"\n--- Tasks ({len(tasks)}) ---")
        for t in tasks:
            print_task(t, base_data_dir=args.data_dir)
            print("---")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An error occurred while listing tasks: {e}", file=sys.stderr)
        sys.exit(1)

def handle_task_view(args: argparse.Namespace):
    try:
        task = task_ops.find_task(args.identifier, base_data_dir=args.data_dir)
        if task:
            print_task(task, include_details=True, base_data_dir=args.data_dir)
        else:
            print(f"Task with identifier '{args.identifier}' not found.", file=sys.stderr)
            sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)

def handle_task_done(args: argparse.Namespace):
    try:
        task = task_ops.mark_task_status(args.identifier, TaskStatus.DONE, base_data_dir=args.data_dir)
        if task:
            print(f"Task '{task.title}' (ID: {task.id}) marked as DONE.")
        else:
            print(f"Task with identifier '{args.identifier}' not found or could not be updated.", file=sys.stderr)
            sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)

def handle_task_getpath(args: argparse.Namespace):
    try:
        file_path = task_ops.get_task_file_path(
            task_identifier=args.identifier,
            base_data_dir=args.data_dir,
            create_if_missing_in_object=True
        )
        if file_path:
            print(file_path) 
        else:
            print(f"Error: Task with identifier '{args.identifier}' not found or path cannot be determined.", file=sys.stderr)
            sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)

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
            base_data_dir=args.data_dir
        )
        if task:
            print(f"Task '{task.title}' (ID: {task.id}) updated successfully.")
            print_task(task, include_details=True, base_data_dir=args.data_dir)
        else:
            print(f"Error: Task with identifier '{args.identifier}' not found or no updates applied.", file=sys.stderr)
            sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)

# --- Main Parser Setup ---
def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="km",
        description="Knowledge Manager CLI: Manage projects, tasks, and LLM assets.",
        formatter_class=argparse.RawTextHelpFormatter, 
        epilog="Use 'km <command> --help' for more information on a specific command."
    )
    parser.add_argument(
        '-D', '--data-dir', dest='data_dir', type=Path, default=None, # Added short form -D
        help="Override the default base data directory for this command."
    )

    subparsers = parser.add_subparsers(title="Commands", dest="command", required=True, metavar="<command>")

    # --- Init Command ---
    init_parser = subparsers.add_parser("init", help="Initialize the knowledge base (database and directories)")
    init_parser.set_defaults(func=handle_init)

    # --- Project Subparser ---
    project_parser = subparsers.add_parser("project", help="Manage projects", aliases=['p'])
    project_subparsers = project_parser.add_subparsers(title="Project Actions", dest="project_action", required=True, metavar="<action>")

    proj_add_parser = project_subparsers.add_parser("add", help="Add a new project")
    proj_add_parser.add_argument("-n", "--name", dest="name", type=str, required=True, help="Name of the project")
    proj_add_parser.add_argument("-d", "--description", dest="description", type=str, help="Markdown description for the project")
    proj_add_parser.set_defaults(func=handle_project_add)

    proj_list_parser = project_subparsers.add_parser("list", help="List projects")
    proj_list_parser.add_argument(
        "-s", "--status", dest="status", type=str, choices=[s.value for s in ProjectStatus],
        help="Filter projects by status"
    )
    proj_list_parser.set_defaults(func=handle_project_list)

    proj_view_parser = project_subparsers.add_parser("view", help="View details of a specific project")
    proj_view_parser.add_argument("identifier", type=str, help="ID or name of the project to view")
    proj_view_parser.set_defaults(func=handle_project_view)


    # --- Task Subparser ---
    task_parser = subparsers.add_parser("task", help="Manage tasks", aliases=['t'])
    task_subparsers = task_parser.add_subparsers(title="Task Actions", dest="task_action", required=True, metavar="<action>")

    # km task add
    task_add_parser = task_subparsers.add_parser("add", help="Add a new task")
    task_add_parser.add_argument("-t", "--title", dest="title", type=str, required=True, help="Title of the task")
    task_add_parser.add_argument("-p", "--project-id", dest="project_id", type=str, help="Project ID or name to associate the task with")
    task_add_parser.add_argument("-P", "--parent-id", dest="parent_id", type=str, help="Parent task ID for creating a subtask")
    task_add_parser.add_argument("-d", "--details", dest="details", type=str, help="Markdown details for the task")
    task_add_parser.add_argument("-r", "--priority", dest="priority", type=int, default=3, choices=range(1,6), help="Priority (1-5, default 3)")
    task_add_parser.add_argument("-D", "--due-date", dest="due_date", type=str, help="Due date in YYYY-MM-DD format") # Note: -D is also used for global --data-dir. This is a conflict.
    task_add_parser.set_defaults(func=handle_task_add)

    # km task list
    task_list_parser = task_subparsers.add_parser("list", help="List tasks")
    task_list_parser.add_argument("-p", "--project-id", dest="project_id", type=str, help="Filter tasks by project ID or name")
    task_list_parser.add_argument(
        "-s", "--status", dest="status", type=str, choices=[s.value for s in TaskStatus],
        help="Filter tasks by status"
    )
    task_list_parser.add_argument("-P", "--parent-id", dest="parent_id", type=str, help="Filter tasks by parent task ID")
    task_list_parser.add_argument(
        "-a", "--all-subtasks", dest="all_subtasks", action="store_true",
        help="When listing without --parent-id, include all subtasks (not just top-level)."
    )
    task_list_parser.set_defaults(func=handle_task_list)

    # km task view
    task_view_parser = task_subparsers.add_parser("view", help="View details of a specific task")
    task_view_parser.add_argument("identifier", type=str, help="ID of the task to view")
    task_view_parser.set_defaults(func=handle_task_view)
    
    # km task done
    task_done_parser = task_subparsers.add_parser("done", help="Mark a task as done")
    task_done_parser.add_argument("identifier", type=str, help="ID of the task to mark as done")
    task_done_parser.set_defaults(func=handle_task_done)

    # km task getpath
    task_getpath_parser = task_subparsers.add_parser("getpath", help="Get the filesystem path for a task's details file")
    task_getpath_parser.add_argument("identifier", type=str, help="ID of the task")
    task_getpath_parser.set_defaults(func=handle_task_getpath)

    # km task update
    task_update_parser = task_subparsers.add_parser("update", help="Update an existing task")
    task_update_parser.add_argument("identifier", type=str, help="ID of the task to update")
    task_update_parser.add_argument("-t", "--title", dest="title", type=str, default=None, help="New title for the task")
    task_update_parser.add_argument(
        "-s", "--status", dest="status", type=str, default=None, choices=[s.value for s in TaskStatus],
        help="New status for the task"
    )
    task_update_parser.add_argument(
        "-r", "--priority", dest="priority", type=int, default=None, choices=range(1,6),
        help="New priority (1-5)"
    )
    task_update_parser.add_argument(
        "-u", "--due-date", dest="due_date", type=str, default=None, # Changed short from -D to -u to avoid conflict
        help="New due date (YYYY-MM-DD), or \"\" to clear"
    )
    task_update_parser.add_argument(
        "-d", "--details", dest="details", type=str, default=None,
        help="New Markdown details for the task, or \"\" to clear/empty file"
    )
    task_update_parser.add_argument(
        "-p", "--project-id", dest="project_id", type=str, default=None,
        help="New project ID or name to associate the task with"
    )
    task_update_parser.add_argument(
        "-c", "--clear-project", dest="clear_project", action="store_true",
        help="Remove task from any project (disassociate)"
    )
    task_update_parser.set_defaults(func=handle_task_update)

    return parser

def main(argv: Optional[List[str]] = None):
    parser = create_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    
    global BASE_DATA_DIR 
    if hasattr(args, 'data_dir') and args.data_dir is not None: # Check if data_dir was actually provided
        BASE_DATA_DIR = args.data_dir
    
    if hasattr(args, 'func'):
        try:
            # Pass the specific data_dir for this command to the handler,
            # which then passes it to ops functions.
            # The ops functions will use their default if args.data_dir is None.
            args.func(args) 
        except Exception as e:
            print(f"An unhandled error occurred: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == '__main__':
    main()

# End of File: knowledge_manager/cli.py
