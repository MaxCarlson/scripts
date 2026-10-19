"""
Centralized request classification and admission controller for LM Studio gateway.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Set

from resource_coordinator.core.events import EventDispatcher
from resource_coordinator.core.leases import LeaseType
from resource_coordinator.core.service import CoordinatorService, ServiceState

logger = logging.getLogger(__name__)


class OperationKind(str, Enum):
    """Classification of an incoming HTTP request."""

    METADATA_READ = "metadata_read"  # Harmless read/inspection (e.g. GET /v1/models)
    INFERENCE = "inference"  # Protected active token generation (e.g. POST /v1/chat/completions)
    MODEL_LOAD = "model_load"  # Protected model load (POST /api/v0/model/load)
    MODEL_MUTATION = "model_mutation"  # Unsupported model unload or other managed mutation
    INTERNAL_COORDINATOR = "internal_coordinator"  # Built-in coordinator endpoints (/_coordinator/*)
    UNSUPPORTED_MUTATING = "unsupported_mutating"  # Uncoordinated state-mutating requests (fail closed)
    UNKNOWN_READ = "unknown_read"  # Unrecognized GET/HEAD/OPTIONS request


KNOWN_INFERENCE_PATHS: Set[str] = {
    "/v1/chat/completions",
    "/v1/completions",
    "/v1/embeddings",
    "/v1/responses",
    "/v1/messages",
    "/api/v0/chat/completions",
    "/api/v0/completions",
    "/api/v0/embeddings",
    "/api/v1/chat",
}

MODEL_LOAD_PATHS: Set[str] = {
    "/api/v0/model/load",
    "/api/v1/models/load",
}
KNOWN_MODEL_MUTATION_PATHS: Set[str] = {
    "/api/v0/model/unload",
    "/api/v1/models/unload",
}

KNOWN_METADATA_PATHS: Set[str] = {
    "/v1/models",
    "/api/v0/models",
    "/api/v1/models",
}


class OperationClassifier:
    """Classifies incoming HTTP requests into well-defined OperationKind categories."""

    @staticmethod
    def classify(method: str, path: str) -> OperationKind:
        m = method.upper()
        norm_path = "/" + path.strip("/") if path else "/"

        # 1. Internal coordinator endpoints
        if norm_path.startswith("/_coordinator/"):
            return OperationKind.INTERNAL_COORDINATOR

        # 2. Inference endpoints
        if m == "POST":
            if norm_path in KNOWN_INFERENCE_PATHS:
                return OperationKind.INFERENCE

            if norm_path in MODEL_LOAD_PATHS:
                return OperationKind.MODEL_LOAD

            # 3. Model unload remains unsupported pending coordinated teardown.
            if norm_path in KNOWN_MODEL_MUTATION_PATHS:
                return OperationKind.MODEL_MUTATION

            # Any other POST is an unsupported mutating endpoint
            return OperationKind.UNSUPPORTED_MUTATING

        # 4. State-mutating non-POST methods (PUT, DELETE, PATCH)
        if m in {"PUT", "DELETE", "PATCH"}:
            return OperationKind.UNSUPPORTED_MUTATING

        # 5. Read-only methods (GET, HEAD, OPTIONS)
        if m in {"GET", "HEAD", "OPTIONS"}:
            if (
                norm_path in KNOWN_METADATA_PATHS
                or norm_path == "/"
                or any(
                    norm_path.startswith(prefix) and "/" not in norm_path[len(prefix) :]
                    for prefix in ("/v1/models/", "/api/v0/models/")
                )
            ):
                return OperationKind.METADATA_READ
            return OperationKind.UNKNOWN_READ

        return OperationKind.UNSUPPORTED_MUTATING


@dataclass(frozen=True)
class AdmissionDecision:
    """Result of evaluating a request against the admission controller."""

    allowed: bool
    status_code: int = 200
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    operation_kind: OperationKind = OperationKind.UNKNOWN_READ
    resource: Optional[str] = None
    lease_type: Optional[LeaseType] = None
    event_name: Optional[str] = None
    finish_event: Optional[str] = None


class AdmissionController:
    """
    Central admission gate evaluating service readiness, endpoint classification,
    and coordination pre-conditions.
    """

    def __init__(
        self,
        service: Optional[CoordinatorService] = None,
        event_dispatcher: Optional[EventDispatcher] = None,
        standalone: bool = False,
    ) -> None:
        self.service = service
        self.standalone = standalone
        self.dispatcher = event_dispatcher or EventDispatcher()

    def set_service(self, service: CoordinatorService) -> None:
        """Bind active coordinator service."""
        self.service = service

    def evaluate(self, method: str, path: str) -> AdmissionDecision:
        """
        Evaluate admission for an incoming request.
        Fails closed on non-ready service, uncoordinated mutations, or unknown methods.
        """
        kind = OperationClassifier.classify(method, path)

        # Internal coordinator endpoints are handled by their own route handlers
        if kind == OperationKind.INTERNAL_COORDINATOR:
            return AdmissionDecision(allowed=True, operation_kind=kind)

        # A bare proxy must explicitly opt out of managed coordination.
        if self.service is None and not self.standalone:
            return AdmissionDecision(False, 503, "coordinator_not_ready", "No managed service is bound", kind)
        # Check service readiness
        if self.service is not None:
            if not self.service.is_ready:
                if self.service.state == ServiceState.DRAINING:
                    return AdmissionDecision(
                        allowed=False,
                        status_code=503,
                        error_type="coordinator_draining",
                        error_message="Coordinator service is shutting down and draining requests",
                        operation_kind=kind,
                    )
                return AdmissionDecision(
                    allowed=False,
                    status_code=503,
                    error_type="coordinator_not_ready",
                    error_message=f"Coordinator service is not ready to admit requests (state: {self.service.state.value})",
                    operation_kind=kind,
                )

        # Route evaluation
        if kind == OperationKind.UNKNOWN_READ:
            return AdmissionDecision(
                False, 501, "unsupported_endpoint", "Unrecognized read route is not verified harmless", kind
            )
        if kind == OperationKind.METADATA_READ:
            return AdmissionDecision(allowed=True, operation_kind=kind)

        elif kind == OperationKind.INFERENCE:
            return AdmissionDecision(
                allowed=True,
                operation_kind=kind,
                resource="gpu.inference",
                lease_type=LeaseType.SHARED,
                event_name="lmstudio.inference_requested",
                finish_event="lmstudio.inference_finished",
            )

        elif kind == OperationKind.MODEL_MUTATION:
            return AdmissionDecision(
                False,
                503,
                "uncoordinated_model_mutation",
                "Model unload is disabled pending coordinated teardown",
                kind,
            )

        elif kind == OperationKind.MODEL_LOAD:
            if self.service is not None and not self.service.has_model_load_policy():
                return AdmissionDecision(
                    False,
                    503,
                    "uncoordinated_model_mutation",
                    "Model loading requires a configured stop policy on gpu.inference with an exclusive lease",
                    kind,
                )
            if not self.dispatcher.has_blocking_listeners("lmstudio.model_load_requested"):
                return AdmissionDecision(
                    allowed=False,
                    status_code=503,
                    error_type="uncoordinated_model_mutation",
                    error_message="Model loading requires an explicit blocking coordination policy",
                    operation_kind=kind,
                )
            return AdmissionDecision(
                allowed=True,
                operation_kind=kind,
                resource="gpu.inference",
                lease_type=LeaseType.EXCLUSIVE,
                event_name="lmstudio.model_load_requested",
                finish_event="lmstudio.model_load_finished",
            )

        elif kind == OperationKind.UNSUPPORTED_MUTATING:
            return AdmissionDecision(
                allowed=False,
                status_code=501,
                error_type="unsupported_endpoint",
                error_message="Unsupported state-mutating endpoint; coordination is required",
                operation_kind=kind,
            )

        return AdmissionDecision(
            allowed=False,
            status_code=400,
            error_type="invalid_request",
            error_message="Unrecognized request",
            operation_kind=kind,
        )
