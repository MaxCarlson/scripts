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
    ActionEffect,
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
    redact_sensitive_data,
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

    # ── Read Action Execution ─────────────────────────────────────────────────

    async def execute_read_action(
        self,
        action_id: str,
        arguments: Dict[str, Any],
        actor_id: str,
        actor_role: str,
    ) -> Dict[str, Any]:
        """Directly execute an authenticated read-only capability without burning confirmation challenges or TOTP."""
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

        if action_def.effect != ActionEffect.READ:
            raise ActionValidationError(f"Action '{action_id}' is a mutating action, not a read action.")

        try:
            param_model = action_def.parameter_model
            validated_obj = param_model(**arguments)
            validated_args = validated_obj.model_dump()
        except ValidationError as exc:
            raise ActionValidationError(f"Invalid parameters for action '{action_id}': {exc}")

        handler = self.registry.get_handler(action_id)
        if not handler or not hasattr(handler, "execute"):
            raise RuntimeError(f"No execution handler bound for action '{action_id}'.")

        res = await asyncio.wait_for(
            handler.execute(validated_args, actor_id=actor_id),
            timeout=action_def.timeout_seconds,
        )
        return redact_sensitive_data(res)

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

        # 1. Idempotency Check: return existing execution if already reserved with matching context
        existing = self.storage.get_execution_by_idempotency_key(action_id, idempotency_key_hash)
        if existing:
            if existing.arguments_digest != arguments_digest:
                raise ActionServiceError("idempotency_conflict", "Idempotency key was used with different parameters.", status_code=409)
            if existing.actor_id != actor_id or existing.device_id != device_id:
                raise ActionServiceError("idempotency_conflict", "Idempotency key belongs to a different security context.", status_code=409)
            if existing.action_id != action_id:
                raise ActionServiceError("idempotency_conflict", "Idempotency key was used for a different action.", status_code=409)
            if existing.action_version != action_def.version:
                raise ActionServiceError("idempotency_conflict", "Idempotency key was used for a different action version.", status_code=409)
            logger.info("Returning existing execution record for idempotency key hash %s", idempotency_key_hash[:12])
            return existing

        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # 2. Challenge Pre-validation (Defect F: validate challenge BEFORE consuming TOTP)
        if action_def.confirmation_policy != ConfirmationPolicy.NONE:
            if not challenge_id:
                raise ActionValidationError("Confirmation challenge_id is required for this action.")

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

        # 3. TOTP Step-Up Authentication (if required)
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

        # 4. Atomic Challenge Consumption
        consumed_challenge: Optional[ConfirmationChallenge] = None
        if action_def.confirmation_policy != ConfirmationPolicy.NONE:
            assert challenge_id is not None
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
                raise ActionServiceError("invalid_challenge", "Confirmation challenge could not be consumed.")

            consumed_challenge = self.storage.get_challenge(challenge_id)

        # 5. Atomic Execution Reservation (Defect A: unpack tuple safely)
        execution_id = f"exec_{uuid.uuid4().hex}"
        started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        placeholder_fingerprint = consumed_challenge.state_fingerprint if consumed_challenge else arguments_digest

        record = ActionExecutionRecord(
            execution_id=execution_id,
            action_id=action_id,
            action_version=action_def.version,
            actor_id=actor_id,
            session_id_hash=session_id_hash,
            device_id=device_id,
            idempotency_key_hash=idempotency_key_hash,
            arguments_digest=arguments_digest,
            state_fingerprint=placeholder_fingerprint,
            started_at=started_at,
            status=ExecutionState.RESERVED,
        )

        created, existing_or_new = self.storage.reserve_execution(record)
        if not created:
            # Race condition on idempotency key: validate matching context
            if existing_or_new.arguments_digest != arguments_digest:
                raise ActionServiceError("idempotency_conflict", "Idempotency key was used with different parameters.", status_code=409)
            if existing_or_new.actor_id != actor_id or existing_or_new.device_id != device_id:
                raise ActionServiceError("idempotency_conflict", "Idempotency key belongs to a different security context.", status_code=409)
            if existing_or_new.action_id != action_id:
                raise ActionServiceError("idempotency_conflict", "Idempotency key was used for a different action.", status_code=409)
            if existing_or_new.action_version != action_def.version:
                raise ActionServiceError("idempotency_conflict", "Idempotency key was used for a different action version.", status_code=409)
            return existing_or_new

        handler = self.registry.get_handler(action_id)

        # 6. Serialized Execution under Concurrency Lock & Cross-Process Resource Lease (Defect C)
        lock = self._get_lock(action_def.concurrency_key)
        async with lock:
            # Acquire durable cross-process lock
            lock_acquired = False
            start_lock = asyncio.get_event_loop().time()
            lock_wait_timeout = min(5.0, float(action_def.timeout_seconds))
            while asyncio.get_event_loop().time() - start_lock < lock_wait_timeout:
                if self.storage.acquire_resource_lock(
                    action_def.concurrency_key,
                    execution_id,
                    ttl_seconds=action_def.timeout_seconds + 5.0,
                ):
                    lock_acquired = True
                    break
                await asyncio.sleep(0.05)

            if not lock_acquired:
                self.storage.update_execution(
                    execution_id=execution_id,
                    status=ExecutionState.FAILED,
                    finished_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    result_category="lock_contention",
                    error_code="lock_contention",
                    summary=f"Could not acquire lock for concurrency key '{action_def.concurrency_key}'.",
                )
                raise ActionServiceError(
                    "lock_contention",
                    f"Resource '{action_def.concurrency_key}' is locked by another operation.",
                    status_code=409,
                )

            try:
                # Fresh State Check & Drift Detection INSIDE the lock boundary (TOCTOU elimination)
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
                    self.storage.update_execution(
                        execution_id=execution_id,
                        status=ExecutionState.DENIED,
                        finished_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                        result_category="state_drift",
                        error_code="state_drift_detected",
                        summary="Source state changed between preparation and confirmation.",
                    )
                    self.storage.record_action_audit(
                        actor_id=actor_id,
                        action_id=action_id,
                        execution_id=execution_id,
                        decision="denied",
                        ip_address=ip_address,
                        details="State drift detected inside execution boundary.",
                    )
                    raise StateDriftError(
                        "Source state changed between preparation and confirmation. Please inspect and confirm with fresh state."
                    )

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
                    sanitized_err = redact_sensitive_data(str(exc))
                    bounded_summary = f"Adapter error: {sanitized_err}"[:256]
                    self.storage.update_execution(
                        execution_id=execution_id,
                        status=ExecutionState.FAILED,
                        finished_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                        result_category="error",
                        error_code="adapter_exception",
                        postcondition_verified=False,
                        summary=bounded_summary,
                    )
                    self.storage.record_action_audit(
                        actor_id=actor_id,
                        action_id=action_id,
                        execution_id=execution_id,
                        decision="error",
                        ip_address=ip_address,
                        details={"error": sanitized_err},
                    )
                    return self.storage.get_execution(execution_id)  # type: ignore[return-value]

                # 7. Evaluate Handler Result
                finished_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                if not res.get("ok"):
                    err_code = res.get("error", "execution_failed")
                    status = ExecutionState.DENIED if err_code in ("safety_refusal", "capability_disabled") else ExecutionState.FAILED
                    raw_summary = res.get("message") or res.get("reason") or f"Action '{action_id}' failed."
                    summary = redact_sensitive_data(raw_summary)[:256]

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
            finally:
                self.storage.release_resource_lock(action_def.concurrency_key, execution_id)

    # ── Journal Lookup ────────────────────────────────────────────────────────

    def get_execution(self, execution_id: str) -> Optional[ActionExecutionRecord]:
        """Look up an execution record by ID."""
        return self.storage.get_execution(execution_id)

    def list_executions(self, limit: int = 50) -> List[ActionExecutionRecord]:
        """List recent execution records."""
        return self.storage.list_executions(limit=limit)
