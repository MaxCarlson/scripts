"""Permission validation for remote control actions."""

from __future__ import annotations

from typing import Set

# Single-operator model with standard roles
ROLE_PERMISSIONS: dict[str, Set[str]] = {
    "operator": {
        "operator.read",
        "operator.action",
    },
    "admin": {
        "operator.read",
        "operator.action",
        "operator.admin",
    },
}


def has_permission(user_role: str, required_permission: str) -> bool:
    """Check if user role has the required permission."""
    if user_role == required_permission:
        return True
    perms = ROLE_PERMISSIONS.get(user_role, set())
    return required_permission in perms
