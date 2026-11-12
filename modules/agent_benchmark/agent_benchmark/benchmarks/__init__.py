"""Unified benchmark catalog, descriptors, and selection protocols."""

from .catalog import BenchmarkCatalog, get_default_catalog, get_unified_discovery
from .schema import (
    BackendDescriptor,
    BenchmarkDescriptor,
    CohortDescriptor,
    DatasetDescriptor,
    ResourceDeclaration,
    ScorerDescriptor,
)
from .selection import select_tasks

__all__ = [
    "BackendDescriptor",
    "BenchmarkCatalog",
    "BenchmarkDescriptor",
    "CohortDescriptor",
    "DatasetDescriptor",
    "ResourceDeclaration",
    "ScorerDescriptor",
    "get_default_catalog",
    "get_unified_discovery",
    "select_tasks",
]
