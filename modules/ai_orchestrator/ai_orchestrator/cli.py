"""CLI interface for AI Orchestrator."""

import sys
from typing import Optional
from pathlib import Path

try:
    import typer
    from rich.console import Console
    from rich.table import Table
    from rich.tree import Tree
    from rich.panel import Panel
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    typer = None
    Console = None

from .db_interface import KnowledgeDB
from .cli_manager import CLIManager, JobType
from .model_manager import ModelManager, ModelCapability


if not RICH_AVAILABLE:
    print("Error: required packages not installed. Run: pip install typer rich")
    sys.exit(1)

app = typer.Typer(help="AI Orchestrator - Unified CLI, model, and knowledge management")
console = Console()


# === Database Commands ===

db_app = typer.Typer(help="Knowledge database operations")
app.add_typer(db_app, name="db")


@db_app.command("list-projects")
def list_projects(
    status: Optional[str] = typer.Option(None, "-s", "--status", help="Filter by status"),
):
    """List all projects."""
    with KnowledgeDB() as db:
        projects = db.list_projects(status=status)

        if not projects:
            console.print("[yellow]No projects found[/yellow]")
            return

        table = Table(title="Projects")
        table.add_column("Name", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Modified", style="blue")
        table.add_column("ID", style="dim")

        for p in projects:
            table.add_row(
                p["name"],
                p["status"],
                p["modified_at"][:19],
                p["id"][:8]
            )

        console.print(table)


@db_app.command("show-project")
def show_project(
    name: Optional[str] = typer.Option(None, "-n", "--name", help="Project name"),
    project_id: Optional[str] = typer.Option(None, "-i", "--id", help="Project ID"),
    show_tasks: bool = typer.Option(True, "--tasks/--no-tasks", help="Show tasks"),
):
    """Show detailed project information."""
    if not name and not project_id:
        console.print("[red]Error: must provide either --name or --id[/red]")
        raise typer.Exit(1)

    with KnowledgeDB() as db:
        if name:
            project = db.get_project(name=name)
        else:
            project = db.get_project(project_id=project_id)

        if not project:
            console.print(f"[red]Project not found[/red]")
            raise typer.Exit(1)

        # Show project details
        console.print(Panel(
            f"[bold cyan]{project['name']}[/bold cyan]\n"
            f"Status: {project['status']}\n"
            f"Created: {project['created_at'][:19]}\n"
            f"Modified: {project['modified_at'][:19]}\n"
            f"ID: {project['id']}",
            title="Project Details"
        ))

        # Show tasks if requested
        if show_tasks:
            tree_data = db.get_project_tree(project['id'])
            if tree_data.get('tasks'):
                console.print("\n[bold]Tasks:[/bold]")
                _print_task_tree(tree_data['tasks'])
            else:
                console.print("\n[dim]No tasks[/dim]")


def _print_task_tree(tasks, level=0):
    """Recursively print task tree."""
    for task in tasks:
        indent = "  " * level
        status_color = {
            "todo": "yellow",
            "in-progress": "blue",
            "done": "green"
        }.get(task["status"], "white")

        console.print(
            f"{indent}• [{status_color}]{task['status']:12}[/{status_color}] {task['title']}"
        )

        if task.get("subtasks"):
            _print_task_tree(task["subtasks"], level + 1)


@db_app.command("create-project")
def create_project(
    name: str = typer.Argument(..., help="Project name"),
    status: str = typer.Option("active", "-s", "--status", help="Project status"),
):
    """Create a new project."""
    with KnowledgeDB() as db:
        project = db.create_project(name=name, status=status)
        console.print(f"[green]✓[/green] Created project: {project['name']} (ID: {project['id'][:8]})")


@db_app.command("create-task")
def create_task(
    title: str = typer.Argument(..., help="Task title"),
    project: Optional[str] = typer.Option(None, "-p", "--project", help="Project name"),
    status: str = typer.Option("todo", "-s", "--status", help="Task status"),
    priority: int = typer.Option(3, "--priority", help="Priority 1-5"),
):
    """Create a new task."""
    with KnowledgeDB() as db:
        # Resolve project name to ID if provided
        project_id = None
        if project:
            proj = db.get_project(name=project)
            if not proj:
                console.print(f"[red]Error: Project '{project}' not found[/red]")
                raise typer.Exit(1)
            project_id = proj['id']

        task = db.create_task(
            title=title,
            project_id=project_id,
            status=status,
            priority=priority
        )
        console.print(f"[green]✓[/green] Created task: {task['title']} (ID: {task['id'][:8]})")


@db_app.command("list-tasks")
def list_tasks(
    project: Optional[str] = typer.Option(None, "-p", "--project", help="Project name"),
    status: Optional[str] = typer.Option(None, "-s", "--status", help="Task status"),
):
    """List tasks."""
    with KnowledgeDB() as db:
        # Resolve project name to ID if provided
        project_id = None
        if project:
            proj = db.get_project(name=project)
            if not proj:
                console.print(f"[red]Error: Project '{project}' not found[/red]")
                raise typer.Exit(1)
            project_id = proj['id']

        status_list = [status] if status else None
        tasks = db.list_tasks(project_id=project_id, status=status_list)

        if not tasks:
            console.print("[yellow]No tasks found[/yellow]")
            return

        table = Table(title="Tasks")
        table.add_column("Title", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Priority", style="magenta")
        table.add_column("Modified", style="blue")
        table.add_column("ID", style="dim")

        for t in tasks:
            table.add_row(
                t["title"][:50],
                t["status"],
                str(t["priority"]),
                t["modified_at"][:19],
                t["id"][:8]
            )

        console.print(table)


# === CLI Tool Commands ===

cli_tool_app = typer.Typer(help="CLI tool management")
app.add_typer(cli_tool_app, name="cli")


@cli_tool_app.command("list")
def list_cli_tools(
    installed_only: bool = typer.Option(False, "--installed", help="Show only installed tools"),
):
    """List available CLI tools."""
    manager = CLIManager()
    tools = manager.list_all_tools(installed_only=installed_only)

    table = Table(title="CLI Tools")
    table.add_column("Name", style="cyan")
    table.add_column("Command", style="green")
    table.add_column("Installed", style="yellow")
    table.add_column("Priority", style="magenta")
    table.add_column("Description", style="blue")

    for tool in tools:
        installed_mark = "✓" if tool.installed else "✗"
        table.add_row(
            tool.name,
            tool.command,
            installed_mark,
            str(tool.priority),
            tool.description[:50]
        )

    console.print(table)


@cli_tool_app.command("best")
def best_cli_tool(
    job_type: str = typer.Argument(..., help="Job type (e.g., code_generation, file_operations)"),
    local_only: bool = typer.Option(False, "--local", help="Require local tools only"),
):
    """Get the best CLI tool for a job type."""
    manager = CLIManager()

    try:
        job = JobType(job_type)
    except ValueError:
        console.print(f"[red]Invalid job type. Valid types:[/red]")
        for jt in JobType:
            console.print(f"  - {jt.value}")
        raise typer.Exit(1)

    tool = manager.get_best_tool(job, require_local=local_only)

    if not tool:
        console.print(f"[yellow]No suitable tool found for {job_type}[/yellow]")
        raise typer.Exit(1)

    console.print(Panel(
        f"[bold cyan]{tool.name}[/bold cyan]\n"
        f"Command: {tool.command}\n"
        f"Priority: {tool.priority}/10\n"
        f"Network required: {'Yes' if tool.requires_network else 'No'}\n"
        f"API key required: {'Yes' if tool.requires_api_key else 'No'}\n\n"
        f"{tool.description}",
        title=f"Best Tool for {job_type}"
    ))


# === Model Commands ===

model_app = typer.Typer(help="AI model management")
app.add_typer(model_app, name="model")


@model_app.command("list")
def list_models(
    capability: Optional[str] = typer.Option(None, "-c", "--capability", help="Filter by capability"),
    local_only: bool = typer.Option(False, "--local", help="Show only local models"),
):
    """List available AI models."""
    manager = ModelManager()

    cap = None
    if capability:
        try:
            cap = ModelCapability(capability)
        except ValueError:
            console.print(f"[red]Invalid capability. Valid capabilities:[/red]")
            for c in ModelCapability:
                console.print(f"  - {c.value}")
            raise typer.Exit(1)

    models = manager.get_available_models(capability=cap, local_only=local_only)

    table = Table(title="AI Models")
    table.add_column("Name", style="cyan")
    table.add_column("Provider", style="green")
    table.add_column("Context", style="yellow")
    table.add_column("Priority", style="magenta")
    table.add_column("Local", style="blue")

    for model in models:
        table.add_row(
            model.name,
            model.provider.value,
            f"{model.context_window:,}",
            str(model.priority),
            "✓" if model.is_local else "✗"
        )

    console.print(table)


@model_app.command("best")
def best_model(
    capability: str = typer.Argument(..., help="Required capability"),
    prefer_local: bool = typer.Option(False, "--local", help="Prefer local models"),
):
    """Get the best model for a capability."""
    manager = ModelManager()

    try:
        cap = ModelCapability(capability)
    except ValueError:
        console.print(f"[red]Invalid capability. Valid capabilities:[/red]")
        for c in ModelCapability:
            console.print(f"  - {c.value}")
        raise typer.Exit(1)

    model = manager.get_best_model(cap, prefer_local=prefer_local)

    if not model:
        console.print(f"[yellow]No suitable model found for {capability}[/yellow]")
        raise typer.Exit(1)

    console.print(Panel(
        f"[bold cyan]{model.name}[/bold cyan]\n"
        f"Provider: {model.provider.value}\n"
        f"Model ID: {model.model_id}\n"
        f"Context window: {model.context_window:,} tokens\n"
        f"Max output: {model.max_output_tokens:,} tokens\n"
        f"Priority: {model.priority}/10\n"
        f"Local: {'Yes' if model.is_local else 'No'}\n"
        f"Requires GPU: {'Yes' if model.requires_gpu else 'No'}",
        title=f"Best Model for {capability}"
    ))


@model_app.command("gpu")
def gpu_status():
    """Show GPU status."""
    manager = ModelManager()
    status = manager.get_gpu_status()

    if not status["available"]:
        console.print("[yellow]No GPU detected[/yellow]")
        return

    console.print(Panel(
        f"[bold cyan]{status['name']}[/bold cyan]\n"
        f"Total VRAM: {status['vram_total_gb']:.1f} GB\n"
        f"Available VRAM: {status['vram_available_gb']:.1f} GB",
        title="GPU Status"
    ))


@model_app.command("recommend")
def recommend_model(
    task: str = typer.Argument(..., help="Task description"),
    prefer_local: bool = typer.Option(False, "--local", help="Prefer local models"),
):
    """Get model recommendations for a task."""
    manager = ModelManager()
    recommendations = manager.get_model_recommendations(task, prefer_local=prefer_local)

    if not recommendations:
        console.print("[yellow]No recommendations available[/yellow]")
        return

    console.print(f"\n[bold]Recommendations for:[/bold] {task}\n")

    for i, (model, reason) in enumerate(recommendations, 1):
        console.print(Panel(
            f"[bold cyan]{model.name}[/bold cyan]\n"
            f"Provider: {model.provider.value}\n"
            f"Model ID: {model.model_id}\n"
            f"[dim]{reason}[/dim]",
            title=f"#{i}"
        ))


# === Status Command ===

@app.command("status")
def show_status():
    """Show overall system status."""
    console.print("[bold cyan]AI Orchestrator Status[/bold cyan]\n")

    # Database status
    try:
        with KnowledgeDB() as db:
            projects = db.list_projects()
            tasks = db.list_tasks()
            console.print(f"[green]✓[/green] Database: {len(projects)} projects, {len(tasks)} tasks")
    except Exception as e:
        console.print(f"[red]✗[/red] Database: Error - {e}")

    # CLI tools status
    cli_manager = CLIManager()
    installed = len([t for t in cli_manager.list_all_tools() if t.installed])
    total = len(cli_manager.list_all_tools())
    console.print(f"[green]✓[/green] CLI Tools: {installed}/{total} installed")

    # GPU status
    model_manager = ModelManager()
    gpu = model_manager.get_gpu_status()
    if gpu["available"]:
        console.print(f"[green]✓[/green] GPU: {gpu['name']} ({gpu['vram_available_gb']:.1f}GB available)")
    else:
        console.print(f"[yellow]○[/yellow] GPU: Not detected")

    # Models status
    models = model_manager.get_available_models()
    local = len([m for m in models if m.is_local])
    console.print(f"[green]✓[/green] Models: {len(models)} configured ({local} local)")


if __name__ == "__main__":
    app()
