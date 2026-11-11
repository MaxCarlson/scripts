"""Notifications action adapters (health, incident detail, and incident acknowledgement)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from notifications.exceptions import IncidentNotFoundError, InvalidTransitionError
from notifications.lifecycle import IncidentLifecycleEngine
from notifications.storage import StorageEngine

logger = logging.getLogger(__name__)


class NotificationsHealthAdapter:
    """Read adapter for notifications.health."""

    def __init__(self, notifications_adapter: Any) -> None:
        self.notifications_adapter = notifications_adapter

    async def execute(self, params: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        """Fetch storage and broker operational health."""
        summary = self.notifications_adapter.get_summary()
        return {
            "ok": True,
            "status": "healthy",
            "summary": summary,
        }


class NotificationsIncidentDetailAdapter:
    """Read adapter for notifications.incident_detail."""

    def __init__(self, notifications_adapter: Any) -> None:
        self.notifications_adapter = notifications_adapter

    async def execute(self, params: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        """Fetch full details and event history for a specific incident."""
        incident_id = params.get("incident_id")
        if not incident_id:
            return {"ok": False, "error": "missing_incident_id", "message": "Incident ID is required."}

        detail = self.notifications_adapter.get_incident(incident_id)
        if not detail:
            return {"ok": False, "error": "incident_not_found", "message": f"Incident '{incident_id}' not found."}

        return {
            "ok": True,
            "incident": detail,
        }


class NotificationsAcknowledgeAdapter:
    """Mutation adapter for notifications.acknowledge_incident.

    Acknowledges an active incident in the Notifications lifecycle.
    Guarantees: Never triggers Resource Coordinator recovery and never clears safety inhibition.
    """

    def __init__(self, db_path: Any) -> None:
        self.db_path = db_path

    def get_source_state(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Fetch current incident state for canonical fingerprinting."""
        incident_id = params.get("incident_id")
        if not incident_id:
            return None
        storage = StorageEngine(self.db_path)
        incident = storage.get_incident(incident_id)
        if not incident:
            return None
        return {
            "incident_id": incident.incident_id,
            "status": incident.status,
            "occurrence_count": incident.occurrence_count,
            "last_occurred_at": getattr(incident, "last_seen", None),
        }

    def verify_postcondition(self, params: Dict[str, Any], result: Dict[str, Any]) -> bool:
        """Verify incident transitioned to acknowledged or resolved."""
        if not result.get("ok"):
            return False
        state = self.get_source_state(params)
        return state is not None and state.get("status") in ("acknowledged", "resolved")

    async def execute(self, params: Dict[str, Any], actor_id: str = "operator", **kwargs: Any) -> Dict[str, Any]:
        incident_id = params["incident_id"]
        reason = params.get("reason")

        storage = StorageEngine(self.db_path)
        lifecycle = IncidentLifecycleEngine(storage)

        try:
            updated = lifecycle.acknowledge_incident(
                incident_id=incident_id,
                actor=actor_id,
                reason=reason,
            )
            return {
                "ok": True,
                "incident_id": updated.incident_id,
                "status": updated.status,
                "acknowledged_at": updated.acknowledged_at,
                "acknowledged_by": actor_id,
                "acknowledgement_reason": reason,
            }
        except IncidentNotFoundError:
            return {
                "ok": False,
                "error": "incident_not_found",
                "message": f"Incident '{incident_id}' does not exist.",
            }
        except InvalidTransitionError as exc:
            return {
                "ok": False,
                "error": "invalid_transition",
                "message": str(exc),
            }
        except Exception as exc:
            logger.error("Error acknowledging incident %s: %s", incident_id, exc, exc_info=True)
            return {
                "ok": False,
                "error": "internal_error",
                "message": "Failed acknowledging incident.",
            }
