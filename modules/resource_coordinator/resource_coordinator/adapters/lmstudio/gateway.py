"""
Transparent asynchronous reverse proxy gateway for LM Studio with inference activity coordination.
"""

from __future__ import annotations

import json
import logging
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
    ) -> None:
        self.upstream_url = upstream_url.rstrip("/")
        self.dispatcher = event_dispatcher or EventDispatcher()
        self.lease_mgr = lease_manager or LeaseManager(event_dispatcher=self.dispatcher)
        self.timeout_seconds = timeout_seconds
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
            Route("/{path:path}", self.handle_proxy, methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"]),
        ]
        app = Starlette(routes=routes, lifespan=lifespan)
        return app

    async def handle_coordinator_status(self, request: Request) -> JSONResponse:
        """Expose internal coordinator health and lease metrics."""
        return JSONResponse(
            {
                "status": "online",
                "upstream_url": self.upstream_url,
                "gpu_inference": {
                    "active_count": self.lease_mgr.active_count("gpu.inference"),
                    "pending_count": self.lease_mgr.pending_count("gpu.inference"),
                    "is_cooling_down": self.lease_mgr.is_cooling_down("gpu.inference"),
                    "cooldown_remaining": round(self.lease_mgr.cooldown_remaining("gpu.inference"), 1),
                },
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
        """Forward an inference or model load request after acquiring resource lease."""
        event_data = {
            "request_id": request_id,
            "path": path,
            "model": model_name,
            "resource": resource,
        }

        # Blocking hook: allows miner to be stopped and verified stopped before proceeding
        try:
            await self.dispatcher.emit_blocking(event_name, event_data, origin="lmstudio_gateway")
        except VetoOperation as veto:
            logger.warning("Request %s vetoed by coordinator: %s", request_id, veto)
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

        client = self.get_http_client()
        upstream_req = self._build_upstream_request(client, request, path, body, request_id)

        try:
            # Acquire lease for the duration of inference
            lease_cm = self.lease_mgr.acquire(
                resource=resource,
                lease_type=lease_type,
                holder_id=request_id,
                metadata={"model": model_name, "path": path},
            )
            _lease = await lease_cm.__aenter__()
        except Exception as exc:
            logger.error("Failed to acquire lease for %s: %s", request_id, exc)
            return JSONResponse(
                {"error": {"message": f"Failed to acquire lease: {exc}", "type": "coordinator_lease_error"}},
                status_code=500,
            )

        try:
            upstream_resp = await client.send(upstream_req, stream=True)
        except Exception as exc:
            await lease_cm.__aexit__(type(exc), exc, exc.__traceback__)
            await self.dispatcher.emit(finish_event, {**event_data, "status": "upstream_error", "error": str(exc)})
            logger.error("Failed to reach upstream for %s: %s", request_id, exc)
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

            async def _stream_body() -> AsyncIterator[bytes]:
                try:
                    async for chunk in upstream_resp.aiter_bytes():
                        yield chunk
                except Exception as stream_exc:
                    logger.warning("Streaming interrupted for %s: %s", request_id, stream_exc)
                finally:
                    await upstream_resp.aclose()
                    await lease_cm.__aexit__(None, None, None)
                    await self.dispatcher.emit(finish_event, {**event_data, "status": "completed"})

            return StreamingResponse(
                _stream_body(),
                status_code=upstream_resp.status_code,
                headers=clean_headers,
                media_type=content_type,
            )
        else:
            try:
                content = await upstream_resp.aread()
                return Response(
                    content=content,
                    status_code=upstream_resp.status_code,
                    headers=clean_headers,
                )
            finally:
                await upstream_resp.aclose()
                await lease_cm.__aexit__(None, None, None)
                await self.dispatcher.emit(finish_event, {**event_data, "status": "completed"})

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
