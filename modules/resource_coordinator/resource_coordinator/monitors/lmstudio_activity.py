"""Optional read-only LM Studio activity observer contract.

No subprocess or network probe is enabled by default: upstream documentation does not
guarantee that querying an absent LM Studio runtime cannot wake it.
"""

from __future__ import annotations

from typing import Any, Dict, Protocol


class LMStudioActivityObserver(Protocol):
    async def observe(self, *, runtime_identity: Dict[str, Any]) -> Dict[str, Any]:
        """Return bounded observational evidence; never mutate the runtime."""


class UnavailableLMStudioActivityObserver:
    """Safe default until a no-wake, instance-bound probe is qualified."""

    async def observe(self, *, runtime_identity: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "unavailable", "coverage": "unknown",
                "reason_code": "no_wake_probe_not_qualified", "runtime_identity": runtime_identity}
