"""
Transparent asynchronous reverse proxy gateway for LM Studio with inference activity coordination.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import AsyncIterator, Dict, Optional, Set

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

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

INFERENCE_PATHS: Set[str] = {
    "/v1/chat/completions",
    "/v1/completions",
    "/v1/embeddings",
    "/v1/responses",
    "/api/v1/chat",
    "/api/v0/chat/completions",
}

MODEL_LOAD_PATHS: Set[str] = {
    "/api/v0/model/load",
    "/api/v1/models/load",
}


def is_inference_request(method: str, path: str) -> bool:
    """Determine whether an incoming request represents active inference."""
    if method.upper() != "POST":
        return False
    normalized = path.rstrip("/")
    return normalized in INFERENCE_PATHS or normalized.endswith("/chat/completions")


def is_model_load_request(method: str, path: str) -> bool:
    """Determine whether an incoming request represents model loading."""
    if method.upper() != "POST":
        return False
    normalized = path.rstrip("/")
    return normalized in MODEL_LOAD_PATHS or normalized.endswith("/models/load")


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
        self._buffer = ""

    def feed(self, chunk: bytes) -> None:
        if self.confirmed:
            return
        text = chunk.decode("utf-8", errors="replace")
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            if line in ("data: [DONE]", "[DONE]", "event: done", "event: finish"):
                self.confirmed = True
                self.termination_state = "confirmed_done_marker"
                return
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload == "[DONE]":
                    self.confirmed = True
                    self.termination_state = "confirmed_done_marker"
                    return
                try:
                    data = json.loads(payload)
                    if isinstance(data, dict):
                        choices = data.get("choices")
                        if choices and isinstance(choices, list) and len(choices) > 0:
                            fr = choices[0].get("finish_reason")
                            if fr is not None:
                                self.finish_reason = str(fr)
                                self.confirmed = True
                                self.termination_state = f"confirmed_finish_reason:{fr}"
                                return
                except Exception:
                    pass

    def finalize(self) -> bool:
        if self.confirmed:
            return True
        rem = self._buffer.strip()
        if rem in ("data: [DONE]", "[DONE]", "event: done", "event: finish"):
            self.confirmed = True
            self.termination_state = "confirmed_done_marker"
            return True
        if rem.startswith("data:"):
            payload = rem[5:].strip()
            if payload == "[DONE]":
                self.confirmed = True
                self.termination_state = "confirmed_done_marker"
                return True
        return False

    @staticmethod
    def check_non_streaming(status_code: int, body: bytes) -> bool:
        if status_code != 200:
            return False
        if not body:
            return False
        try:
            data = json.loads(body)
            if isinstance(data, dict):
                if "error" in data:
                    return False
                if "choices" in data and isinstance(data["choices"], list):
                    return True
                if "data" in data and isinstance(data["data"], list):
                    return True
                return True
        except Exception:
            return False
        return False


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
    ) -> None:
        self.upstream_url = upstream_url.rstrip("/")
        self.dispatcher = event_dispatcher or EventDispatcher()
        self.lease_mgr = lease_manager or LeaseManager(event_dispatcher=self.dispatcher)
        self.timeout_seconds = timeout_seconds
        self.bounded_drain_seconds = bounded_drain_seconds
        self._http_client: Optional[httpx.AsyncClient] = None

    def get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                base_url=self.upstream_url,
                timeout=httpx.Timeout(self.timeout_seconds, connect=10.0),
                follow_redirects=True,
            )
        return self._http_client

    async def close(self) -> None:
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    def create_app(self) -> Starlette:
        """Create Starlette ASGI application for the proxy."""
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def lifespan(app: Starlette):
            yield
            await self.close()

        routes = [
            Route("/_coordinator/status", self.handle_coordinator_status, methods=["GET"]),
            Route("/_coordinator/recover", self.handle_coordinator_recover, methods=["POST"]),
            Route("/{path:path}", self.handle_proxy, methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"]),
        ]
        app = Starlette(routes=routes, lifespan=lifespan)
        return app

    async def handle_coordinator_status(self, request: Request) -> JSONResponse:
        """Expose internal coordinator health, lease metrics, and restart inhibition state."""
        inhibition = self.lease_mgr.get_inhibition("gpu.inference")
        return JSONResponse(
            {
                "status": "online",
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

    async def handle_coordinator_recover(self, request: Request) -> JSONResponse:
        """Clear protective restart inhibition and restore idle scheduling."""
        resource = request.query_params.get("resource", "gpu.inference")
        cleared = await self.lease_mgr.clear_inhibition(resource, origin="api_recovery")
        return JSONResponse(
            {
                "status": "cleared" if cleared else "none",
                "resource": resource,
                "previous_inhibition": cleared.to_dict() if cleared else None,
            }
        )

    async def handle_proxy(self, request: Request) -> Response:
        path = "/" + request.path_params.get("path", "").lstrip("/")
        method = request.method
        request_id = f"coord-{uuid.uuid4().hex[:12]}"

        # Read body
        body = await request.body()
        model_name = ""
        if body:
            try:
                body_json = json.loads(body)
                if isinstance(body_json, dict):
                    model_name = str(body_json.get("model", ""))
            except Exception:
                pass

        # Check if inference or model load
        if is_inference_request(method, path):
            return await self._proxy_with_coordination(
                request=request,
                path=path,
                body=body,
                request_id=request_id,
                resource="gpu.inference",
                lease_type=LeaseType.SHARED,
                event_name="lmstudio.inference_requested",
                finish_event="lmstudio.inference_finished",
                model_name=model_name,
            )
        elif is_model_load_request(method, path):
            return await self._proxy_with_coordination(
                request=request,
                path=path,
                body=body,
                request_id=request_id,
                resource="gpu.model_loading",
                lease_type=LeaseType.EXCLUSIVE,
                event_name="lmstudio.model_load_requested",
                finish_event="lmstudio.model_load_finished",
                model_name=model_name,
            )
        else:
            # Metadata / read request - forward directly without stopping mining
            return await self._forward_direct(request, path, body, request_id)

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
        """Forward an inference or model load request with atomic registration and robust termination tracking."""
        event_data = {
            "request_id": request_id,
            "path": path,
            "model": model_name,
            "resource": resource,
        }

        # 1. ATOMIC REGISTRATION: reserve pending claim and cancel idle cooldown BEFORE blocking hooks
        reservation_cm = self.lease_mgr.reserve(
            resource=resource,
            lease_type=lease_type,
            holder_id=request_id,
            metadata={"model": model_name, "path": path},
        )
        reservation = await reservation_cm.__aenter__()

        # 2. Blocking hooks: allows miner to be stopped and verified stopped before proceeding
        try:
            await self.dispatcher.emit_blocking(event_name, event_data, origin="lmstudio_gateway")
        except VetoOperation as veto:
            logger.warning("Request %s vetoed by coordinator: %s", request_id, veto)
            await reservation_cm.__aexit__(None, None, None)
            return JSONResponse(
                {
                    "error": {
                        "message": str(veto),
                        "type": "coordinator_veto",
                        "request_id": request_id,
                    }
                },
                status_code=503,
            )
        except Exception as exc:
            logger.error("Pre-inference coordination failed for %s: %s", request_id, exc)
            await reservation_cm.__aexit__(None, None, None)
            return JSONResponse(
                {
                    "error": {
                        "message": f"Pre-inference coordination failure: {exc}",
                        "type": "coordinator_failure",
                        "request_id": request_id,
                    }
                },
                status_code=500,
            )

        # 3. Promote reservation to active lease
        try:
            await reservation.activate(timeout=self.timeout_seconds)
        except Exception as exc:
            logger.error("Failed to activate lease for %s: %s", request_id, exc)
            await reservation_cm.__aexit__(None, None, None)
            return JSONResponse(
                {"error": {"message": f"Failed to activate lease: {exc}", "type": "coordinator_lease_error"}},
                status_code=500,
            )

        client = self.get_http_client()
        upstream_req = self._build_upstream_request(client, request, path, body, request_id)

        try:
            upstream_resp = await client.send(upstream_req, stream=True)
        except Exception as exc:
            logger.error("Failed to reach upstream for %s: %s", request_id, exc)
            await self.lease_mgr.inhibit_restart(
                resource=resource,
                reason=f"Failed to connect to upstream LM Studio: {exc}",
                holder_id=request_id,
                details={"error": str(exc), "model": model_name},
            )
            await self.dispatcher.emit(finish_event, {**event_data, "status": "upstream_error", "error": str(exc)})
            await reservation_cm.__aexit__(type(exc), exc, exc.__traceback__)
            return JSONResponse(
                {"error": {"message": f"Failed to connect to LM Studio: {exc}", "type": "upstream_error"}},
                status_code=502,
            )

        content_type = upstream_resp.headers.get("content-type", "")
        is_streaming = (
            "text/event-stream" in content_type or upstream_resp.headers.get("transfer-encoding") == "chunked"
        )
        clean_headers = self._clean_headers(upstream_resp.headers, request_id)

        if is_streaming:
            detector = StreamCompletionDetector(is_sse="text/event-stream" in content_type)

            async def _stream_body() -> AsyncIterator[bytes]:
                interrupted = False
                interrupted_exc: Optional[BaseException] = None
                try:
                    async for chunk in upstream_resp.aiter_bytes():
                        detector.feed(chunk)
                        yield chunk
                except (asyncio.CancelledError, Exception) as stream_exc:
                    interrupted = True
                    interrupted_exc = stream_exc
                    logger.warning("Streaming interrupted for %s: %s", request_id, stream_exc)
                finally:
                    detector.finalize()

                    # Bounded drain: optional, explicitly opt-in best-effort drain on client disconnect
                    if (
                        interrupted
                        and not detector.confirmed
                        and self.bounded_drain_seconds
                        and self.bounded_drain_seconds > 0
                    ):
                        logger.info(
                            "Attempting bounded drain for %s (up to %.1fs)", request_id, self.bounded_drain_seconds
                        )
                        try:
                            drain_deadline = time.time() + self.bounded_drain_seconds
                            while time.time() < drain_deadline and not detector.confirmed:
                                rem = drain_deadline - time.time()
                                if rem <= 0:
                                    break
                                chunk = await asyncio.wait_for(upstream_resp.aiter_bytes().__anext__(), timeout=rem)
                                detector.feed(chunk)
                        except (StopAsyncIteration, asyncio.TimeoutError, Exception) as drain_exc:
                            logger.debug("Bounded drain ended for %s: %s", request_id, drain_exc)
                        detector.finalize()

                    await upstream_resp.aclose()

                    if detector.confirmed:
                        if self.lease_mgr.is_restart_inhibited(resource):
                            await self.lease_mgr.clear_inhibition(resource, origin="inference_recovery")
                        await self.dispatcher.emit(
                            finish_event,
                            {**event_data, "status": "completed", "termination": detector.termination_state},
                        )
                    else:
                        reason = (
                            "Client disconnected before stream completed"
                            if interrupted
                            else "Stream ended without completion signal"
                        )
                        logger.warning("Inference termination uncertain for %s: %s", request_id, reason)
                        await self.lease_mgr.inhibit_restart(
                            resource=resource,
                            reason=reason,
                            holder_id=request_id,
                            details={
                                "model": model_name,
                                "path": path,
                                "error": str(interrupted_exc) if interrupted_exc else None,
                            },
                        )
                        await self.dispatcher.emit(
                            finish_event,
                            {**event_data, "status": "uncertain", "error": reason},
                        )

                    await reservation_cm.__aexit__(None, None, None)

            return StreamingResponse(
                _stream_body(),
                status_code=upstream_resp.status_code,
                headers=clean_headers,
                media_type=content_type,
            )
        else:
            try:
                content = await upstream_resp.aread()
                is_ok = StreamCompletionDetector.check_non_streaming(upstream_resp.status_code, content)
                if is_ok:
                    if self.lease_mgr.is_restart_inhibited(resource):
                        await self.lease_mgr.clear_inhibition(resource, origin="inference_recovery")
                    await self.dispatcher.emit(finish_event, {**event_data, "status": "completed"})
                else:
                    reason = f"Upstream returned status {upstream_resp.status_code} or malformed response"
                    logger.warning("Inference response uncertain for %s: %s", request_id, reason)
                    await self.lease_mgr.inhibit_restart(
                        resource=resource,
                        reason=reason,
                        holder_id=request_id,
                        details={"status_code": upstream_resp.status_code, "model": model_name, "path": path},
                    )
                    await self.dispatcher.emit(finish_event, {**event_data, "status": "uncertain", "error": reason})

                return Response(
                    content=content,
                    status_code=upstream_resp.status_code,
                    headers=clean_headers,
                )
            finally:
                await upstream_resp.aclose()
                await reservation_cm.__aexit__(None, None, None)

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
            if k.lower() not in HOP_BY_HOP_HEADERS:
                clean[k] = v
        clean["x-coordinator-request-id"] = request_id
        return clean
