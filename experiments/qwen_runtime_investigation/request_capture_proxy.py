#!/usr/bin/env python3
"""Loopback-only LM Studio forwarder that persists allowlisted request metadata only."""

from __future__ import annotations

__version__ = "0.1.0"

import argparse
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
from pathlib import Path

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from request_capture import safe_request_summary


UPSTREAM_BASE_URL = "http://127.0.0.1:1234"
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 1235
ALLOWED_MODEL_IDS = {"qwen38_23GB", "qwen38-27b-q4km"}
HOP_BY_HOP_HEADERS = {
    "connection",
    "content-length",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
RESPONSE_HEADERS = {"cache-control", "content-encoding", "content-length", "content-type"}


def create_app(
    capture_path: Path,
    *,
    upstream_base_url: str = UPSTREAM_BASE_URL,
    upstream_transport: httpx.AsyncBaseTransport | None = None,
) -> Starlette:
    capture_path = Path(capture_path).resolve()
    upstream_base_url = upstream_base_url.rstrip("/")

    @asynccontextmanager
    async def lifespan(app: Starlette):
        async with httpx.AsyncClient(
            transport=upstream_transport,
            timeout=None,
            trust_env=False,
        ) as client:
            app.state.upstream_client = client
            yield

    async def forward_models(request: Request) -> Response:
        return await _forward(request, capture=False)

    async def forward_chat(request: Request) -> Response:
        try:
            body = await request.body()
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JSONResponse({"error": "invalid JSON request"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"error": "request must be a JSON object"}, status_code=400)

        model = payload.get("model")
        if not isinstance(model, str) or model not in ALLOWED_MODEL_IDS:
            return JSONResponse({"error": "model is outside the capture scope"}, status_code=409)

        summary = safe_request_summary(request.url.path, payload)
        record = {
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "provider": "lmstudio",
            **summary,
        }
        capture_path.parent.mkdir(parents=True, exist_ok=True)
        with capture_path.open("a", encoding="utf-8", newline="\n") as capture:
            capture.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")
            capture.flush()

        return await _forward(request, capture=True, raw_body=body)

    async def _forward(
        request: Request,
        *,
        capture: bool,
        raw_body: bytes | None = None,
    ) -> Response:
        del capture  # Route selection and body retention are explicit at the call site.
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS
        }
        outbound = request.app.state.upstream_client.build_request(
            request.method,
            f"{upstream_base_url}{request.url.path}",
            params=request.query_params,
            headers=headers,
            content=raw_body if raw_body is not None else await request.body(),
        )
        try:
            upstream_response = await request.app.state.upstream_client.send(outbound, stream=True)
        except httpx.RequestError:
            return JSONResponse({"error": "LM Studio upstream unavailable"}, status_code=502)

        response_headers = {
            key: value
            for key, value in upstream_response.headers.items()
            if key.lower() in RESPONSE_HEADERS
        }

        async def chunks():
            try:
                async for chunk in upstream_response.aiter_raw():
                    yield chunk
            finally:
                await upstream_response.aclose()

        return StreamingResponse(
            chunks(),
            status_code=upstream_response.status_code,
            headers=response_headers,
        )

    app = Starlette(
        routes=[
            Route("/v1/models", forward_models, methods=["GET"]),
            Route("/v1/chat/completions", forward_chat, methods=["POST"]),
        ],
        lifespan=lifespan,
    )
    return app


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-V", "--version", action="version", version=__version__)
    parser.add_argument("-o", "--capture-file", required=True, type=Path)
    args = parser.parse_args()
    uvicorn.run(
        create_app(args.capture_file),
        host=LISTEN_HOST,
        port=LISTEN_PORT,
        access_log=False,
        log_level="warning",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
