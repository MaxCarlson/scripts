"""
Unit tests for OperationClassifier and AdmissionController.
"""

from resource_coordinator.adapters.lmstudio.admission import (
    AdmissionController,
    OperationClassifier,
    OperationKind,
)
from resource_coordinator.config import CoordinatorConfig, build_system
from resource_coordinator.core.events import EventDispatcher
from resource_coordinator.core.leases import LeaseType
from resource_coordinator.core.service import CoordinatorService, ServiceState


def test_operation_classifier_inference_endpoints():
    for path in [
        "/v1/chat/completions",
        "/v1/completions",
        "/v1/embeddings",
        "/v1/responses",
        "/v1/messages",
        "/api/v0/chat/completions",
        "/api/v0/completions",
        "/api/v0/embeddings",
        "/api/v1/chat",
        "/custom/prefix/chat/completions",
    ]:
        assert OperationClassifier.classify("POST", path) == OperationKind.INFERENCE
        # GET on inference path is not an inference request
        assert OperationClassifier.classify("GET", path) != OperationKind.INFERENCE


def test_operation_classifier_model_mutation():
    for path in [
        "/api/v0/model/load",
        "/api/v0/model/unload",
        "/api/v1/models/load",
        "/api/v1/models/unload",
    ]:
        assert OperationClassifier.classify("POST", path) == OperationKind.MODEL_MUTATION


def test_operation_classifier_metadata_reads():
    for path in [
        "/v1/models",
        "/api/v0/models",
        "/api/v1/models",
        "/v1/models/qwen2.5-coder-32b",
    ]:
        assert OperationClassifier.classify("GET", path) == OperationKind.METADATA_READ
        assert OperationClassifier.classify("HEAD", path) == OperationKind.METADATA_READ
        assert OperationClassifier.classify("OPTIONS", path) == OperationKind.METADATA_READ


def test_operation_classifier_unsupported_mutating():
    for path in ["/v1/unknown", "/api/v0/mutate", "/admin/reset"]:
        assert OperationClassifier.classify("POST", path) == OperationKind.UNSUPPORTED_MUTATING
        assert OperationClassifier.classify("PUT", path) == OperationKind.UNSUPPORTED_MUTATING
        assert OperationClassifier.classify("DELETE", path) == OperationKind.UNSUPPORTED_MUTATING
        assert OperationClassifier.classify("PATCH", path) == OperationKind.UNSUPPORTED_MUTATING


def test_admission_controller_no_service():
    dispatcher = EventDispatcher()
    controller = AdmissionController(event_dispatcher=dispatcher)

    # Inference allowed with correct parameters
    dec = controller.evaluate("POST", "/v1/chat/completions")
    assert dec.allowed is True
    assert dec.operation_kind == OperationKind.INFERENCE
    assert dec.resource == "gpu.inference"
    assert dec.lease_type == LeaseType.SHARED

    # Read allowed
    dec_read = controller.evaluate("GET", "/v1/models")
    assert dec_read.allowed is True
    assert dec_read.operation_kind == OperationKind.METADATA_READ

    # Unsupported mutating rejected with 501
    dec_bad = controller.evaluate("POST", "/v1/unknown_action")
    assert dec_bad.allowed is False
    assert dec_bad.status_code == 501
    assert dec_bad.error_type == "unsupported_endpoint"


def test_admission_controller_service_not_ready():
    config = CoordinatorConfig()
    system = build_system(config, use_fake_processes=True)
    service = CoordinatorService(system)
    assert service.state == ServiceState.CREATED

    controller = AdmissionController(service=service, event_dispatcher=system.dispatcher)

    # In CREATED state -> rejected with 503
    dec = controller.evaluate("POST", "/v1/chat/completions")
    assert dec.allowed is False
    assert dec.status_code == 503
    assert dec.error_type == "coordinator_not_ready"
    assert "created" in dec.error_message

    # Even read requests are rejected when coordinator is not ready
    dec_read = controller.evaluate("GET", "/v1/models")
    assert dec_read.allowed is False
    assert dec_read.status_code == 503

    # Internal endpoints are still allowed through to their route handlers
    dec_internal = controller.evaluate("GET", "/_coordinator/status")
    assert dec_internal.allowed is True


def test_admission_controller_service_draining():
    config = CoordinatorConfig()
    system = build_system(config, use_fake_processes=True)
    service = CoordinatorService(system)
    service._state = ServiceState.DRAINING

    controller = AdmissionController(service=service, event_dispatcher=system.dispatcher)

    dec = controller.evaluate("POST", "/v1/chat/completions")
    assert dec.allowed is False
    assert dec.status_code == 503
    assert dec.error_type == "coordinator_draining"


def test_admission_controller_model_load_without_blocking_policy():
    dispatcher = EventDispatcher()
    controller = AdmissionController(event_dispatcher=dispatcher)

    # No blocking listener registered for model load
    dec = controller.evaluate("POST", "/api/v0/model/load")
    assert dec.allowed is False
    assert dec.status_code == 503
    assert dec.error_type == "uncoordinated_model_mutation"

    # Register blocking listener
    dispatcher.on("lmstudio.model_load_requested", lambda e: None, is_blocking=True)
    dec_allowed = controller.evaluate("POST", "/api/v0/model/load")
    assert dec_allowed.allowed is True
    assert dec_allowed.resource == "gpu.model_loading"
    assert dec_allowed.lease_type == LeaseType.EXCLUSIVE
