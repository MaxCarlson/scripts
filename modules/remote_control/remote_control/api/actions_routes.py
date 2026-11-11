"""Guarded action execution, challenge confirmation, and execution journal API routes."""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from remote_control.actions.models import ActionDefinition, ActionEffect, ActionExecutionRecord
from remote_control.actions.service import (
    ActionDisabledError,
    ActionNotFoundError,
    ActionPermissionDeniedError,
    ActionService,
    ActionServiceError,
    ActionValidationError,
    ChallengeConsumedError,
    ChallengeDeviceMismatchError,
    ChallengeExpiredError,
    ChallengeNotFoundError,
    StateDriftError,
    StepUpAuthenticationError,
)
from remote_control.api.dependencies import get_client_ip, get_current_session, verify_csrf
from remote_control.models import SessionModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["actions"])


# ── Request / Response Models ──────────────────────────────────────────────────


class PrepareActionRequest(BaseModel):
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Action arguments")


class ExecuteActionRequest(BaseModel):
    challenge_id: Optional[str] = Field(None, description="Confirmation challenge ID if required")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Action arguments")
    totp_code: Optional[str] = Field(None, description="TOTP code for step-up authentication")
    idempotency_key: Optional[str] = Field(None, description="Client idempotency key")


class AcknowledgeIncidentRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=256, description="Operator reason for acknowledgement")
    totp_code: Optional[str] = Field(None, description="TOTP code for step-up authentication")
    challenge_id: Optional[str] = Field(None, description="Pre-prepared confirmation challenge if available")


def get_action_service(request: Request) -> ActionService:
    """Dependency provider for ActionService."""
    service = getattr(request.app.state, "action_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"ok": False, "error": "service_unavailable", "message": "Action service is not initialized."},
        )
    return service


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get("/capabilities")
async def list_capabilities(
    session: SessionModel = Depends(get_current_session),
    action_service: ActionService = Depends(get_action_service),
) -> Dict[str, Any]:
    """List registered capabilities and their parameter schemas for mobile browser display."""
    caps = action_service.list_capabilities()
    return {
        "ok": True,
        "capabilities": caps,
    }


@router.get("/capabilities/{action_id}")
async def get_capability(
    action_id: str,
    session: SessionModel = Depends(get_current_session),
    action_service: ActionService = Depends(get_action_service),
) -> Dict[str, Any]:
    """Retrieve metadata and schema for a specific capability."""
    cap = action_service.get_capability(action_id)
    if not cap:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"ok": False, "error": "action_not_found", "message": f"Action '{action_id}' not found."},
        )
    return {
        "ok": True,
        "capability": cap.to_public_dict(),
    }


@router.post("/actions/{action_id}/prepare", dependencies=[Depends(verify_csrf)])
async def prepare_action(
    action_id: str,
    payload: PrepareActionRequest,
    session: SessionModel = Depends(get_current_session),
    action_service: ActionService = Depends(get_action_service),
) -> Dict[str, Any]:
    """Inspect fresh source state and generate an expiring confirmation challenge."""
    session_id_hash = hashlib.sha256(session.session_id.encode("utf-8")).hexdigest()

    try:
        challenge_resp = await action_service.prepare_action(
            action_id=action_id,
            arguments=payload.parameters,
            actor_id=session.operator_id,
            actor_role="operator",  # default operator role
            session_id_hash=session_id_hash,
            device_id=session.device_id,
        )
        return challenge_resp
    except ActionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.to_dict())
    except (ActionDisabledError, ActionPermissionDeniedError) as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.to_dict())
    except ActionValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.to_dict())
    except ActionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_dict())


@router.post("/actions/{action_id}/execute", dependencies=[Depends(verify_csrf)])
async def execute_action(
    action_id: str,
    payload: ExecuteActionRequest,
    request: Request,
    session: SessionModel = Depends(get_current_session),
    action_service: ActionService = Depends(get_action_service),
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
) -> Dict[str, Any]:
    """Execute an action with challenge consumption, step-up TOTP, and postconditions."""
    action_def = action_service.get_capability(action_id)
    if not action_def:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"ok": False, "error": "action_not_found", "message": f"Action '{action_id}' not found."},
        )

    # Direct execution path for authenticated read actions without burning challenges or TOTP (Defect E)
    if action_def.effect == ActionEffect.READ:
        try:
            read_result = await action_service.execute_read_action(
                action_id=action_id,
                arguments=payload.parameters,
                actor_id=session.operator_id,
                actor_role="operator",
            )
            return {
                "ok": True,
                "action_id": action_id,
                "read_only": True,
                "result": read_result,
            }
        except ActionNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.to_dict())
        except (ActionDisabledError, ActionPermissionDeniedError) as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.to_dict())
        except ActionValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.to_dict())
        except ActionServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.to_dict())

    session_id_hash = hashlib.sha256(session.session_id.encode("utf-8")).hexdigest()
    client_ip = get_client_ip(request)

    eff_idempotency_key = payload.idempotency_key or x_idempotency_key or f"idem_{uuid.uuid4().hex}"

    try:
        record = await action_service.execute_action(
            action_id=action_id,
            challenge_id=payload.challenge_id,
            arguments=payload.parameters,
            actor_id=session.operator_id,
            actor_role="operator",
            session_id_hash=session_id_hash,
            device_id=session.device_id,
            idempotency_key=eff_idempotency_key,
            totp_code=payload.totp_code,
            ip_address=client_ip,
        )

        return {
            "ok": True,
            "execution": {
                "execution_id": record.execution_id,
                "action_id": record.action_id,
                "action_version": record.action_version,
                "status": record.status.value,
                "started_at": record.started_at,
                "finished_at": record.finished_at,
                "result_category": record.result_category,
                "error_code": record.error_code,
                "postcondition_verified": record.postcondition_verified,
                "summary": record.summary,
                "details": record.details_json,
            },
        }
    except ActionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.to_dict())
    except (ActionDisabledError, ActionPermissionDeniedError, ChallengeDeviceMismatchError) as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.to_dict())
    except StepUpAuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=exc.to_dict())
    except StateDriftError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.to_dict())
    except ActionValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.to_dict())
    except ActionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_dict())


@router.get("/executions/{execution_id}")
async def get_execution_record(
    execution_id: str,
    session: SessionModel = Depends(get_current_session),
    action_service: ActionService = Depends(get_action_service),
) -> Dict[str, Any]:
    """Retrieve durable execution journal record."""
    record = action_service.get_execution(execution_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"ok": False, "error": "execution_not_found", "message": f"Execution '{execution_id}' not found."},
        )
    return {
        "ok": True,
        "execution": {
            "execution_id": record.execution_id,
            "action_id": record.action_id,
            "action_version": record.action_version,
            "status": record.status.value,
            "started_at": record.started_at,
            "finished_at": record.finished_at,
            "result_category": record.result_category,
            "error_code": record.error_code,
            "postcondition_verified": record.postcondition_verified,
            "summary": record.summary,
            "details": record.details_json,
        },
    }


@router.get("/executions")
async def list_executions(
    session: SessionModel = Depends(get_current_session),
    action_service: ActionService = Depends(get_action_service),
) -> Dict[str, Any]:
    """List recent execution journal records."""
    records = action_service.list_executions(limit=50)
    return {
        "ok": True,
        "executions": [
            {
                "execution_id": r.execution_id,
                "action_id": r.action_id,
                "action_version": r.action_version,
                "status": r.status.value,
                "started_at": r.started_at,
                "finished_at": r.finished_at,
                "result_category": r.result_category,
                "error_code": r.error_code,
                "postcondition_verified": r.postcondition_verified,
                "summary": r.summary,
            }
            for r in records
        ],
    }


# ── Convenience Incident Acknowledge Route ───────────────────────────────────


@router.post("/incidents/{incident_id}/acknowledge", dependencies=[Depends(verify_csrf)])
async def acknowledge_incident(
    incident_id: str,
    payload: AcknowledgeIncidentRequest,
    request: Request,
    session: SessionModel = Depends(get_current_session),
    action_service: ActionService = Depends(get_action_service),
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
) -> Dict[str, Any]:
    """Dedicated endpoint to acknowledge an incident via the guarded action workflow."""
    session_id_hash = hashlib.sha256(session.session_id.encode("utf-8")).hexdigest()
    client_ip = get_client_ip(request)
    action_id = "notifications.acknowledge_incident"
    parameters = {"incident_id": incident_id, "reason": payload.reason}

    # Elimination of auto-preparation bypass (Defect B): require pre-issued challenge_id
    challenge_id = payload.challenge_id
    if not challenge_id or not challenge_id.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "ok": False,
                "error": "challenge_required",
                "message": "Confirmation challenge_id is required. Pre-issue challenge via prepare before execution.",
            },
        )

    # Scope idempotency key by challenge_id so reopened incidents don't collide
    eff_idempotency_key = x_idempotency_key or f"ack_{incident_id}_{challenge_id[:16]}"

    try:
        record = await action_service.execute_action(
            action_id=action_id,
            challenge_id=challenge_id,
            arguments=parameters,
            actor_id=session.operator_id,
            actor_role="operator",
            session_id_hash=session_id_hash,
            device_id=session.device_id,
            idempotency_key=eff_idempotency_key,
            totp_code=payload.totp_code,
            ip_address=client_ip,
        )

        return {
            "ok": record.status == "succeeded",
            "incident_id": incident_id,
            "execution_id": record.execution_id,
            "status": record.status.value,
            "postcondition_verified": record.postcondition_verified,
            "summary": record.summary,
            "details": record.details_json,
        }
    except ActionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.to_dict())
    except (ActionDisabledError, ActionPermissionDeniedError, ChallengeDeviceMismatchError) as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.to_dict())
    except StepUpAuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=exc.to_dict())
    except StateDriftError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.to_dict())
    except ActionValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.to_dict())
    except ActionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_dict())
