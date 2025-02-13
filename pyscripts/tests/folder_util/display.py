# folder_util/display.py

from rich.table import Table
from rich.console import Console
from rich import box

def display_items(items, columns, truncate=20, sort_key="date"):
    console = Console()
    table = Table(show_header=True, header_style="bold magenta", box=box.MINIMAL_DOUBLE_HEAD)
    
    # Always include the Name column
    table.add_column("Name", style="cyan", no_wrap=True)
    
    # Add extra columns based on flags
    for col in columns:
        if col == "size":
            table.add_column("Size (bytes)", style="green")
        elif col == "date_created":
            table.add_column("Date Created", style="yellow")
        elif col == "date_modified":
            table.add_column("Date Modified", style="yellow")
        elif col == "date_accessed":
            table.add_column("Date Accessed", style="yellow")
        elif col == "permissions":
            table.add_column("Permissions", style="blue")
        elif col == "owner":
            table.add_column("Owner", style="magenta")
        elif col == "file_count":
            table.add_column("File Count", style="green")
        elif col == "attributes":
            table.add_column("Attributes", style="cyan")
        elif col == "git_repo":
            table.add_column("Git Repo", style="red")
        elif col == "git_status":
            table.add_column("Git Status", style="red")
        else:
            table.add_column(col)
    
    for item in items:
        # Truncate the name if necessary
        name = item.get("name", "")
        if len(name) > truncate:
            name = name[:truncate] + "..."
        row = [name]
        for col in columns:
            if col == "size":
                value = str(item.get("size", ""))
            elif col in ["date_created", "date_modified", "date_accessed"]:
                dt = item.get(col)
                value = dt.strftime("%Y-%m-%d %H:%M") if dt else ""
            elif col == "permissions":
                value = item.get("permissions", "")
            elif col == "owner":
                value = item.get("owner", "")
            elif col == "file_count":
                value = str(item.get("file_count", ""))
            elif col == "attributes":
                value = item.get("attributes", "")
            elif col == "git_repo":
                value = item.get("git_repo", "")
            elif col == "git_status":
                value = item.get("git_status", "")
            else:
                value = str(item.get(col, ""))
            row.append(value)
        table.add_row(*row)
    console.print(table)