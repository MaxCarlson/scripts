"""Command group parsers and handlers for agent-benchmark CLI."""

from .experiment import add_experiment_parser, handle_experiment
from .external import add_external_parser, handle_external
from .models import add_models_parser, handle_models
from .setup import add_setup_parser, handle_setup
from .suite import add_suite_parser, handle_suite
from .task import add_root_task_parsers, add_task_parser, handle_task

__all__ = [
    "add_experiment_parser",
    "add_external_parser",
    "add_models_parser",
    "add_root_task_parsers",
    "add_setup_parser",
    "add_suite_parser",
    "add_task_parser",
    "handle_experiment",
    "handle_external",
    "handle_models",
    "handle_setup",
    "handle_suite",
    "handle_task",
]
