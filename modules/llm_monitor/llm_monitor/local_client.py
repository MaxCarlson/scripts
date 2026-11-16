"""Client for interacting with a managed LLM Monitor instance.

Acquires ephemeral scoped read capability tokens over the local control channel,
caches them in memory, attaches them as Authorization: Bearer headers, and
automatically handles at-most-once token refresh upon 401 responses.
"""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from .local_control import LocalControlClient
from .server_lifecycle import ServerDescriptor, descriptor_path, read_descriptor, verify_running_instance


class ManagedMonitorClientError(RuntimeError):
    """Base error for managed monitor client operations."""


class ManagedMonitorAuthError(ManagedMonitorClientError):
    """Authentication or capability issuance failure."""


class ManagedMonitorClient:
    """Client for querying an authenticated, managed local LLM Monitor server."""

    def __init__(
        self,
        port: int = 8788,
        host: str = "127.0.0.1",
        state_dir: Path | str | None = None,
        descriptor: ServerDescriptor | None = None,
    ) -> None:
        self.port = port
        self.host = host
        self.state_dir = state_dir
        self._descriptor = descriptor
        self._capability_token: str | None = None
        self._token_expires_at: float = 0.0
        self._control_client: LocalControlClient | None = None

    @property
    def base_url(self) -> str:
        clean_host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{clean_host}:{self.port}"

    def ensure_descriptor(self) -> ServerDescriptor:
        """Resolve and verify the server descriptor for this client."""
        if self._descriptor is not None:
            return self._descriptor

        desc_p = descriptor_path(self.port, self.host, state_dir=self.state_dir)
        desc = read_descriptor(desc_p)
        if desc is None:
            raise ManagedMonitorClientError(
                f"No server descriptor found on {self.host}:{self.port}. Is LLM Monitor running?"
            )

        info = verify_running_instance(desc, timeout=1.5)
        if info is None:
            raise ManagedMonitorClientError(
                f"Process {desc.pid} on port {desc.port} failed instance verification."
            )

        self._descriptor = desc
        return desc

    def acquire_capability_token(self, force_refresh: bool = False, requested_scopes: list[str] | None = None) -> str:
        """Acquire a scoped read capability token, reusing cached unexpired token if valid."""
        now = time.time()
        if requested_scopes is None and not force_refresh and self._capability_token and now < (self._token_expires_at - 5.0):
            return self._capability_token

        desc = self.ensure_descriptor()
        endpoint = desc.control_endpoint
        if not endpoint:
            # Fall back to default pipe / socket naming
            if desc.host == "127.0.0.1":
                import sys
                if sys.platform == "win32":
                    endpoint = rf"\\.\pipe\llm-monitor-{desc.instance_id}"
                else:
                    endpoint = f"/tmp/llm_monitor_{os.getuid()}/control_{desc.instance_id}.sock"

        if not endpoint:
            raise ManagedMonitorAuthError("Server descriptor does not define a local control endpoint.")

        client = LocalControlClient(endpoint, desc.instance_id)
        try:
            resp = client.issue_read_capability(
                requested_scopes=requested_scopes or [
                    "inference:models:read",
                    "inference:status:read",
                    "recording:health:read",
                    "requests:summary:read",
                    "history:verification:read",
                ],
                ttl_seconds=120.0,
            )
        except Exception as err:
            raise ManagedMonitorAuthError(f"Failed to communicate with local control channel: {err}") from err

        token = resp.get("capability_token")
        if not token:
            raise ManagedMonitorAuthError(f"Control channel failed to issue capability token: {resp.get('detail')}")

        self._capability_token = token
        self._token_expires_at = now + float(resp.get("expires_in_seconds", 120.0))
        return token

    def request_json(self, method: str, path: str) -> dict[str, Any]:
        """Perform an authenticated GET request against an API route with at-most-once 401 refresh."""
        token = self.acquire_capability_token()
        try:
            return self._execute_request(method, path, token)
        except urllib.error.HTTPError as err:
            if err.code == 401:
                # Refresh token once and retry
                new_token = self.acquire_capability_token(force_refresh=True)
                try:
                    return self._execute_request(method, path, new_token)
                except urllib.error.HTTPError as retry_err:
                    raise ManagedMonitorAuthError(
                        f"Authentication failed on retry for {path} (HTTP {retry_err.code})"
                    ) from retry_err
            raise

    def _execute_request(self, method: str, path: str, token: str) -> dict[str, Any]:
        url = urllib.parse.urljoin(self.base_url, path)
        host_header = f"{self.host}:{self.port}"
        req = urllib.request.Request(
            url,
            method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Host": host_header,
                "Origin": f"http://{host_header}",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data)

    def get_models(self) -> dict[str, Any]:
        """Query /api/inference/v1/models."""
        return self.request_json("GET", "/api/inference/v1/models")

    def get_status(self) -> dict[str, Any]:
        """Query /api/inference/v1/status."""
        return self.request_json("GET", "/api/inference/v1/status")

    def get_recording_status(self) -> dict[str, Any]:
        """Query /api/inference/v1/recording/status."""
        return self.request_json("GET", "/api/inference/v1/recording/status")

    def get_requests(self) -> dict[str, Any]:
        """Query /api/inference/v1/requests."""
        return self.request_json("GET", "/api/inference/v1/requests")
