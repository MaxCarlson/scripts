"""Registry for benchmark execution backends and scoring adapters."""

from __future__ import annotations

from typing import Callable

from .contract import ExecutionBackend, ScoringAdapter
from .direct_chat import DirectChatBackend
from .harbor_backend import HarborExecutionBackend
from .mock_backend import MockExecutionBackend, MockScoringAdapter

_BACKENDS: dict[str, Callable[[], ExecutionBackend]] = {
    "direct_chat": DirectChatBackend,
    "mock": MockExecutionBackend,
    "harbor": HarborExecutionBackend,
}

_SCORERS: dict[str, Callable[[], ScoringAdapter]] = {
    "mock_scorer": MockScoringAdapter,
}


def register_backend(backend_id: str, factory: Callable[[], ExecutionBackend]) -> None:
    """Register a new execution backend factory under a unique ID."""
    _BACKENDS[backend_id] = factory


def get_backend(backend_id: str) -> ExecutionBackend:
    """Resolve an execution backend by its registered identifier."""
    factory = _BACKENDS.get(backend_id)
    if factory is None:
        raise KeyError(f"Unknown execution backend: {backend_id!r}. Registered: {sorted(_BACKENDS)}")
    return factory()


def register_scorer(scorer_id: str, factory: Callable[[], ScoringAdapter]) -> None:
    """Register an authoritative scoring adapter factory under a unique ID."""
    _SCORERS[scorer_id] = factory


def get_scorer(scorer_id: str) -> ScoringAdapter:
    """Resolve a scoring adapter by its registered identifier."""
    if scorer_id not in _SCORERS:
        if scorer_id == "ifeval_official":
            from ..benchmarks.adapters.ifeval import IFEvalScoringAdapter

            return IFEvalScoringAdapter()
        elif scorer_id == "lcb_official":
            from ..benchmarks.adapters.livecodebench import LCBScoringAdapter

            return LCBScoringAdapter()
    factory = _SCORERS.get(scorer_id)
    if factory is None:
        raise KeyError(f"Unknown scoring adapter: {scorer_id!r}. Registered: {sorted(_SCORERS)}")
    return factory()
