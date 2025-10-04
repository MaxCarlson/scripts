"""Setup utilities for module installation and configuration."""

from .dependency_resolver import DependencyResolver, resolve_module_order

__all__ = ['DependencyResolver', 'resolve_module_order']
