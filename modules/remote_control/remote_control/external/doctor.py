"""Read-only preflight diagnostics and health verification for external public HTTPS rollout.

CRITICAL INVARIANT (Amendment 2):
Diagnostics (doctor and status) are 100% read-only.
They MUST NEVER clear barriers, reconcile executions, release holds, or mutate database/system state.
"""

from __future__ import annotations

import logging
import socket
from typing import Any, Dict, List, Optional

from remote_control.actions.storage import ActionStorage
from remote_control.config import RemoteControlConfig
from remote_control.external.client import TailscaleClientProtocol, get_tailscale_client

logger = logging.getLogger(__name__)


class ExternalDoctor:
    """Performs non-mutating preflight validation checks for external exposure."""

    def __init__(
        self,
        config: RemoteControlConfig,
        storage: ActionStorage,
        client: Optional[TailscaleClientProtocol] = None,
    ) -> None:
        self.config = config
        self.storage = storage
        self.client = client or get_tailscale_client()

    def check_local_listener(self, host: str = "127.0.0.1", port: int = 8443) -> Dict[str, Any]:
        """Check whether the local dashboard service is actively listening on localhost."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        try:
            res = s.connect_ex((host, port))
            is_listening = (res == 0)
            return {
                "ok": is_listening,
                "host": host,
                "port": port,
                "status": "listening" if is_listening else "offline",
                "message": "Local service is reachable on localhost." if is_listening else f"No process responding on {host}:{port}.",
            }
        except Exception as exc:
            return {
                "ok": False,
                "host": host,
                "port": port,
                "status": "error",
                "message": f"Socket check failed: {exc}",
            }
        finally:
            s.close()

    def check_tailscale(self) -> Dict[str, Any]:
        """Check Tailscale installation, login, and node identity."""
        st = self.client.get_status()
        return {
            "ok": st.installed and st.logged_in,
            "installed": st.installed,
            "version": st.version,
            "logged_in": st.logged_in,
            "node_name": st.node_name,
            "tailnet_name": st.tailnet_name,
            "funnel_available": st.funnel_available,
            "funnel_active": st.funnel_active,
            "public_url": st.public_url,
        }

    def check_cookie_and_origin_policy(self) -> Dict[str, Any]:
        """Verify cookie security mode and origin pinning settings."""
        is_valid = (
            self.config.cookie_security_mode in ("strict", "auto")
            or self.config.cookie_secure
        )
        has_origin = bool(self.config.public_origin)
        return {
            "ok": is_valid,
            "cookie_security_mode": self.config.cookie_security_mode,
            "cookie_secure": self.config.cookie_secure,
            "public_origin": self.config.public_origin,
            "origin_pinned": has_origin,
            "allowed_public_hosts": self.config.allowed_public_hosts,
            "trusted_proxy_peers": getattr(self.config, "trusted_proxy_peers", ["127.0.0.1", "::1"]),
        }

    def check_active_barriers(self) -> Dict[str, Any]:
        """Read-only inspection of active execution barriers."""
        barriers = self.storage.list_active_barriers()
        return {
            "ok": True,
            "active_count": len(barriers),
            "items": barriers,
            "requires_reconciliation": len(barriers) > 0,
        }

    def check_all(self) -> Dict[str, Any]:
        """Run all non-mutating preflight checks and compile diagnostic report."""
        listener = self.check_local_listener(host=self.config.host, port=self.config.port)
        tailscale = self.check_tailscale()
        security = self.check_cookie_and_origin_policy()
        barriers = self.check_active_barriers()

        overall_ok = tailscale["installed"] and security["ok"]

        return {
            "ok": overall_ok,
            "read_only": True,
            "checks": {
                "local_listener": listener,
                "tailscale": tailscale,
                "security_configuration": security,
            },
            "barriers": barriers,
        }
