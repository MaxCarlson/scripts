"""Pydantic models and schemas for the typed action and capability registry."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel, ConfigDict, Field


class ActionEffect(str, Enum):
    READ = "read"
    MUTATION = "mutation"


class ConfirmationPolicy(str, Enum):
    NONE = "none"
    EXPLICIT_CHALLENGE = "explicit_challenge"


class StepUpPolicy(str, Enum):
    NONE = "none"
    TOTP = "totp"


class PostconditionPolicy(str, Enum):
    NONE = "none"
    VERIFY_SOURCE_STATE = "verify_source_state"


class ExecutionState(str, Enum):
    PREPARED = "prepared"
    AUTHORIZED = "authorized"
    RESERVED = "reserved"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    DENIED = "denied"
    FAILED = "failed"
    OUTCOME_UNKNOWN = "outcome_unknown"
    POSTCONDITION_UNVERIFIED = "postcondition_unverified"


class DispatchPhase(str, Enum):
    RESERVED_NOT_DISPATCHED = "reserved_not_dispatched"
    DISPATCH_POSSIBLE = "dispatch_possible"
    DISPATCH_STARTED = "dispatch_started"
    OUTCOME_UNKNOWN = "outcome_unknown"
    POSTCONDITION_VERIFIED = "postcondition_verified"
    TERMINAL_WITHOUT_DISPATCH = "terminal_without_dispatch"


class ActionParameterSchema(BaseModel):
    """Base class for all action parameter schemas. Rejects arbitrary/extra fields."""

    model_config = ConfigDict(extra="forbid")


class EmptyParameters(ActionParameterSchema):
    """Parameter schema for actions that take no arguments."""

    pass


class AcknowledgeIncidentParameters(ActionParameterSchema):
    """Typed parameters for acknowledging a notification incident."""

    incident_id: str = Field(..., min_length=1, max_length=128, description="Target incident identifier")
    reason: Optional[str] = Field(None, max_length=256, description="Optional operator reason for acknowledgement")


class GuardedRecoveryParameters(ActionParameterSchema):
    """Typed parameters for Resource Coordinator guarded recovery."""

    resource: str = Field(default="gpu.inference", min_length=1, max_length=64, description="Target resource name")
    reason: str = Field(..., min_length=3, max_length=256, description="Operator reason for requesting recovery")


class ActionDefinition(BaseModel):
    """Typed, code-owned specification for a registered capability."""

    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(..., description="Unique stable capability identifier")
    version: str = Field(default="1.0.0", description="Semantic version of capability contract")
    label: str = Field(..., description="Human-readable title")
    description: str = Field(..., description="Human-readable operational description")
    module: str = Field(..., description="Owning module (e.g. 'resource_coordinator', 'notifications')")
    effect: ActionEffect = Field(..., description="Read or mutation effect")
    required_permission: str = Field(default="operator.action", description="Required permission role")
    parameter_model: Type[ActionParameterSchema] = Field(default=EmptyParameters, description="Pydantic model for parameter validation")
    timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0, description="Execution timeout limit in seconds")
    max_output_bytes: int = Field(default=65536, ge=1024, le=1048576, description="Maximum output size limit")
    freshness_required_seconds: float = Field(default=30.0, ge=1.0, le=300.0, description="Required freshness of source state")
    concurrency_key: str = Field(..., description="Key for per-resource serialization locking")
    idempotency_scope: str = Field(default="action:args", description="Scope for idempotency uniqueness")
    confirmation_policy: ConfirmationPolicy = Field(default=ConfirmationPolicy.NONE, description="Confirmation policy requirement")
    step_up_policy: StepUpPolicy = Field(default=StepUpPolicy.NONE, description="Step-up authentication policy")
    postcondition_policy: PostconditionPolicy = Field(default=PostconditionPolicy.NONE, description="Postcondition verification policy")
    enabled: bool = Field(default=True, description="Whether the capability is enabled for production execution")
    disabled_reason: Optional[str] = Field(None, description="Explanation if capability is disabled in production")

    def to_public_dict(self) -> Dict[str, Any]:
        """Return safe, browser-visible capability representation."""
        # Intentionally exclude raw internal handler references
        return {
            "action_id": self.action_id,
            "version": self.version,
            "label": self.label,
            "description": self.description,
            "module": self.module,
            "effect": self.effect.value,
            "required_permission": self.required_permission,
            "timeout_seconds": self.timeout_seconds,
            "confirmation_required": self.confirmation_policy != ConfirmationPolicy.NONE,
            "step_up_required": self.step_up_policy != StepUpPolicy.NONE,
            "enabled": self.enabled,
            "disabled_reason": self.disabled_reason,
            "parameters_schema": self.parameter_model.model_json_schema() if self.parameter_model else {},
        }


class ConfirmationChallenge(BaseModel):
    """Durable confirmation challenge record."""

    model_config = ConfigDict(extra="forbid")

    challenge_id: str
    operator_id: str
    session_id_hash: str
    device_id: str
    action_id: str
    action_version: str
    arguments_digest: str
    state_fingerprint: str
    rc_request_id: Optional[str] = None
    prepared_at: str
    expires_at: str
    status: str = "pending"  # "pending", "consumed", "expired", "rejected"
    rejection_reason: Optional[str] = None


class ActionExecutionRecord(BaseModel):
    """Durable action execution journal record."""

    model_config = ConfigDict(extra="forbid")

    execution_id: str
    action_id: str
    action_version: str
    actor_id: str
    session_id_hash: str
    device_id: str
    idempotency_key_hash: str
    arguments_digest: str
    state_fingerprint: str
    started_at: str
    finished_at: Optional[str] = None
    status: ExecutionState
    result_category: Optional[str] = None
    error_code: Optional[str] = None
    postcondition_verified: bool = False
    summary: str = ""
    details_json: Optional[str] = None
    dispatch_phase: str = DispatchPhase.RESERVED_NOT_DISPATCHED.value
