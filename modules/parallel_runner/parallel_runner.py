import asyncio
import subprocess
import re
import os
import sys
import logging
from typing import Callable, List, Dict, Any, Optional
from rich.live import Live
from rich.progress import Progress, BarColumn, TaskProgressColumn, TextColumn, SpinnerColumn, Text
from rich.console import Console

console = Console()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class ParallelRunner:
    def __init__(
            self,
            command_template: List[str],
            instance_args: List[List[str]],
            parser_func: Callable[[str, str], Optional[Any]],
            aggregate_func: Callable[[Dict[int, Any]], Optional[Dict[str, Any]]],
            restart_on_failure: bool = False,
            max_retries: int = 3,
            log_output: bool = False,
            allow_pause_resume: bool = False,
    ):
        self.command_template = command_template
        self.instance_args = instance_args
        self.parser_func = parser_func
        self.aggregate_func = aggregate_func
        self.restart_on_failure = restart_on_failure
        self.max_retries = max_retries
        self.log_output = log_output
        self.allow_pause_resume = allow_pause_resume
        self.task_status = {i: "Running" for i in range(len(instance_args))}
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # Initially not paused
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}[/bold blue]"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("({task.fields[status]})"),
            TextColumn("  {task.fields[speed]}", justify="right"),
        )
        self.overall_task_id = self.progress.add_task("[bold green]Overall Progress[/bold green]", total=100, status="", speed="")
        self.instance_tasks = {}
        self.parsed_outputs = {}

    async def run_instance(self, instance_name: str, args: List[str], instance_id: int):
        cmd = self.command_template + args
        stdout_buffer = ""
        stderr_buffer = ""
        retry_count = 0
        log_file = None
        if self.log_output:
            try:
                log_file = open(f"{instance_name}.log", "w")
            except IOError as e:
                console.print(f"[bold red]Error opening log file for {instance_name}: {e}[/bold red]")
                self.log_output = False

        task_id = self.progress.add_task(f"[cyan]{instance_name}[/cyan]", total=None, status="Running", speed="")
        self.instance_tasks[instance_id] = task_id

        while retry_count <= self.max_retries:
            await self._pause_event.wait()  # Wait if paused

            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )

                async for line in process.stdout:
                    line_str = line.decode().strip()
                    stdout_buffer += line_str + "\n"
                    try:
                        parsed = self.parser_func(line_str, stderr_buffer) # Parse only the new line
                        if parsed and 'total' in parsed:
                            self.progress.update(task_id, total=parsed['total'])
                        if parsed and 'current' in parsed:
                            self.progress.update(task_id, completed=parsed['current'])
                        self.parsed_outputs[instance_id] = parsed # Update parsed_outputs immediately
                        if parsed and 'speed' in parsed:
                            self.progress.update(task_id, speed=parsed['speed']) # Update the speed field
                    except Exception as e:
                        logging.error(f"Error in parser for {instance_name}: {e}")

                    if log_file:
                        log_file.write(line_str + "\n")

                async for line in process.stderr:
                    stderr_buffer += line.decode().strip() + "\n"
                    if log_file:
                        log_file.write("[stderr] " + line.decode().strip() + "\n")

                await process.wait()
                self.progress.update(task_id, completed=self.progress.tasks[task_id].total if self.progress.tasks[task_id].total is not None else 100, status="✅ Done")
                self.task_status[instance_id] = "✅ Done"
                break

            except Exception as e:
                self.task_status[instance_id] = "❌ Failed"
                console.print(f"[bold red]Error running {instance_name}: {e}[/bold red]")
                self.progress.update(task_id, status="❌ Failed")
                if not self.restart_on_failure or retry_count >= self.max_retries:
                    break
                retry_count += 1
                console.print(f"[yellow]Restarting {instance_name} (Attempt {retry_count}/{self.max_retries})...[/yellow]")
                self.progress.update(task_id, completed=0, status=f"🔄 Retrying ({retry_count}/{self.max_retries})")
                await asyncio.sleep(1)

        if log_file:
            try:
                log_file.close()
            except IOError as e:
                console.print(f"[bold red]Error closing log file for {instance_name}: {e}[/bold red]")

    def update_individual_progress(self, instance_id: int, parsed_output: Any):
        pass

    async def monitor_overall_progress(self):
        while True:
            if self.parsed_outputs:
                try:
                    aggregated = self.aggregate_func(self.parsed_outputs)
                    if aggregated and 'overall_speed' in aggregated:
                        total_possible_progress = sum(output.get('total', 1) for output in self.parsed_outputs.values() if output)
                        current_total_progress = sum(output.get('current', 0) for output in self.parsed_outputs.values() if output)

                        if total_possible_progress > 0:
                            overall_percentage = int((current_total_progress / total_possible_progress) * 100)
                            self.progress.update(self.overall_task_id, completed=overall_percentage, fields={'speed': aggregated['overall_speed']}, description=f"[bold green]Overall Progress (Speed: {aggregated['overall_speed']})[/bold green]")
                        else:
                            self.progress.update(self.overall_task_id, completed=0, fields={'speed': aggregated['overall_speed']}, description=f"[bold green]Overall Progress (Speed: {aggregated['overall_speed']})[/bold green]")
                    else:
                        total_possible_progress = sum(output.get('total', 1) for output in self.parsed_outputs.values() if output)
                        current_total_progress = sum(output.get('current', 0) for output in self.parsed_outputs.values() if output)
                        if total_possible_progress > 0:
                            overall_percentage = int((current_total_progress / total_possible_progress) * 100)
                            self.progress.update(self.overall_task_id, completed=overall_percentage, description="[bold green]Overall Progress[/bold green]")
                        else:
                            self.progress.update(self.overall_task_id, completed=0, description="[bold green]Overall Progress[/bold green]")

                except Exception as e:
                    logging.error(f"Error in aggregator function: {e}")
            else:
                self.progress.update(self.overall_task_id, completed=0, description="[bold green]Overall Progress (Waiting for data...)[/bold green]")
            await asyncio.sleep(0.1)
            if all(status.startswith("✅") or status.startswith("❌") for status in self.task_status.values()):
                break

    async def run_all(self) -> Dict[int, Any]:
        async def user_input():
            while True:
                cmd = await asyncio.to_thread(console.input, "[bold yellow](Type 'pause' to pause, 'resume' to continue, 'quit' to exit)[/bold yellow] > ")
                if cmd.lower() == "pause":
                    self._pause_event.clear()
                    console.print("[bold yellow]Paused all tasks.[/bold yellow]")
                elif cmd.lower() == "resume":
                    self._pause_event.set()
                    console.print("[bold green]Resumed all tasks.[/bold green]")
                elif cmd.lower() == "quit":
                    console.print("[bold red]Exiting...[/bold red]")
                    sys.exit(0)
                await asyncio.sleep(0.1)

        with Live(self.progress, console=console, screen=True, refresh_per_second=10):
            tasks = {
                i: asyncio.create_task(self.run_instance(f"Task {i+1}", self.instance_args[i], i))
                for i in range(len(self.instance_args))
            }
            monitor_task = asyncio.create_task(self.monitor_overall_progress())
            user_input_task = asyncio.create_task(user_input()) if self.allow_pause_resume else None

            results = await asyncio.gather(*tasks.values())

            if user_input_task:
                user_input_task.cancel()
                try:
                    await user_input_task
                except asyncio.CancelledError:
                    pass

            await monitor_task

        console.print(self.progress) # Print the final progress state
        return dict(enumerate(results))  # Return results with instance IDs

    async def run(self) -> Dict[int, Any]:
        """Main entry point to run all tasks."""
        return await self.run_all()
