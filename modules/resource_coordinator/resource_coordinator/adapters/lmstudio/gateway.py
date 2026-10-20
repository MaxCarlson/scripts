"""
Transparent asynchronous reverse proxy gateway for LM Studio with inference activity coordination.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import uuid
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Optional, Set

import anyio
import httpx
from starlette.applications import Starlette
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
from resource_coordinator.core.events import EventDispatcher, VetoOperation
from resource_coordinator.core.leases import LeaseManager, LeaseType

logger = logging.getLogger(__name__)

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

    def __init__(self, is_sse: bool = True) -> None:
        self.is_sse = is_sse
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
            if data.get("type") == "chat.end":
                result = data.get("result", {})
                if isinstance(result, dict) and isinstance(result.get("output"), list):
                    self.confirmed = True
                    self.termination_state = "confirmed_chat_end"
            elif data.get("type") == "response.completed":
                response = data.get("response", {})
                if isinstance(response, dict) and response.get("status") == "completed":
                    self.confirmed = True
                    self.termination_state = "confirmed_response_completed"
        if len(self._buffer) > 1024 * 1024:
            self._buffer = b""
            self._failed = True
        if self._failed:
            self.confirmed = False
            self.termination_state = "uncertain_error_or_oversized_frame"

    def finalize(self) -> bool:
        return self.confirmed and not self._failed and not self._buffer.strip()

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
            and (isinstance(data.get("instance_id"), str) or isinstance(data.get("model"), str))
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
    ) -> None:
        self.upstream_url = upstream_url.rstrip("/")
        self.dispatcher = event_dispatcher or EventDispatcher()
        self.lease_mgr = lease_manager or LeaseManager(event_dispatcher=self.dispatcher)
        self.timeout_seconds = timeout_seconds
        self.bounded_drain_seconds = bounded_drain_seconds
        self._http_client: Optional[httpx.AsyncClient] = None
        self.recovery_token = recovery_token or os.environ.get("RESOURCE_COORDINATOR_RECOVERY_TOKEN")
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
                timeout=httpx.Timeout(self.timeout_seconds, connect=10.0),
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
            Route("/_coordinator/recover", self.handle_coordinator_recover, methods=["POST"]),
            Route("/_coordinator/abort", self.handle_coordinator_abort, methods=["POST"]),
            Route("/{path:path}", self.handle_proxy, methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"]),
        ]
        app = Starlette(routes=routes, lifespan=lifespan)
        return app

    async def handle_coordinator_status(self, request: Request) -> JSONResponse:
        """Expose internal coordinator health, lease metrics, and restart inhibition state."""
        inhibition = self.lease_mgr.get_inhibition("gpu.inference")
        svc = self.admission_controller.service
        return JSONResponse(
            {
                "status": "online",
                "service_state": svc.state.value if svc else "standalone",
                "is_ready": svc.is_ready if svc else self.admission_controller.standalone,
                "upstream_url": self.upstream_url,
                "gpu_inference": {
                    "active_count": self.lease_mgr.active_count("gpu.inference"),
                    "pending_count": self.lease_mgr.pending_count("gpu.inference"),
                    "is_cooling_down": self.lease_mgr.is_cooling_down("gpu.inference"),
                    "cooldown_remaining": round(self.lease_mgr.cooldown_remaining("gpu.inference"), 1),
                    "is_restart_inhibited": self.lease_mgr.is_restart_inhibited("gpu.inference"),
                    "inhibition": inhibition.to_dict() if inhibition else None,
                },
            }
        )

    async def handle_coordinator_abort(self, request: Request) -> JSONResponse:
        """Trigger emergency abort to stop admission and prevent miner restarts."""
        svc = self.admission_controller.service
        if not svc:
            return JSONResponse({"error": "No managed service bound to coordinator"}, status_code=503)
        token = os.environ.get("RESOURCE_COORDINATOR_OPERATOR_TOKEN") or self.recovery_token
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
        return JSONResponse(res)

    async def handle_coordinator_recover(self, request: Request) -> JSONResponse:
        """Explicit authenticated operator override; no upstream idle verifier exists yet."""
        if not self.recovery_token:
            return JSONResponse({"error": "Recovery is disabled: configure an operator token"}, status_code=503)
        supplied = request.headers.get("authorization", "")
        if not secrets.compare_digest(supplied, "Bearer " + self.recovery_token):
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
        try:
            cleared = await self.lease_mgr.clear_inhibition(
                resource, origin=f"operator_override:{operator}:{reason}", require_all_idle=True
            )
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        return JSONResponse(
            {
                "status": "cleared" if cleared else "none",
                "resource": resource,
                "previous_inhibition": cleared.to_dict() if cleared else None,
                "operator": operator,
                "reason": reason,
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

        reservation_cm = self.lease_mgr.reserve(resource, lease_type, request_id, {"model": model_name, "path": path})
        reservation = await reservation_cm.__aenter__()
        upstream_resp: Optional[httpx.Response] = None
        forwarded = False
        completed = False
        response_owns_cleanup = False
        cleaned = False

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
                            "Stream ended without completion signal or execution termination uncertain",
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
                        await reservation_cm.__aexit__(None, None, None)

        try:
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
            forwarded = True  # send may have reached upstream even if it raises/cancels
            upstream_resp = await client.send(upstream_req, stream=True)
            content_type = upstream_resp.headers.get("content-type", "")
            clean_headers = self._clean_headers(upstream_resp.headers, request_id)
            if "text/event-stream" in content_type:
                detector = StreamCompletionDetector()
                response = upstream_resp

                async def stream_body() -> AsyncIterator[bytes]:
                    nonlocal completed
                    async for chunk in response.aiter_bytes():
                        detector.feed(chunk)
                        yield chunk
                    # Require both protocol completion and normal EOF, never a choice-level marker alone.
                    completed = response.status_code == 200 and detector.finalize()

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
            return Response(content=content, status_code=upstream_resp.status_code, headers=clean_headers)
        except VetoOperation as exc:
            return JSONResponse(
                {"error": {"message": str(exc), "type": "coordinator_veto", "request_id": request_id}}, status_code=503
            )
        except Exception as exc:
            logger.error("Coordinated request %s failed: %s", request_id, exc)
            return JSONResponse(
                {"error": {"message": "Coordinated request failed", "type": "upstream_error"}},
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
