"""Subprocess-backed LLM CLI adapter."""

from pathlib import Path
import subprocess
import tempfile
import time

from agent_sync.adapters.base import AgentAdapter, WorkerResult
from agent_sync.errors import WorkerError


class CommandAdapter(AgentAdapter):
    """Run a worker through a configured command template."""

    def run(self, prompt: str, *, task_type: str, context_level: str) -> WorkerResult:
        """Run a command-backed worker."""
        if not self.spec.command:
            raise WorkerError(f"Worker '{self.spec.name}' has no command template.")
        start = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="agent-sync-") as temp_dir:
            prompt_file = Path(temp_dir) / "prompt.md"
            prompt_file.write_text(prompt, encoding="utf-8")
            command = [
                part.format(
                    prompt=prompt,
                    prompt_file=str(prompt_file),
                    repo_root=str(self.repo_root),
                    task_type=task_type,
                    context_level=context_level,
                )
                for part in self.spec.command
            ]
            try:
                result = subprocess.run(
                    command,
                    cwd=self.repo_root,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self.spec.timeout_seconds,
                )
            except FileNotFoundError as error:
                raise WorkerError(
                    f"Worker command not found for '{self.spec.name}': {command[0]}. "
                    "Edit .agent_sync/workers.json or install the CLI."
                ) from error
            except subprocess.TimeoutExpired as error:
                duration = time.monotonic() - start
                output = (error.stdout or "") + (error.stderr or "")
                return WorkerResult(
                    worker=self.spec.name,
                    output=output,
                    exit_code=124,
                    duration_seconds=duration,
                    status="timeout",
                    error=f"Timed out after {self.spec.timeout_seconds} seconds.",
                )
        duration = time.monotonic() - start
        output = result.stdout
        if result.stderr:
            output = output + ("\n\n## STDERR\n" if output else "") + result.stderr
        status = "ok" if result.returncode == 0 else "error"
        return WorkerResult(
            worker=self.spec.name,
            output=output,
            exit_code=result.returncode,
            duration_seconds=duration,
            status=status,
            error=None if result.returncode == 0 else f"Worker exited with code {result.returncode}.",
        )
