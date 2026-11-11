"""
Transparent asynchronous reverse proxy gateway for LM Studio with inference activity coordination.
"""

from __future__ import annotations

import json
import logging
import math
import os
import secrets
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Optional, Set

import anyio
import httpx
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from resource_coordinator.adapters.lmstudio.admission import (
    MODEL_LOAD_PATHS,
    AdmissionController,
    OperationClassifier,
    OperationKind,
)
from resource_coordinator.core.durable_state import RequestPhase, StateCodec
from resource_coordinator.core.events import EventDispatcher, VetoOperation
from resource_coordinator.core.leases import LeaseManager, LeaseType
from resource_coordinator.core.operator_credentials import CredentialError, load_token
from resource_coordinator.core.service import ServiceState

logger = logging.getLogger(__name__)
UPSTREAM_CONNECT_TIMEOUT_SECONDS = 10.0

# Hop-by-hop headers that should not be forwarded
HOP_BY_HOP_HEADERS: Set[str] = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
}


def is_inference_request(method: str, path: str) -> bool:
    """Determine whether an incoming request represents active inference."""
    return OperationClassifier.classify(method, path) == OperationKind.INFERENCE


def is_model_load_request(method: str, path: str) -> bool:
    """Determine whether an incoming request represents model loading."""
    return OperationClassifier.classify(method, path) == OperationKind.MODEL_LOAD


class StreamCompletionDetector:
    """
    Analyzes response chunks and payloads to distinguish confirmed completion from
    interrupted, indeterminate, or error states.
    """

    def __init__(self, is_sse: bool = True, operation_type: str = "inference") -> None:
        self.is_sse = is_sse
        self.operation_type = operation_type
        self.confirmed = False
        self.finish_reason: Optional[str] = None
        self.termination_state = "active"
        self._buffer = b""
        self._failed = False

    def feed(self, chunk: bytes) -> None:
        # Parse complete SSE frames; choice/tool boundaries are not request completion.
        self._buffer = (self._buffer + chunk).replace(b"\r\n", b"\n")
        while b"\n\n" in self._buffer:
            frame, self._buffer = self._buffer.split(b"\n\n", 1)
            payload = b"\n".join(line[5:].lstrip() for line in frame.split(b"\n") if line.startswith(b"data:"))
            if payload == b"[DONE]":
                if self.operation_type != "model_load":
                    self.confirmed = True
                    self.termination_state = "confirmed_done_marker"
                continue
            try:
                data = json.loads(payload)
            except (ValueError, TypeError):
                continue
            if not isinstance(data, dict):
                continue
            if "error" in data or data.get("type") in {"error", "response.failed", "response.incomplete"}:
                self._failed = True
            if self.operation_type == "model_load" and data.get("type") == "model_load.end":
                # model_load.end is terminal evidence even when the operation failed;
                # failure affects the outcome, not whether the upstream is still running.
                self.confirmed = True
                status = str(data.get("status", "")).casefold()
                failed_terminal = self._failed or "error" in data or status in {"error", "failed"}
                self.termination_state = (
                    "verified_model_load_failure" if failed_terminal else "verified_model_load_success"
                )
            elif self.operation_type != "model_load" and data.get("type") == "chat.end":
                result = data.get("result", {})
                if isinstance(result, dict) and isinstance(result.get("output"), list):
                    self.confirmed = True
                    self.termination_state = "confirmed_chat_end"
            elif self.operation_type != "model_load" and data.get("type") == "response.completed":
                response = data.get("response", {})
                if isinstance(response, dict) and response.get("status") == "completed":
                    self.confirmed = True
                    self.termination_state = "confirmed_response_completed"
        if len(self._buffer) > 1024 * 1024:
            self._buffer = b""
            self._failed = True
        if self._failed and self.termination_state != "verified_model_load_failure":
            self.confirmed = False
            self.termination_state = "uncertain_error_or_oversized_frame"

    def finalize(self) -> bool:
        terminal_failure = self.termination_state == "verified_model_load_failure"
        return self.confirmed and (not self._failed or terminal_failure) and not self._buffer.strip()

    @staticmethod
    def check_non_streaming(status_code: int, body: bytes, path: str = "") -> bool:
        if status_code != 200:
            return False
        try:
            data = json.loads(body)
        except (ValueError, TypeError):
            return False
        if not isinstance(data, dict) or "error" in data:
            return False
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            return all(isinstance(c, dict) and c.get("finish_reason") is not None for c in choices)
        if data.get("status") == "completed":
            return isinstance(data.get("output"), list)
        if "model_instance_id" in data and isinstance(data.get("output"), list):
            return isinstance(data.get("stats"), dict)
        embeddings = data.get("data")
        if isinstance(embeddings, list) and embeddings:
            return all(isinstance(e, dict) and isinstance(e.get("embedding"), list) for e in embeddings)
        # Explicit synchronous model-load result; does not establish inference completion.
        return (
            path.rstrip("/") in MODEL_LOAD_PATHS
            and data.get("status") == "loaded"
            and isinstance(data.get("instance_id"), str)
            and bool(data["instance_id"])
        )


class _CoordinatedStreamingResponse(StreamingResponse):
    def __init__(self, *args, cleanup: Callable[[], Awaitable[None]], **kwargs):
        super().__init__(*args, **kwargs)
        self._cleanup = cleanup

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                await self._cleanup()


class LMStudioGateway:
    """
    Reverse proxy gateway coordinating inference requests to upstream LM Studio.
    """

    def __init__(
        self,
        upstream_url: str = "http://127.0.0.1:1234",
        event_dispatcher: Optional[EventDispatcher] = None,
        lease_manager: Optional[LeaseManager] = None,
        timeout_seconds: float = 120.0,
        bounded_drain_seconds: Optional[float] = None,
        recovery_token: Optional[str] = None,
        admission_controller: Optional[AdmissionController] = None,
        standalone: bool = False,
        state_persistence_path: Optional[str] = None,
    ) -> None:
        self.upstream_url = upstream_url.rstrip("/")
        self.dispatcher = event_dispatcher or EventDispatcher()
        self.lease_mgr = lease_manager or LeaseManager(event_dispatcher=self.dispatcher)
        self.timeout_seconds = timeout_seconds
        self.bounded_drain_seconds = bounded_drain_seconds
        self.state_persistence_path = state_persistence_path or ""
        self._http_client: Optional[httpx.AsyncClient] = None
        self.recovery_token = recovery_token or os.environ.get("RESOURCE_COORDINATOR_RECOVERY_TOKEN")
        try:
            self.operator_token = load_token()
        except CredentialError as exc:
            # Credential storage must never take down inference or miner supervision.
            self.operator_token = None
            logger.error("Operator controls unavailable: %s", exc)
        self.admission_controller = admission_controller or AdmissionController(
            event_dispatcher=self.dispatcher, standalone=standalone
        )
        if bounded_drain_seconds:
            raise ValueError("Bounded drain is disabled until cancellation-safe upstream draining is verified")

    def set_service(self, service: Any) -> None:
        """Bind a coordinator service to gate admission on service readiness."""
        bound = self.admission_controller.service
        if bound is not None and bound is not service:
            raise RuntimeError("Cannot replace the service bound to a gateway")
        self.admission_controller.set_service(service)

    def get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                base_url=self.upstream_url,
                timeout=httpx.Timeout(self.timeout_seconds, connect=UPSTREAM_CONNECT_TIMEOUT_SECONDS),
                follow_redirects=False,
            )
        return self._http_client

    async def close(self) -> None:
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    def create_app(self, service: Optional[Any] = None) -> Starlette:
        """Create Starlette ASGI application for the proxy."""
        if service is not None:
            self.set_service(service)
        from contextlib import asynccontextmanager

        bound_service = self.admission_controller.service

        @asynccontextmanager
        async def lifespan(app: Starlette):
            try:
                if bound_service is not None:
                    if not await bound_service.start():
                        raise RuntimeError("Coordinator service startup failed closed")
                elif not self.admission_controller.standalone:
                    raise RuntimeError("A managed service is required")
                yield
            finally:
                with anyio.CancelScope(shield=True):
                    if bound_service is not None:
                        await bound_service.stop()
                    else:
                        await self.close()

        routes = [
            Route("/_coordinator/status", self.handle_coordinator_status, methods=["GET"]),
            Route("/_coordinator/miner/status", self.handle_coordinator_miner_status, methods=["GET"]),
            Route("/_coordinator/miner/{action:str}", self.handle_coordinator_miner_control, methods=["POST"]),
            Route("/_coordinator/gaming/status", self.handle_coordinator_gaming_status, methods=["GET"]),
            Route("/_coordinator/gaming/{action:str}", self.handle_coordinator_gaming_control, methods=["POST"]),
            Route("/_coordinator/logs/{process_name:str}", self.handle_coordinator_logs, methods=["GET"]),
            Route("/_coordinator/restart", self.handle_coordinator_restart, methods=["POST"]),
            Route("/_coordinator/shutdown", self.handle_coordinator_shutdown, methods=["POST"]),
            Route("/_coordinator/recover", self.handle_coordinator_recover, methods=["POST"]),
            Route("/_coordinator/abort", self.handle_coordinator_abort, methods=["POST"]),
            Route("/{path:path}", self.handle_proxy, methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"]),
        ]
        app = Starlette(routes=routes, lifespan=lifespan)
        return app

    def _current_operator_token(self) -> Optional[str]:
        token = os.environ.get("RESOURCE_COORDINATOR_OPERATOR_TOKEN") or self.operator_token
        if token is None:
            try:
                token = load_token()
                self.operator_token = token
            except CredentialError:
                token = None
        return token or self.recovery_token

    def _operator_authorized(self, request: Request) -> bool:
        token = self._current_operator_token()
        supplied = request.headers.get("authorization", "")
        return bool(token and secrets.compare_digest(supplied.encode(), ("Bearer " + token).encode()))

    def _recovery_tokens(self) -> Set[str]:
        accepted = {
            token
            for token in (
                self.recovery_token,
                os.environ.get("RESOURCE_COORDINATOR_RECOVERY_TOKEN"),
                os.environ.get("RESOURCE_COORDINATOR_OPERATOR_TOKEN"),
            )
            if token
        }
        if not os.environ.get("RESOURCE_COORDINATOR_OPERATOR_TOKEN"):
            try:
                accepted.add(load_token(require_secure=True))
            except CredentialError:
                pass
        return accepted

    def _recovery_authorized(self, request: Request) -> bool:
        supplied = request.headers.get("authorization", "").encode()
        accepted = self._recovery_tokens()
        return any(secrets.compare_digest(supplied, ("Bearer " + token).encode()) for token in accepted)

    async def handle_coordinator_logs(self, request: Request) -> Response:
        if not self._operator_authorized(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=403)
        service = self.admission_controller.service
        name = request.path_params.get("process_name", "")
        supervisors = service.system.supervisors if service is not None else {}
        supervisor = supervisors.get(name)
        if supervisor is None and name.casefold() in {"miner", "krig"}:
            matches = [
                candidate for process_name, candidate in supervisors.items()
                if "miner" in process_name.casefold() or "krig" in process_name.casefold()
            ]
            if len(matches) == 1:
                supervisor = matches[0]
        if supervisor is None:
            return JSONResponse({"error": f"Unknown configured process: {name}"}, status_code=404)
        log_path = getattr(getattr(supervisor, "backend", None), "stdout_log_path", None)
        if not log_path:
            return JSONResponse({"error": f"No captured log is configured for process: {name}"}, status_code=404)
        try:
            offset = int(request.query_params.get("offset", "0"))
            tail_bytes = int(request.query_params.get("tail_bytes", "65536"))
            if offset < 0 or tail_bytes < 0 or tail_bytes > 262144:
                raise ValueError
            path = Path(log_path)
            size = path.stat().st_size
            if "offset" not in request.query_params:
                offset = max(0, size - tail_bytes)
            elif offset > size:
                offset = 0
            with path.open("rb") as stream:
                stream.seek(offset)
                content = stream.read(262144)
                next_offset = stream.tell()
        except ValueError:
            return JSONResponse({"error": "offset and tail_bytes must be valid bounded integers"}, status_code=400)
        except OSError:
            return JSONResponse({"error": "Configured process log is not currently readable"}, status_code=404)
        return Response(content, media_type="application/octet-stream", headers={"X-Log-Offset": str(next_offset)})

    async def handle_coordinator_miner_status(self, request: Request) -> Response:
        service = self.admission_controller.service
        if service is None:
            return JSONResponse({"error": "No managed service bound to coordinator"}, status_code=503)
        result = await service.manual_miner_control("status")
        return JSONResponse(result, status_code=200 if result.get("status") == "ok" else 503)

    async def handle_coordinator_miner_control(self, request: Request) -> Response:
        service = self.admission_controller.service
        if service is None:
            return JSONResponse({"error": "No managed service bound to coordinator"}, status_code=503)
        if not self._operator_authorized(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=403)
        if not service.is_ready:
            return JSONResponse({"error": "Coordinator is not ready"}, status_code=409)
        action = request.path_params.get("action")
        try:
            payload = await request.json()
        except (ValueError, TypeError):
            return JSONResponse({"error": "A control request body is required"}, status_code=400)
        if not isinstance(payload, dict) or any(
            not isinstance(payload.get(key), str) or not payload[key].strip() or len(payload[key]) > 1024
            for key in ("operator", "reason")
        ):
            return JSONResponse({"error": "Nonempty bounded operator and reason are required"}, status_code=400)
        duration = payload.get("duration_seconds")
        threshold = payload.get("until_gpu_below_pct")
        window = payload.get("window_seconds")
        if action == "pause" and threshold is not None:
            if (type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0 <= threshold <= 100
                    or type(window) not in (int, float) or not math.isfinite(window) or window <= 0):
                return JSONResponse({"error": "pause GPU condition requires a threshold 0..100 and positive window"},
                                    status_code=400)
        elif action == "pause" and (
            type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0
        ):
            return JSONResponse({"error": "pause requires duration_seconds or a GPU-idle condition"}, status_code=400)
        result = await service.manual_miner_control(
            action, duration_seconds=duration, threshold_pct=threshold, window_seconds=window
        )
        status_code = 200 if result.get("status") in {"running", "paused", "stopped"} else 409
        if result.get("status") == "invalid":
            status_code = 400
        if result.get("status") == "unavailable":
            status_code = 503
        result.update(operator=payload["operator"], operator_reason=payload["reason"])
        result.setdefault("reason", payload["reason"])
        return JSONResponse(result, status_code=status_code)

    async def handle_coordinator_gaming_status(self, request: Request) -> Response:
        service = self.admission_controller.service
        if service is None:
            return JSONResponse({"error": "No managed service bound to coordinator"}, status_code=503)
        result = await service.gaming_control("status")
        return JSONResponse(result, status_code=200 if result.get("status") != "unavailable" else 503)

    async def handle_coordinator_gaming_control(self, request: Request) -> Response:
        service = self.admission_controller.service
        if service is None:
            return JSONResponse({"error": "No managed service bound to coordinator"}, status_code=503)
        if not self._operator_authorized(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=403)
        if not service.is_ready:
            return JSONResponse({"error": "Coordinator is not ready"}, status_code=409)
        try:
            payload = await request.json()
        except (ValueError, TypeError):
            return JSONResponse({"error": "An attributed gaming request body is required"}, status_code=400)
        if not isinstance(payload, dict) or any(
            not isinstance(payload.get(key), str) or not payload[key].strip() or len(payload[key]) > 1024
            for key in ("operator", "reason")
        ):
            return JSONResponse({"error": "Nonempty bounded operator and reason are required"}, status_code=400)
        action = request.path_params.get("action")
        result = await service.gaming_control(action)
        result.update(operator=payload["operator"], operator_reason=payload["reason"])
        result.setdefault("reason", payload["reason"])
        status_code = 200 if result.get("status") in {"active", "inactive"} else 409
        if result.get("status") == "unavailable":
            status_code = 503
        if result.get("status") == "invalid":
            status_code = 400
        return JSONResponse(result, status_code=status_code)

    async def _request_lifecycle_action(self, request: Request, *, restart: bool) -> Response:
        service = self.admission_controller.service
        if service is None:
            return JSONResponse({"error": "No managed service bound to coordinator"}, status_code=503)
        token = self._current_operator_token()
        if not token:
            return JSONResponse({"error": "Lifecycle control disabled: configure an operator token"}, status_code=503)
        supplied = request.headers.get("authorization", "")
        if not secrets.compare_digest(supplied.encode(), ("Bearer " + token).encode()):
            return JSONResponse({"error": "Unauthorized"}, status_code=403)
        try:
            payload = await request.json()
        except (ValueError, TypeError):
            return JSONResponse({"error": "Operator and reason are required"}, status_code=400)
        if not isinstance(payload, dict) or any(
            not isinstance(payload.get(key), str) or not payload[key].strip() or len(payload[key]) > 1024
            for key in ("operator", "reason")
        ):
            return JSONResponse({"error": "Nonempty bounded operator and reason are required"}, status_code=400)
        if service.state != ServiceState.READY:
            return JSONResponse({"error": f"Coordinator is not ready ({service.state.value})"}, status_code=409)

        # Close admission synchronously before returning 202. This prevents a
        # concurrent control or inference request from slipping in before the
        # ASGI background task begins the graceful drain.
        service._state = ServiceState.DRAINING

        async def drain_and_exit() -> None:
            await service.stop(reason=f"{payload['operator']}: {payload['reason']}")
            if service.state != ServiceState.STOPPED:
                return
            request.app.state.restart_requested = restart
            callback = getattr(request.app.state, "request_server_exit", None)
            if callback is not None:
                callback()

        return JSONResponse(
            {"status": "draining", "action": "restart" if restart else "shutdown"},
            status_code=202,
            background=BackgroundTask(drain_and_exit),
        )

    async def handle_coordinator_restart(self, request: Request) -> Response:
        """Drain safely, then let the serving supervisor rebuild the service from config."""
        return await self._request_lifecycle_action(request, restart=True)

    async def handle_coordinator_shutdown(self, request: Request) -> Response:
        """Drain safely and exit the serving process without an emergency abort."""
        return await self._request_lifecycle_action(request, restart=False)

    async def handle_coordinator_status(self, request: Request) -> JSONResponse:
        """Expose internal coordinator health, lease metrics, and restart inhibition state."""
        inhibition = self.lease_mgr.get_inhibition("gpu.inference")
        svc = self.admission_controller.service
        processes = {}
        if svc is not None:
            for name, supervisor in svc.system.supervisors.items():
                info = await supervisor.status()
                processes[name] = {
                    **info.to_dict(),
                    "was_stopped_by_coordinator": supervisor.was_stopped_by_coordinator,
                }
        safe_request_detail_fields = {
            "request_id",
            "operation_type",
            "model",
            "resource",
            "lease_type",
            "lifecycle_state",
            "started_at",
            "elapsed_seconds",
            "configured_timeout_seconds",
            "connect_timeout_seconds",
            "timeout_phase",
            "failure_kind",
            "exception_class",
            "safe_exception_detail",
            "http_status",
            "terminal_evidence",
            "inhibition_holder",
            "inhibition_reason",
            "recovery_recommendation",
        }
        safe_inhibition = inhibition.to_dict() if inhibition else None
        if safe_inhibition is not None:
            safe_inhibition["details"] = {
                key: value
                for key, value in inhibition.details.items()
                if key in safe_request_detail_fields
            }
        recovery: Dict[str, Any] = {
            "required": bool(inhibition),
            "inhibition": safe_inhibition,
            "requests": [],
            "journal_status": "not_configured" if not self.state_persistence_path else "available",
            "recommendation": (
                "Verify the upstream operation has terminated, then use authenticated service recover with an explicit reason."
                if inhibition
                else None
            ),
        }
        if inhibition and self.state_persistence_path:
            try:
                durable = StateCodec.load(self.state_persistence_path)
                unresolved = {
                    RequestPhase.RESERVED.value,
                    RequestPhase.POSSIBLY_FORWARDED.value,
                    RequestPhase.UNCERTAIN.value,
                }
                recovery["requests"] = [
                    {
                        "request_id": item.request_id,
                        "resource": item.resource,
                        "phase": item.phase,
                        "model": item.model,
                        "path": item.path,
                        "created_at": item.created_at,
                        "updated_at": item.updated_at,
                        "details": {
                            key: value
                            for key, value in item.details.items()
                            if key in safe_request_detail_fields
                        },
                    }
                    for item in durable.requests.values()
                    if item.resource == "gpu.inference" and item.phase in unresolved
                ]
            except (OSError, ValueError):
                recovery["journal_status"] = "unavailable"
        return JSONResponse(
            {
                "status": "online",
                "service_state": svc.state.value if svc else "standalone",
                "is_ready": svc.is_ready if svc else self.admission_controller.standalone,
                "runtime": {
                    **(getattr(svc, "runtime_identity", {}) if svc else {}),
                    "pid": os.getpid(),
                    "stop_miner_on_shutdown": bool(getattr(svc, "stop_miner_on_shutdown", False)),
                } if svc else None,
                "upstream_url": self.upstream_url,
                "processes": processes,
                "gpu_inference": {
                    "active_count": self.lease_mgr.active_count("gpu.inference"),
                    "pending_count": self.lease_mgr.pending_count("gpu.inference"),
                    "is_cooling_down": self.lease_mgr.is_cooling_down("gpu.inference"),
                    "cooldown_remaining": round(self.lease_mgr.cooldown_remaining("gpu.inference"), 1),
                    "is_restart_inhibited": self.lease_mgr.is_restart_inhibited("gpu.inference"),
                    "inhibition": inhibition.to_dict() if inhibition else None,
                    "recovery": recovery,
                },
            }
        )

    async def handle_coordinator_abort(self, request: Request) -> JSONResponse:
        """Trigger emergency abort to stop admission and prevent miner restarts."""
        svc = self.admission_controller.service
        if not svc:
            return JSONResponse({"error": "No managed service bound to coordinator"}, status_code=503)
        token = self._current_operator_token()
        if not token:
            return JSONResponse({"error": "Abort API disabled: configure an operator token"}, status_code=503)
        supplied = request.headers.get("authorization", "")
        if not secrets.compare_digest(supplied.encode(), ("Bearer " + token).encode()):
            return JSONResponse({"error": "Unauthorized"}, status_code=403)
        try:
            body = await request.json()
        except (ValueError, TypeError):
            return JSONResponse({"error": "Attributed abort JSON is required"}, status_code=400)
        if not isinstance(body, dict) or any(
            not isinstance(body.get(k), str) or not body[k].strip() or len(body[k]) > 1024
            for k in ("reason", "operator")
        ):
            return JSONResponse({"error": "Nonempty bounded reason and operator are required"}, status_code=400)
        res = await svc.emergency_abort(reason=f"{body['operator']}: {body['reason']}")
        if self.state_persistence_path:
            StateCodec.record_inhibition(
                self.state_persistence_path,
                "gpu.inference",
                reason=f"abort:{body['operator']}:{body['reason']}",
                holder_id=body["operator"],
            )
        return JSONResponse(res)

    async def handle_coordinator_recover(self, request: Request) -> JSONResponse:
        """Explicit authenticated operator override; no upstream idle verifier exists yet."""
        if not self._recovery_tokens():
            return JSONResponse({"error": "Recovery is disabled: configure an operator token"}, status_code=503)
        if not self._recovery_authorized(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=403)
        try:
            payload = await request.json()
        except (ValueError, TypeError):
            return JSONResponse({"error": "An explicit operator override body is required"}, status_code=400)
        if not isinstance(payload, dict) or payload.get("override") is not True:
            return JSONResponse(
                {"error": "Upstream idle cannot be verified; explicit override is required"}, status_code=409
            )
        operator = payload.get("operator")
        reason = payload.get("reason")
        if not isinstance(operator, str) or not operator.strip() or not isinstance(reason, str) or not reason.strip():
            return JSONResponse({"error": "Operator and reason are required"}, status_code=400)
        service = self.admission_controller.service
        if service is not None and not service.is_ready:
            return JSONResponse(
                {"error": "Terminal or unready service requires independent reconciliation"}, status_code=409
            )
        resource = request.query_params.get("resource", "gpu.inference")
        resolved_requests: list[str] = []

        def _persist_resolution() -> None:
            nonlocal resolved_requests
            if self.state_persistence_path:
                _, resolved_requests = StateCodec.resolve_unresolved_requests(
                    self.state_persistence_path, resource, operator, reason
                )

        try:
            cleared = await self.lease_mgr.clear_inhibition(
                resource,
                origin=f"operator_override:{operator}:{reason}",
                require_all_idle=True,
                before_clear=_persist_resolution,
            )
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        except (OSError, ValueError) as exc:
            logger.error("Failed persisting operator recovery for '%s': %s", resource, exc)
            return JSONResponse(
                {"error": f"Durable state persistence failed during recovery: {exc}"}, status_code=500
            )
        if service is not None and service.state == ServiceState.RECONCILIATION_REQUIRED:
            # If all resources are now uninhibited and not claimed, restore service readiness
            if not self.lease_mgr.restarts_blocked and not any(
                self.lease_mgr.is_restart_inhibited(r) for r in self.lease_mgr.tracked_resources()
            ):
                service._state = ServiceState.READY
                service._aborted = False
                service._failure_reason = None
        return JSONResponse(
            {
                "status": "cleared" if cleared else "none",
                "resource": resource,
                "previous_inhibition": cleared.to_dict() if cleared else None,
                "operator": operator,
                "reason": reason,
                "resolved_request_ids": resolved_requests,
                "upstream_verified_idle": False,
            }
        )

    async def handle_proxy(self, request: Request) -> Response:
        path = "/" + request.path_params.get("path", "").lstrip("/")
        method = request.method
        request_id = f"coord-{uuid.uuid4().hex[:12]}"

        # Evaluate admission decision through centralized controller
        decision = self.admission_controller.evaluate(method, path)
        if not decision.allowed:
            svc = self.admission_controller.service
            return JSONResponse(
                {
                    "error": {
                        "code": decision.error_type,
                        "type": decision.error_type,
                        "message": decision.error_message,
                        "service_state": svc.state.value if svc else "standalone",
                    }
                },
                status_code=decision.status_code,
            )

        if decision.operation_kind == OperationKind.INTERNAL_COORDINATOR:
            return JSONResponse({"error": "Unknown coordinator route or method"}, status_code=404)
        # Body acquisition can suspend past abort/shutdown. Never reuse its old admission decision.
        body = await request.body()
        decision = self.admission_controller.evaluate(method, path)
        if not decision.allowed:
            return JSONResponse(
                {"error": {"type": decision.error_type, "message": decision.error_message}},
                status_code=decision.status_code,
            )
        model_name = ""
        if body:
            try:
                body_json = json.loads(body)
                if isinstance(body_json, dict):
                    model_name = str(body_json.get("model", ""))
            except Exception:
                pass

        if decision.operation_kind in {OperationKind.METADATA_READ, OperationKind.UNKNOWN_READ}:
            return await self._forward_direct(request, path, body, request_id)

        if decision.operation_kind in {OperationKind.INFERENCE, OperationKind.MODEL_LOAD}:
            assert decision.resource is not None
            assert decision.lease_type is not None
            assert decision.event_name is not None
            assert decision.finish_event is not None
            return await self._proxy_with_coordination(
                request=request,
                path=path,
                body=body,
                request_id=request_id,
                resource=decision.resource,
                lease_type=decision.lease_type,
                event_name=decision.event_name,
                finish_event=decision.finish_event,
                model_name=model_name,
            )

        return JSONResponse({"error": "Unhandled admission decision"}, status_code=500)

    async def _proxy_with_coordination(
        self,
        request: Request,
        path: str,
        body: bytes,
        request_id: str,
        resource: str,
        lease_type: LeaseType,
        event_name: str,
        finish_event: str,
        model_name: str,
    ) -> Response:
        """Forward protected inference or model load with robust termination tracking."""
        event_data = {
            "request_id": request_id,
            "path": path,
            "model": model_name,
            "resource": resource,
        }
        started_monotonic = time.monotonic()
        started_at = time.time()
        operation_type = "model_load" if path.rstrip("/") in MODEL_LOAD_PATHS else "inference"

        reservation_cm = self.lease_mgr.reserve(resource, lease_type, request_id, {"model": model_name, "path": path})
        reservation = None
        upstream_resp: Optional[httpx.Response] = None
        forwarded = False
        completed = False
        response_owns_cleanup = False
        cleaned = False
        reserved_in_journal = False
        failure_kind: Optional[str] = None
        failure_class: Optional[str] = None
        failure_detail: Optional[str] = None
        http_status: Optional[int] = None
        terminal_evidence = "not_forwarded"
        completion_detector: Optional[StreamCompletionDetector] = None

        def request_details() -> Dict[str, Any]:
            if completed:
                evidence = (
                    completion_detector.termination_state
                    if completion_detector is not None
                    else "verified_non_streaming_response"
                )
                recommendation = None
            elif forwarded:
                evidence = terminal_evidence
                recommendation = (
                    "Keep restart inhibited until upstream termination is verified or an operator explicitly recovers."
                )
            else:
                evidence = "not_forwarded"
                recommendation = None
            return {
                "request_id": request_id,
                "operation_type": operation_type,
                "model": model_name or None,
                "resource": resource,
                "lease_type": lease_type.value,
                "lifecycle_state": (
                    "terminal_verified" if completed else "possibly_forwarded" if forwarded else "reserved"
                ),
                "started_at": started_at,
                "elapsed_seconds": round(max(0.0, time.monotonic() - started_monotonic), 3),
                "configured_timeout_seconds": self.timeout_seconds,
                "connect_timeout_seconds": UPSTREAM_CONNECT_TIMEOUT_SECONDS,
                "timeout_phase": failure_kind if failure_kind and "timeout" in failure_kind else None,
                "failure_kind": failure_kind,
                "exception_class": failure_class,
                "safe_exception_detail": failure_detail,
                "http_status": http_status,
                "terminal_evidence": evidence,
                "inhibition_holder": request_id if forwarded and not completed else None,
                "inhibition_reason": (
                    failure_kind or "upstream_terminal_evidence_missing" if forwarded and not completed else None
                ),
                "recovery_recommendation": recommendation,
            }

        async def cleanup() -> None:
            nonlocal cleaned
            if cleaned:
                return
            cleaned = True
            with anyio.CancelScope(shield=True):
                try:
                    if forwarded and not completed:
                        await self.lease_mgr.inhibit_restart(
                            resource,
                            failure_kind or "Stream ended without completion signal or execution termination uncertain",
                            request_id,
                            {"model": model_name, "path": path, **request_details()},
                        )
                    if self.state_persistence_path and (reserved_in_journal or forwarded):
                        try:
                            if completed:
                                StateCodec.record_request_phase(
                                    self.state_persistence_path,
                                    request_id,
                                    resource,
                                    RequestPhase.TERMINAL_VERIFIED,
                                    model=model_name,
                                    path=path,
                                    details=request_details(),
                                )
                            elif forwarded:
                                StateCodec.record_request_phase(
                                    self.state_persistence_path,
                                    request_id,
                                    resource,
                                    RequestPhase.UNCERTAIN,
                                    model=model_name,
                                    path=path,
                                    details=request_details(),
                                )
                            else:
                                StateCodec.record_request_phase(
                                    self.state_persistence_path,
                                    request_id,
                                    resource,
                                    RequestPhase.TERMINAL_VERIFIED,
                                    model=model_name,
                                    path=path,
                                    details={"cancelled": True},
                                )
                        except Exception as log_exc:
                            logger.error("Failed recording terminal phase in state journal: %s", log_exc)
                            await self.lease_mgr.inhibit_restart(
                                resource,
                                f"Journal persistence failure during request cleanup: {log_exc}",
                                request_id,
                                {"model": model_name, "path": path},
                            )
                    await self.dispatcher.emit(
                        finish_event,
                        {
                            **event_data,
                            "status": "completed" if completed else "uncertain" if forwarded else "rejected",
                        },
                    )
                finally:
                    try:
                        if upstream_resp is not None:
                            await upstream_resp.aclose()
                    finally:
                        if reservation is not None:
                            await reservation_cm.__aexit__(None, None, None)

        try:
            reservation = await reservation_cm.__aenter__()
            if self.state_persistence_path:
                StateCodec.record_request_phase(
                    self.state_persistence_path,
                    request_id,
                    resource,
                    RequestPhase.RESERVED,
                    model=model_name,
                    path=path,
                    details=request_details(),
                )
                reserved_in_journal = True
            if not self.admission_controller.evaluate(request.method, path).allowed:
                raise VetoOperation("Admission closed before blocking actions")
            await self.dispatcher.emit_blocking(event_name, event_data, origin="lmstudio_gateway")
            await reservation.activate(timeout=self.timeout_seconds)
            if not self.admission_controller.evaluate(request.method, path).allowed:
                raise VetoOperation("Admission closed before forwarding")
            service = self.admission_controller.service
            if service is not None:
                await service.verify_before_forward()
            if not self.admission_controller.evaluate(request.method, path).allowed:
                raise VetoOperation("Admission closed before forwarding")
            client = self.get_http_client()
            upstream_req = self._build_upstream_request(client, request, path, body, request_id)
            if self.state_persistence_path:
                StateCodec.record_request_phase(
                    self.state_persistence_path,
                    request_id,
                    resource,
                    RequestPhase.POSSIBLY_FORWARDED,
                    model=model_name,
                    path=path,
                    details={
                        **request_details(),
                        "lifecycle_state": "possibly_forwarded",
                        "terminal_evidence": "dispatch_started_execution_not_yet_verified",
                    },
                )
            forwarded = True  # send may have reached upstream even if it raises/cancels
            await self.dispatcher.emit("lmstudio.inference_forwarded", event_data)
            upstream_resp = await client.send(upstream_req, stream=True)
            http_status = upstream_resp.status_code
            content_type = upstream_resp.headers.get("content-type", "")
            clean_headers = self._clean_headers(upstream_resp.headers, request_id)
            if "text/event-stream" in content_type:
                detector = StreamCompletionDetector(operation_type=operation_type)
                completion_detector = detector
                response = upstream_resp

                async def stream_body() -> AsyncIterator[bytes]:
                    nonlocal completed, terminal_evidence, failure_kind, failure_class, failure_detail
                    try:
                        async for chunk in response.aiter_bytes():
                            detector.feed(chunk)
                            yield chunk
                        # Require both protocol completion and normal EOF, never a choice-level marker alone.
                        completed = response.status_code == 200 and detector.finalize()
                        terminal_evidence = detector.termination_state
                        if terminal_evidence == "verified_model_load_failure":
                            failure_kind = "upstream_operation_failed"
                            failure_detail = "The upstream reported a terminal model-load failure."
                        if response.status_code >= 400:
                            failure_kind = "upstream_returned_error"
                            failure_detail = "The upstream returned an HTTP error response."
                    except BaseException as exc:
                        failure_kind = "client_disconnect_or_stream_interruption"
                        failure_class = type(exc).__name__
                        failure_detail = "The downstream stream ended unexpectedly; upstream execution is unverified."
                        terminal_evidence = "stream_interrupted_without_verified_terminal"
                        raise

                result = _CoordinatedStreamingResponse(
                    stream_body(),
                    status_code=response.status_code,
                    headers=clean_headers,
                    media_type=content_type,
                    cleanup=cleanup,
                )
                response_owns_cleanup = True
                return result
            content = await upstream_resp.aread()
            completed = StreamCompletionDetector.check_non_streaming(upstream_resp.status_code, content, path)
            terminal_evidence = "verified_non_streaming_response" if completed else "non_streaming_response_not_terminal"
            if upstream_resp.status_code >= 400:
                failure_kind = "upstream_returned_error"
                failure_detail = "The upstream returned an HTTP error response; termination is not assumed."
            return Response(content=content, status_code=upstream_resp.status_code, headers=clean_headers)
        except VetoOperation as exc:
            return JSONResponse(
                {"error": {"message": str(exc), "type": "coordinator_veto", "request_id": request_id}}, status_code=503
            )
        except Exception as exc:
            failure_class = type(exc).__name__
            if isinstance(exc, httpx.ConnectTimeout):
                failure_kind = "upstream_connect_timeout"
                failure_detail = "Timed out while establishing the upstream connection."
            elif isinstance(exc, httpx.ReadTimeout):
                failure_kind = "upstream_read_timeout"
                failure_detail = "No upstream response bytes arrived before the read timeout; execution may continue."
            elif isinstance(exc, httpx.TimeoutException):
                failure_kind = "upstream_timeout"
                failure_detail = "An upstream timeout occurred; remote execution termination is unverified."
            elif isinstance(exc, httpx.RequestError):
                failure_kind = "upstream_transport_error"
                failure_detail = "The upstream transport failed; remote execution termination is unverified."
            else:
                failure_kind = "coordinated_operation_error"
                failure_detail = "The coordinated request failed; remote execution termination is unverified."
            terminal_evidence = "upstream_execution_uncertain" if forwarded else "not_forwarded"
            logger.error("Coordinated request %s failed (%s)", request_id, failure_class)
            return JSONResponse(
                {
                    "error": {
                        "message": "Upstream operation failed; execution may still be active"
                        if forwarded
                        else "Coordinated request failed before forwarding",
                        "type": failure_kind,
                        "request_id": request_id,
                        "operation_type": operation_type,
                        "timeout_seconds": self.timeout_seconds,
                        "detail": failure_detail,
                    }
                },
                status_code=502 if forwarded else 500,
            )
        finally:
            if not response_owns_cleanup:
                await cleanup()

    async def _forward_direct(self, request: Request, path: str, body: bytes, request_id: str) -> Response:
        """Forward a read/metadata request without acquiring a lease or interrupting mining."""
        client = self.get_http_client()
        upstream_req = self._build_upstream_request(client, request, path, body, request_id)

        try:
            upstream_resp = await client.send(upstream_req, stream=True)
            content = await upstream_resp.aread()
            clean_headers = self._clean_headers(upstream_resp.headers, request_id)
            return Response(
                content=content,
                status_code=upstream_resp.status_code,
                headers=clean_headers,
            )
        except Exception as exc:
            logger.error("Direct proxy failed for %s: %s", request_id, exc)
            return JSONResponse(
                {"error": {"message": f"Failed to reach LM Studio: {exc}", "type": "upstream_error"}},
                status_code=502,
            )
        finally:
            if "upstream_resp" in locals():
                await upstream_resp.aclose()

    def _build_upstream_request(
        self,
        client: httpx.AsyncClient,
        request: Request,
        path: str,
        body: bytes,
        request_id: str,
    ) -> httpx.Request:
        headers = dict(request.headers)
        # Strip hop-by-hop headers
        for h in HOP_BY_HOP_HEADERS:
            headers.pop(h, None)
        headers["x-request-id"] = request_id

        return client.build_request(
            method=request.method,
            url=path,
            params=request.query_params,
            headers=headers,
            content=body,
        )

    def _clean_headers(self, headers: httpx.Headers, request_id: str) -> Dict[str, str]:
        clean: Dict[str, str] = {}
        for k, v in headers.items():
            if k.lower() not in HOP_BY_HOP_HEADERS | {"content-encoding", "content-length"}:
                clean[k] = v
        clean["x-coordinator-request-id"] = request_id
        return clean
