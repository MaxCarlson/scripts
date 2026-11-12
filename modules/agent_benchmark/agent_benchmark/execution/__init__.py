"""Execution backend abstraction, direct chat client, and scoring adapters."""

from __future__ import annotations

from .contract import (
    BackendAttempt,
    ExecutionBackend,
    ExecutionPlan,
    ResultNormalizer,
    ScoredAttempt,
    ScoringAdapter,
    TaskContext,
)
from .direct_chat import DirectChatBackend, validate_endpoint_url
from .harbor_backend import HarborExecutionBackend
from .mock_backend import MockExecutionBackend, MockScoringAdapter
from .registry import get_backend, get_scorer, register_backend, register_scorer

__all__ = [
    "BackendAttempt",
    "DirectChatBackend",
    "ExecutionBackend",
    "ExecutionPlan",
    "HarborExecutionBackend",
    "MockExecutionBackend",
    "MockScoringAdapter",
    "ResultNormalizer",
    "ScoredAttempt",
    "ScoringAdapter",
    "TaskContext",
    "get_backend",
    "get_scorer",
    "register_backend",
    "register_scorer",
    "validate_endpoint_url",
]
