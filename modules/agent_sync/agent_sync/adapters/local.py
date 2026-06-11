"""Local LM Studio worker adapter via scripts/modules/llm_local."""

import time

from agent_sync.adapters.base import AgentAdapter, WorkerResult
from agent_sync.errors import WorkerError


class LocalAdapter(AgentAdapter):
    """Run a local LM Studio/OpenAI-compatible worker through llm_local."""

    def run(self, prompt: str, *, task_type: str, context_level: str) -> WorkerResult:
        """Run the local model worker."""
        del task_type, context_level
        try:
            from llm_local.client import complete
        except ImportError as error:
            raise WorkerError(
                "Local worker requires scripts/modules/llm_local to be installed. "
                "Install llm-local or choose a command-backed worker."
            ) from error
        start = time.monotonic()
        output = complete(
            prompt,
            model=self.spec.model,
            url=self.spec.local_url,
            timeout=self.spec.timeout_seconds,
            system="You are a delegated local LLM worker. Return concise, structured Markdown.",
        )
        duration = time.monotonic() - start
        if output is None:
            return WorkerResult(
                worker=self.spec.name,
                output="",
                exit_code=None,
                duration_seconds=duration,
                status="error",
                error="llm_local returned no output. Verify LM Studio is running and has a model loaded.",
            )
        return WorkerResult(
            worker=self.spec.name,
            output=output,
            exit_code=0,
            duration_seconds=duration,
            status="ok",
        )
