"""Observable headless subprocess supervisor and opt-in context propagation."""

from procwatch.runner.context_hook import build_instrumented_env
from procwatch.runner.supervisor import execute

__all__ = [
    "build_instrumented_env",
    "execute",
]