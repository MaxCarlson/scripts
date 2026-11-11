"""ActionService coordinating capability preparation, challenge verification, atomic execution, and postconditions."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import logging
from typing import Any, Dict, List, Optional
import uuid

from pydantic import ValidationError

from remote_control.actions.models import (
    ActionDefinition,
    ActionExecutionRecord,
    ConfirmationChallenge,
    ConfirmationPolicy,
    ExecutionState,
    PostconditionPolicy,
    StepUpPolicy,
)
from remote_control.actions.permissions import has_permission
from remote_control.actions.registry import ActionRegistry
from remote_control.actions.state_fingerprint import (
    compute_arguments_digest,
    compute_incident_fingerprint,
    compute_rc_fingerprint,
)
from remote_control.actions.storage import ActionStorage
from remote_control.auth.crypto import find_matching_totp_timesteps, hash_token
from remote_control.auth.storage import AuthStorage

logger = logging.getLogger(__name__)


# ── Action Service Exceptions ──────────────────────────────────────────────────


class ActionServiceError(Exception):
    """Base exception for action service operations."""

    def __init__(self, error_code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": False, "error": self.error_code, "message": self.message}


class ActionNotFoundError(ActionServiceError):
    def __init__(self, message: str = "Action not found") -> None:
        super().__init__("action_not_found", message, status_code=404)


class ActionDisabledError(ActionServiceError):
    def __init__(self, message: str = "Capability disabled") -> None:
        super().__init__("capability_disabled", message, status_code=403)


class ActionPermissionDeniedError(ActionServiceError):
    def __init__(self, message: str = "Permission denied") -> None:
        super().__init__("permission_denied", message, status_code=403)


class ActionValidationError(ActionServiceError):
    def __init__(self, message: str = "Validation failed") -> None:
        super().__init__("invalid_parameters", message, status_code=422)


class ChallengeNotFoundError(ActionServiceError):
    def __init__(self, message: str = "Challenge not found") -> None:
        super().__init__("challenge_not_found", message, status_code=404)


class ChallengeExpiredError(ActionServiceError):
    def __init__(self, message: str = "Challenge expired") -> None:
        super().__init__("challenge_expired", message, status_code=400)


class ChallengeConsumedError(ActionServiceError):
    def __init__(self, message: str = "Challenge already consumed") -> None:
        super().__init__("challenge_already_consumed", message, status_code=400)


class ChallengeDeviceMismatchError(ActionServiceError):
    def __init__(self, message: str = "Challenge was issued to a different session or device") -> None:
        super().__init__("challenge_device_mismatch", message, status_code=403)


class StateDriftError(ActionServiceError):
    def __init__(self, message: str = "State drift detected") -> None:
        super().__init__("state_drift_detected", message, status_code=409)


class StepUpAuthenticationError(ActionServiceError):
    def __init__(self, message: str = "Step-up authentication failed") -> None:
        super().__init__("step_up_authentication_failed", message, status_code=401)


# ── Action Service Implementation ─────────────────────────────────────────────


class ActionService:
    """Coordinates capability lookup, challenge management, two-factor step-up,
    atomic idempotency reservation, serialized mutation, and postcondition verification.
    """

    def __init__(
        self,
        storage: ActionStorage,
        registry: ActionRegistry,
        auth_storage: AuthStorage,
    ) -> None:
        self.storage = storage
        self.registry = registry
        self.auth_storage = auth_storage
        self._locks: Dict[str, asyncio.Lock] = {}

    def _get_lock(self, concurrency_key: str) -> asyncio.Lock:
        """Get or create an asyncio lock for a concurrency serialization key."""
        if concurrency_key not in self._locks:
            self._locks[concurrency_key] = asyncio.Lock()
        return self._locks[concurrency_key]

    def _compute_fingerprint_for_module(self, module: str, state: Optional[Dict[str, Any]]) -> str:
        """Route state to appropriate domain fingerprinting function."""
        if module == "resource_coordinator":
            return compute_rc_fingerprint(state)
        elif module == "notifications":
            return compute_incident_fingerprint(state)
        return compute_arguments_digest(state or {})

    # ── Capability Discovery ──────────────────────────────────────────────────

    def list_capabilities(self) -> List[Dict[str, Any]]:
        """Return safe browser-visible descriptions of registered capabilities."""
        return self.registry.list_public_capabilities()

    def get_capability(self, action_id: str) -> Optional[ActionDefinition]:
        """Look up capability definition."""
        return self.registry.get(action_id)

    # ── Action Preparation (Challenge Creation) ───────────────────────────────

    async def prepare_action(
        self,
        action_id: str,
        arguments: Dict[str, Any],
        actor_id: str,
        actor_role: str,
        session_id_hash: str,
        device_id: str,
    ) -> Dict[str, Any]:
        """Validate capability, check permissions, inspect fresh source state,
        compute state fingerprint, and issue an expiring confirmation challenge.
        """
        action_def = self.registry.get(action_id)
        if not action_def:
            raise ActionNotFoundError(f"Capability '{action_id}' is not registered.")

        if not action_def.enabled:
            raise ActionDisabledError(
                action_def.disabled_reason or f"Capability '{action_id}' is disabled."
            )

        if not has_permission(actor_role, action_def.required_permission):
            raise ActionPermissionDeniedError(
                f"Role '{actor_role}' does not have required permission '{action_def.required_permission}'."
            )

        # Validate arguments using capability parameter schema
        try:
            param_model = action_def.parameter_model
            validated_obj = param_model(**arguments)
            validated_args = validated_obj.model_dump()
        except ValidationError as exc:
            raise ActionValidationError(f"Invalid parameters for action '{action_id}': {exc}")

        arguments_digest = compute_arguments_digest(validated_args)

        # Read fresh source state from adapter handler
        handler = self.registry.get_handler(action_id)
        source_state = {}
        if handler and hasattr(handler, "get_source_state"):
            source_state = handler.get_source_state(validated_args) or {}

        state_fingerprint = self._compute_fingerprint_for_module(action_def.module, source_state)
        rc_request_id = source_state.get("active_request_id") if isinstance(source_state, dict) else None

        # Issue 120-second challenge
        challenge_id = f"cld_{uuid.uuid4().hex}"
        now = datetime.now(timezone.utc)
        prepared_at = now.isoformat().replace("+00:00", "Z")
        expires_at = (now + timedelta(seconds=120)).isoformat().replace("+00:00", "Z")

        challenge = ConfirmationChallenge(
            challenge_id=challenge_id,
            operator_id=actor_id,
            session_id_hash=session_id_hash,
            device_id=device_id,
            action_id=action_id,
            action_version=action_def.version,
            arguments_digest=arguments_digest,
            state_fingerprint=state_fingerprint,
            rc_request_id=rc_request_id,
            prepared_at=prepared_at,
            expires_at=expires_at,
            status="pending",
        )

        self.storage.save_challenge(challenge)

        return {
            "ok": True,
            "challenge_id": challenge_id,
            "action_id": action_id,
            "action_label": action_def.label,
            "description": action_def.description,
            "parameters": validated_args,
            "arguments_digest": arguments_digest,
            "state_fingerprint": state_fingerprint,
            "source_state": source_state,
            "prepared_at": prepared_at,
            "expires_at": expires_at,
            "ttl_seconds": 120,
            "requires_totp": action_def.step_up_policy == StepUpPolicy.TOTP,
            "requires_confirmation": action_def.confirmation_policy != ConfirmationPolicy.NONE,
        }

    # ── Action Execution ──────────────────────────────────────────────────────

    async def execute_action(
        self,
        action_id: str,
        challenge_id: Optional[str],
        arguments: Dict[str, Any],
        actor_id: str,
        actor_role: str,
        session_id_hash: str,
        device_id: str,
        idempotency_key: str,
        totp_code: Optional[str] = None,
        ip_address: str = "127.0.0.1",
    ) -> ActionExecutionRecord:
        """Atomically execute a guarded capability with challenge consumption,
        TOTP step-up, state drift detection, concurrency serialization, and postconditions.
        """
        action_def = self.registry.get(action_id)
        if not action_def:
            raise ActionNotFoundError(f"Capability '{action_id}' is not registered.")

        if not action_def.enabled:
            raise ActionDisabledError(
                action_def.disabled_reason or f"Capability '{action_id}' is disabled."
            )

        if not has_permission(actor_role, action_def.required_permission):
            raise ActionPermissionDeniedError(
                f"Role '{actor_role}' does not have required permission '{action_def.required_permission}'."
            )

        # Validate arguments strictly
        try:
            param_model = action_def.parameter_model
            validated_obj = param_model(**arguments)
            validated_args = validated_obj.model_dump()
        except ValidationError as exc:
            raise ActionValidationError(f"Invalid parameters for action '{action_id}': {exc}")

        arguments_digest = compute_arguments_digest(validated_args)
        idempotency_key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()

        # 1. Idempotency Check: return existing execution if already reserved
        existing = self.storage.get_execution_by_idempotency_key(action_id, idempotency_key_hash)
        if existing:
            logger.info("Returning existing execution record for idempotency key hash %s", idempotency_key_hash[:12])
            return existing

        # 2. TOTP Step-Up Authentication (if required)
        if action_def.step_up_policy == StepUpPolicy.TOTP:
            if not totp_code or not totp_code.strip():
                raise StepUpAuthenticationError("Two-factor TOTP verification code is required.")

            op = self.auth_storage.get_operator()
            if not op:
                raise StepUpAuthenticationError("Operator identity not found.")

            matching_timesteps = find_matching_totp_timesteps(op["totp_secret"], totp_code.strip(), valid_window=1)
            if not matching_timesteps:
                raise StepUpAuthenticationError("Invalid two-factor verification code.")

            consumed_step = self.auth_storage.consume_totp_timestep(op["operator_id"], matching_timesteps)
            if consumed_step is None:
                raise StepUpAuthenticationError("TOTP code has already been used. Please wait for the next code.")

        consumed_challenge: Optional[ConfirmationChallenge] = None

        # 3. Challenge Consumption (if confirmation required)
        if action_def.confirmation_policy != ConfirmationPolicy.NONE:
            if not challenge_id:
                raise ActionValidationError("Confirmation challenge_id is required for this action.")

            now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            consumed_ok = self.storage.consume_challenge(
                challenge_id=challenge_id,
                operator_id=actor_id,
                device_id=device_id,
                session_id_hash=session_id_hash,
                action_id=action_id,
                arguments_digest=arguments_digest,
                now_iso=now_iso,
            )

            if not consumed_ok:
                # Inspect stored challenge to throw specific error
                raw_ch = self.storage.get_challenge(challenge_id)
                if not raw_ch:
                    raise ChallengeNotFoundError(f"Confirmation challenge '{challenge_id}' not found.")
                if raw_ch.status == "consumed":
                    raise ChallengeConsumedError("Confirmation challenge has already been used.")
                if raw_ch.session_id_hash != session_id_hash or raw_ch.device_id != device_id:
                    raise ChallengeDeviceMismatchError("Challenge was issued to a different session or device.")
                if raw_ch.arguments_digest != arguments_digest:
                    raise ActionValidationError("Parameters do not match confirmed challenge parameters.")
                if raw_ch.expires_at < now_iso:
                    raise ChallengeExpiredError("Confirmation challenge has expired.")
                raise ActionServiceError("invalid_challenge", "Confirmation challenge could not be consumed.")

            consumed_challenge = self.storage.get_challenge(challenge_id)

        # 4. Fresh State Check & Drift Detection
        handler = self.registry.get_handler(action_id)
        current_state = {}
        if handler and hasattr(handler, "get_source_state"):
            current_state = handler.get_source_state(validated_args) or {}

        current_fingerprint = self._compute_fingerprint_for_module(action_def.module, current_state)

        if consumed_challenge and current_fingerprint != consumed_challenge.state_fingerprint:
            logger.warning(
                "State drift detected for action %s: expected %s, found %s",
                action_id,
                consumed_challenge.state_fingerprint[:12],
                current_fingerprint[:12],
            )
            raise StateDriftError(
                "Source state changed between preparation and confirmation. Please inspect and confirm with fresh state."
            )

        # 5. Atomic Execution Reservation
        execution_id = f"exec_{uuid.uuid4().hex}"
        started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        record = ActionExecutionRecord(
            execution_id=execution_id,
            action_id=action_id,
            action_version=action_def.version,
            actor_id=actor_id,
            session_id_hash=session_id_hash,
            device_id=device_id,
            idempotency_key_hash=idempotency_key_hash,
            arguments_digest=arguments_digest,
            state_fingerprint=current_fingerprint,
            started_at=started_at,
            status=ExecutionState.RESERVED,
        )

        reserved = self.storage.reserve_execution(record)
        if not reserved:
            # Race condition on idempotency key
            existing = self.storage.get_execution_by_idempotency_key(action_id, idempotency_key_hash)
            if existing:
                return existing
            raise ActionServiceError("idempotency_conflict", "Failed to reserve execution record.")

        # 6. Serialized Execution under Concurrency Lock
        lock = self._get_lock(action_def.concurrency_key)
        async with lock:
            finished_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            try:
                if not handler or not hasattr(handler, "execute"):
                    raise RuntimeError(f"No execution handler bound for action '{action_id}'.")

                res = await asyncio.wait_for(
                    handler.execute(validated_args, actor_id=actor_id),
                    timeout=action_def.timeout_seconds,
                )
            except asyncio.TimeoutError:
                logger.error("Execution timed out for action %s (exec_id=%s)", action_id, execution_id)
                self.storage.update_execution(
                    execution_id=execution_id,
                    status=ExecutionState.OUTCOME_UNKNOWN,
                    finished_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    result_category="timeout",
                    error_code="timeout",
                    postcondition_verified=False,
                    summary=f"Action '{action_id}' timed out after {action_def.timeout_seconds}s waiting for subsystem response.",
                )
                self.storage.record_action_audit(
                    actor_id=actor_id,
                    action_id=action_id,
                    execution_id=execution_id,
                    decision="timeout",
                    ip_address=ip_address,
                    details=f"Execution timed out after {action_def.timeout_seconds}s.",
                )
                return self.storage.get_execution(execution_id)  # type: ignore[return-value]
            except Exception as exc:
                logger.error("Adapter exception executing action %s: %s", action_id, exc, exc_info=True)
                self.storage.update_execution(
                    execution_id=execution_id,
                    status=ExecutionState.FAILED,
                    finished_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    result_category="error",
                    error_code="adapter_exception",
                    postcondition_verified=False,
                    summary=f"Adapter error: {exc}",
                )
                self.storage.record_action_audit(
                    actor_id=actor_id,
                    action_id=action_id,
                    execution_id=execution_id,
                    decision="error",
                    ip_address=ip_address,
                    details=f"Adapter exception: {exc}",
                )
                return self.storage.get_execution(execution_id)  # type: ignore[return-value]

            # 7. Evaluate Handler Result
            finished_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            if not res.get("ok"):
                err_code = res.get("error", "execution_failed")
                status = ExecutionState.DENIED if err_code in ("safety_refusal", "capability_disabled") else ExecutionState.FAILED
                summary = res.get("message") or res.get("reason") or f"Action '{action_id}' failed."

                self.storage.update_execution(
                    execution_id=execution_id,
                    status=status,
                    finished_at=finished_at,
                    result_category=err_code,
                    error_code=err_code,
                    postcondition_verified=False,
                    summary=summary,
                    details=res,
                )
                self.storage.record_action_audit(
                    actor_id=actor_id,
                    action_id=action_id,
                    execution_id=execution_id,
                    decision="denied" if status == ExecutionState.DENIED else "failed",
                    ip_address=ip_address,
                    details=f"Failed with {err_code}: {summary}",
                )
                return self.storage.get_execution(execution_id)  # type: ignore[return-value]

            # 8. Postcondition Verification
            postcondition_ok = True
            if action_def.postcondition_policy == PostconditionPolicy.VERIFY_SOURCE_STATE:
                if hasattr(handler, "verify_postcondition"):
                    postcondition_ok = handler.verify_postcondition(validated_args, res)
                else:
                    new_state = handler.get_source_state(validated_args) or {}
                    if action_def.module == "notifications":
                        postcondition_ok = new_state.get("status") in ("acknowledged", "resolved")
                    elif action_def.module == "resource_coordinator":
                        postcondition_ok = (
                            new_state.get("recovery_required") is False
                            and new_state.get("inhibition_active") is False
                        )

            final_status = ExecutionState.SUCCEEDED if postcondition_ok else ExecutionState.POSTCONDITION_UNVERIFIED
            summary = (
                f"Action '{action_id}' executed successfully."
                if postcondition_ok
                else f"Action '{action_id}' completed but postcondition could not be verified."
            )

            self.storage.update_execution(
                execution_id=execution_id,
                status=final_status,
                finished_at=finished_at,
                result_category="success" if postcondition_ok else "postcondition_unverified",
                error_code=None if postcondition_ok else "postcondition_unverified",
                postcondition_verified=postcondition_ok,
                summary=summary,
                details=res,
            )
            self.storage.record_action_audit(
                actor_id=actor_id,
                action_id=action_id,
                execution_id=execution_id,
                decision="allow",
                ip_address=ip_address,
                details=summary,
            )
            return self.storage.get_execution(execution_id)  # type: ignore[return-value]

    # ── Journal Lookup ────────────────────────────────────────────────────────

    def get_execution(self, execution_id: str) -> Optional[ActionExecutionRecord]:
        """Look up an execution record by ID."""
        return self.storage.get_execution(execution_id)

    def list_executions(self, limit: int = 50) -> List[ActionExecutionRecord]:
        """List recent execution records."""
        return self.storage.list_executions(limit=limit)
