from __future__ import annotations

import json
import socket
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, Optional, Tuple


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Dict[str, str]
    body: bytes


class HttpError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, body: bytes | None = None):
        super().__init__(message)
        self.status = status
        self.body = body or b""


class HttpClient:
    def __init__(self, timeout_seconds: float = 60.0, verify_tls: bool = True):
        self._timeout = float(timeout_seconds)
        self._verify_tls = bool(verify_tls)

    def _ssl_context(self) -> ssl.SSLContext | None:
        if self._verify_tls:
            return None
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        json_body: Any | None = None,
        raw_body: bytes | None = None,
    ) -> HttpResponse:
        method = method.upper().strip()
        headers = dict(headers or {})

        data: bytes | None = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        elif raw_body is not None:
            data = raw_body

        req = urllib.request.Request(url=url, method=method, headers=headers, data=data)

        try:
            with urllib.request.urlopen(req, timeout=self._timeout, context=self._ssl_context()) as resp:
                status = int(getattr(resp, "status", 200))
                resp_headers = {k.lower(): v for k, v in resp.headers.items()}
                body = resp.read()
                return HttpResponse(status=status, headers=resp_headers, body=body)
        except urllib.error.HTTPError as e:
            body = e.read() if hasattr(e, "read") else b""
            raise HttpError(f"HTTP {e.code} for {method} {url}", status=int(e.code), body=body) from e
        except (urllib.error.URLError, socket.timeout) as e:
            raise HttpError(f"Network error for {method} {url}: {e}") from e

    def get_json(self, url: str, headers: Optional[Dict[str, str]] = None) -> Any:
        resp = self.request("GET", url, headers=headers)
        if resp.status < 200 or resp.status >= 300:
            raise HttpError(f"Unexpected status {resp.status} for GET {url}", status=resp.status, body=resp.body)
        if not resp.body:
            return None
        return json.loads(resp.body.decode("utf-8", errors="replace"))

    def post_json(self, url: str, json_body: Any, headers: Optional[Dict[str, str]] = None) -> Any:
        resp = self.request("POST", url, headers=headers, json_body=json_body)
        if resp.status < 200 or resp.status >= 300:
            raise HttpError(f"Unexpected status {resp.status} for POST {url}", status=resp.status, body=resp.body)
        if not resp.body:
            return None
        return json.loads(resp.body.decode("utf-8", errors="replace"))

    def stream_lines(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        json_body: Any | None = None,
    ) -> Iterator[str]:
        """
        Yield decoded text lines from a streaming HTTP response.
        Used for SSE style streaming (data: ...\n\n).
        """
        method = method.upper().strip()
        headers = dict(headers or {})

        data: bytes | None = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")

        req = urllib.request.Request(url=url, method=method, headers=headers, data=data)

        try:
            with urllib.request.urlopen(req, timeout=self._timeout, context=self._ssl_context()) as resp:
                while True:
                    line = resp.readline()
                    if not line:
                        break
                    yield line.decode("utf-8", errors="replace").rstrip("\r\n")
        except urllib.error.HTTPError as e:
            body = e.read() if hasattr(e, "read") else b""
            raise HttpError(f"HTTP {e.code} for {method} {url}", status=int(e.code), body=body) from e
        except (urllib.error.URLError, socket.timeout) as e:
            raise HttpError(f"Network error for {method} {url}: {e}") from e
