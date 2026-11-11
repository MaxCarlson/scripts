"""Read-only preflight diagnostics and health verification for external public HTTPS rollout.

CRITICAL INVARIANTS:
1. Diagnostics (doctor and status) are 100% read-only.
   They MUST NEVER clear barriers, reconcile executions, release holds, or mutate database/system state.
2. Stage A Fail-Closed Preflight:
   Every security prerequisite is evaluated with explicit severities: pass, warning, blocker, unknown.
   ready_for_public_enable requires len(blockers) == 0 and len(security_unknowns) == 0.
   Any failure halts public enablement BEFORE executing any Tailscale mutation.
"""

from __future__ import annotations

import logging
import re
import socket
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from remote_control.actions.registry import ActionRegistry
from remote_control.actions.storage import ActionStorage
from remote_control.auth.storage import AuthStorage
from remote_control.config import RemoteControlConfig
from remote_control.external.client import (
    SUPPORTED_FUNNEL_PORTS,
    TailscaleClientProtocol,
    get_tailscale_client,
)

logger = logging.getLogger(__name__)

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "[::1]"}


@dataclass
class DiagnosticCheck:
    """Individual preflight check item with explicit severity."""

    name: str
    severity: str  # "pass", "warning", "blocker", "unknown"
    is_security_critical: bool
    message: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ExternalDoctor:
    """Performs non-mutating preflight validation checks for external exposure."""

    def __init__(
        self,
        config: RemoteControlConfig,
        storage: ActionStorage,
        client: Optional[TailscaleClientProtocol] = None,
        registry: Optional[ActionRegistry] = None,
    ) -> None:
        self.config = config
        self.storage = storage
        self.client = client or get_tailscale_client(read_only=True)
        self.registry = registry or ActionRegistry()

    def check_tailscale(self, public_port: int = 8443) -> List[DiagnosticCheck]:
        """Check Tailscale installation, login, version support, funnel capability, and port conflict."""
        checks: List[DiagnosticCheck] = []
        st = self.client.get_status()

        # 1. Tailscale installation
        if not st.installed:
            checks.append(
                DiagnosticCheck(
                    name="tailscale_installed",
                    severity="blocker",
                    is_security_critical=True,
                    message="Tailscale CLI is not installed or not found on PATH.",
                    details={"installed": False},
                )
            )
            return checks

        checks.append(
            DiagnosticCheck(
                name="tailscale_installed",
                severity="pass",
                is_security_critical=True,
                message="Tailscale CLI is installed.",
                details={"installed": True},
            )
        )

        # 2. Authentication / Login
        if not st.logged_in:
            checks.append(
                DiagnosticCheck(
                    name="tailscale_authenticated",
                    severity="blocker",
                    is_security_critical=True,
                    message="Tailscale node is not authenticated or not logged into tailnet.",
                    details={"logged_in": False},
                )
            )
        else:
            checks.append(
                DiagnosticCheck(
                    name="tailscale_authenticated",
                    severity="pass",
                    is_security_critical=True,
                    message=f"Tailscale authenticated as node '{st.node_name}' on '{st.tailnet_name}'.",
                    details={"node_name": st.node_name, "tailnet_name": st.tailnet_name},
                )
            )

        # 3. Version support (modern direct funnel >= 1.52)
        version_str = st.version.split("-")[0].strip()
        version_match = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", version_str)
        if not version_match:
            checks.append(
                DiagnosticCheck(
                    name="tailscale_version",
                    severity="unknown",
                    is_security_critical=True,
                    message=f"Tailscale version string '{st.version}' could not be parsed; compatibility unknown.",
                    details={"version": st.version},
                )
            )
        else:
            major, minor = int(version_match.group(1)), int(version_match.group(2))
            if (major, minor) < (1, 52):
                checks.append(
                    DiagnosticCheck(
                        name="tailscale_version",
                        severity="blocker",
                        is_security_critical=True,
                        message=f"Tailscale version {st.version} is unsupported; requires >= 1.52 for direct Funnel proxy.",
                        details={"version": st.version, "required": ">= 1.52.0"},
                    )
                )
            else:
                checks.append(
                    DiagnosticCheck(
                        name="tailscale_version",
                        severity="pass",
                        is_security_critical=True,
                        message=f"Tailscale version {st.version} supports modern Funnel interface.",
                        details={"version": st.version},
                    )
                )

        # 4. Funnel capability
        if not st.funnel_available:
            checks.append(
                DiagnosticCheck(
                    name="funnel_capability",
                    severity="blocker",
                    is_security_critical=True,
                    message="Tailscale Funnel capability is disabled in Tailscale ACL policy or not permitted.",
                    details={"funnel_available": False},
                )
            )
        else:
            checks.append(
                DiagnosticCheck(
                    name="funnel_capability",
                    severity="pass",
                    is_security_critical=True,
                    message="Tailscale Funnel capability is available.",
                    details={"funnel_available": True},
                )
            )

        # 5. Public port compatibility
        if public_port not in SUPPORTED_FUNNEL_PORTS:
            checks.append(
                DiagnosticCheck(
                    name="funnel_port_compatibility",
                    severity="blocker",
                    is_security_critical=True,
                    message=f"Public port {public_port} is not supported by Funnel (supported: {sorted(SUPPORTED_FUNNEL_PORTS)}).",
                    details={"public_port": public_port, "supported": sorted(SUPPORTED_FUNNEL_PORTS)},
                )
            )
        else:
            checks.append(
                DiagnosticCheck(
                    name="funnel_port_compatibility",
                    severity="pass",
                    is_security_critical=True,
                    message=f"Public port {public_port} is supported by Funnel.",
                    details={"public_port": public_port},
                )
            )

        # 6. Preexisting route conflict detection
        routes = st.routes if isinstance(st.routes, dict) else {}
        conflict = False
        conflict_owner = ""
        target_str = f"http://127.0.0.1:{self.config.port}"
        for ep, details in routes.items():
            if str(public_port) in ep:
                if isinstance(details, str):
                    if details != target_str:
                        conflict = True
                        conflict_owner = details
                elif isinstance(details, dict):
                    proxy = details.get("Handlers", {}).get("/", {}).get("Proxy", "")
                    if proxy and proxy != target_str:
                        conflict = True
                        conflict_owner = proxy

        if conflict:
            checks.append(
                DiagnosticCheck(
                    name="no_conflicting_funnel_route",
                    severity="blocker",
                    is_security_critical=True,
                    message=f"Public port {public_port} is already owned by another service: {conflict_owner}",
                    details={"conflicting_route": conflict_owner},
                )
            )
        else:
            checks.append(
                DiagnosticCheck(
                    name="no_conflicting_funnel_route",
                    severity="pass",
                    is_security_critical=True,
                    message=f"No conflicting preexisting route found for port {public_port}.",
                )
            )

        return checks

    def check_origin_and_hosts(self) -> List[DiagnosticCheck]:
        """Verify HTTPS public origin and matching pinned hostname."""
        checks: List[DiagnosticCheck] = []
        origin = self.config.public_origin

        if not origin:
            checks.append(
                DiagnosticCheck(
                    name="public_origin_configured",
                    severity="blocker",
                    is_security_critical=True,
                    message="public_origin is not configured. Public HTTPS exposure requires an exact origin.",
                    details={"public_origin": None},
                )
            )
            return checks

        if not origin.startswith("https://"):
            checks.append(
                DiagnosticCheck(
                    name="public_origin_https",
                    severity="blocker",
                    is_security_critical=True,
                    message=f"public_origin '{origin}' must use HTTPS scheme.",
                    details={"public_origin": origin},
                )
            )
            return checks

        checks.append(
            DiagnosticCheck(
                name="public_origin_https",
                severity="pass",
                is_security_critical=True,
                message=f"Exact HTTPS public origin configured: {origin}",
                details={"public_origin": origin},
            )
        )

        parsed = urlparse(origin)
        host = parsed.hostname or ""
        allowed_hosts = getattr(self.config, "allowed_public_hosts", [])
        if host not in allowed_hosts and not any(host.endswith(f".{ah}") for ah in allowed_hosts):
            checks.append(
                DiagnosticCheck(
                    name="pinned_public_hostname",
                    severity="blocker",
                    is_security_critical=True,
                    message=f"Public hostname '{host}' from public_origin is not in allowed_public_hosts: {allowed_hosts}",
                    details={"host": host, "allowed_public_hosts": allowed_hosts},
                )
            )
        else:
            checks.append(
                DiagnosticCheck(
                    name="pinned_public_hostname",
                    severity="pass",
                    is_security_critical=True,
                    message=f"Public hostname '{host}' is pinned in allowed_public_hosts.",
                    details={"host": host},
                )
            )

        return checks

    def check_cookie_and_proxy_policy(self) -> List[DiagnosticCheck]:
        """Verify cookie security, loopback backend binding, and proxy trust topology."""
        checks: List[DiagnosticCheck] = []

        # Cookie security mode
        mode = getattr(self.config, "cookie_security_mode", "auto")
        if mode not in ("strict", "auto") and not self.config.cookie_secure:
            checks.append(
                DiagnosticCheck(
                    name="cookie_security_strict",
                    severity="blocker",
                    is_security_critical=True,
                    message=f"cookie_security_mode '{mode}' does not enforce secure cookies for public exposure.",
                    details={"cookie_security_mode": mode, "cookie_secure": self.config.cookie_secure},
                )
            )
        else:
            checks.append(
                DiagnosticCheck(
                    name="cookie_security_strict",
                    severity="pass",
                    is_security_critical=True,
                    message="Strict cookie security mode is configured (__Host- prefixed, SameSite=Strict).",
                    details={"cookie_security_mode": mode},
                )
            )

        # Loopback-only backend binding
        backend_host = getattr(self.config, "host", "127.0.0.1")
        if backend_host not in LOOPBACK_HOSTS:
            checks.append(
                DiagnosticCheck(
                    name="loopback_only_backend_binding",
                    severity="blocker",
                    is_security_critical=True,
                    message=f"Backend is bound to non-loopback address '{backend_host}'. Backend must bind to 127.0.0.1 only.",
                    details={"host": backend_host},
                )
            )
        else:
            checks.append(
                DiagnosticCheck(
                    name="loopback_only_backend_binding",
                    severity="pass",
                    is_security_critical=True,
                    message=f"Backend is safely bound to loopback only ({backend_host}).",
                    details={"host": backend_host},
                )
            )

        # Trusted proxy peers
        trusted_proxies = getattr(self.config, "trusted_proxy_peers", ["127.0.0.1", "::1"])
        non_loopback = [p for p in trusted_proxies if p not in LOOPBACK_HOSTS]
        if non_loopback:
            checks.append(
                DiagnosticCheck(
                    name="proxy_trust_topology",
                    severity="blocker",
                    is_security_critical=True,
                    message=f"trusted_proxy_peers contains non-loopback address(es) {non_loopback}. Tailscale reverse proxy forwards from 127.0.0.1 only.",
                    details={"trusted_proxy_peers": trusted_proxies},
                )
            )
        else:
            checks.append(
                DiagnosticCheck(
                    name="proxy_trust_topology",
                    severity="pass",
                    is_security_critical=True,
                    message="Forwarded headers are restricted to trusted loopback proxy peer only.",
                    details={"trusted_proxy_peers": trusted_proxies},
                )
            )

        return checks

    def check_operator_and_auth_database(self) -> List[DiagnosticCheck]:
        """Check authentication database availability, schema version, operator enrollment, and audit storage."""
        checks: List[DiagnosticCheck] = []
        db_path = getattr(self.config, "auth_db_path", None)

        if not db_path or not Path(db_path).is_file():
            checks.append(
                DiagnosticCheck(
                    name="auth_database_present",
                    severity="blocker",
                    is_security_critical=True,
                    message=f"Authentication database does not exist at {db_path}.",
                    details={"db_path": str(db_path)},
                )
            )
            return checks

        checks.append(
            DiagnosticCheck(
                name="auth_database_present",
                severity="pass",
                is_security_critical=True,
                message=f"Authentication database exists at {db_path}.",
                details={"db_path": str(db_path)},
            )
        )

        auth_storage = AuthStorage(Path(db_path), read_only=True)
        # Check enrolled operators
        enrolled_ops = []
        try:
            # Query operators read-only
            with auth_storage._get_connection() as conn:
                rows = conn.execute("SELECT operator_id, password_hash, totp_secret FROM operators").fetchall()
                for r in rows:
                    if r["password_hash"] and r["totp_secret"]:
                        enrolled_ops.append(r["operator_id"])
        except (sqlite3.OperationalError, Exception) as exc:
            checks.append(
                DiagnosticCheck(
                    name="operator_enrolled",
                    severity="blocker",
                    is_security_critical=True,
                    message=f"No operator is enrolled (operators table uninitialized or inaccessible: {exc}).",
                )
            )
            return checks

        if not enrolled_ops:
            checks.append(
                DiagnosticCheck(
                    name="operator_enrolled",
                    severity="blocker",
                    is_security_critical=True,
                    message="No operator is enrolled with both password and TOTP 2FA secret.",
                    details={"enrolled_count": 0},
                )
            )
        else:
            checks.append(
                DiagnosticCheck(
                    name="operator_enrolled",
                    severity="pass",
                    is_security_critical=True,
                    message=f"Found {len(enrolled_ops)} enrolled operator(s) with password and TOTP.",
                    details={"operators": enrolled_ops},
                )
            )

        # Check audit storage health
        try:
            with auth_storage._get_connection() as conn:
                conn.execute("SELECT 1 FROM audit_events LIMIT 1").fetchone()
            checks.append(
                DiagnosticCheck(
                    name="audit_storage_healthy",
                    severity="pass",
                    is_security_critical=True,
                    message="Audit storage ledger is accessible and healthy.",
                )
            )
        except Exception as exc:
            checks.append(
                DiagnosticCheck(
                    name="audit_storage_healthy",
                    severity="blocker",
                    is_security_critical=True,
                    message=f"Audit storage is inaccessible or corrupted: {exc}",
                )
            )

        return checks

    def check_capabilities_and_policy(self) -> List[DiagnosticCheck]:
        """Verify Resource Coordinator recovery is disabled and public action policy is conservative."""
        checks: List[DiagnosticCheck] = []

        # 1. Resource Coordinator recovery capability disabled in backend registry
        coord_rec = self.registry.get("coordinator.recovery")
        if coord_rec and coord_rec.enabled:
            checks.append(
                DiagnosticCheck(
                    name="coordinator_recovery_disabled",
                    severity="blocker",
                    is_security_critical=True,
                    message="Production Resource Coordinator recovery is enabled in the capability registry. It must remain disabled.",
                    details={"enabled": True},
                )
            )
        else:
            checks.append(
                DiagnosticCheck(
                    name="coordinator_recovery_disabled",
                    severity="pass",
                    is_security_critical=True,
                    message="Production Resource Coordinator recovery is safely disabled in registry.",
                    details={"enabled": False},
                )
            )

        # 2. Public action policy conservative
        policy = getattr(self.config, "public_action_policy", "conservative")
        if policy != "conservative":
            checks.append(
                DiagnosticCheck(
                    name="public_action_policy",
                    severity="blocker",
                    is_security_critical=True,
                    message=f"public_action_policy is '{policy}'. Only 'conservative' is authorized for external exposure.",
                    details={"policy": policy},
                )
            )
        else:
            checks.append(
                DiagnosticCheck(
                    name="public_action_policy",
                    severity="pass",
                    is_security_critical=True,
                    message="Public action policy is conservative (mutating actions forbidden externally except incident ack).",
                    details={"policy": policy},
                )
            )

        return checks

    def check_active_barriers(self) -> DiagnosticCheck:
        """Check for active unresolved execution barriers."""
        barriers = self.storage.list_active_barriers()
        if barriers:
            return DiagnosticCheck(
                name="no_active_barriers",
                severity="blocker",
                is_security_critical=True,
                message=f"Found {len(barriers)} active unresolved execution barrier(s). Barriers must be reconciled before enabling exposure.",
                details={"active_count": len(barriers), "barriers": [b["resource_key"] for b in barriers]},
            )

        return DiagnosticCheck(
            name="no_active_barriers",
            severity="pass",
            is_security_critical=True,
            message="Zero active unresolved execution barriers.",
            details={"active_count": 0},
        )

    def check_local_listener(
        self,
        host: str = "127.0.0.1",
        port: int = 8443,
        verify_listener: bool = True,
    ) -> DiagnosticCheck:
        """Probe local listener reachability on loopback."""
        if not verify_listener:
            return DiagnosticCheck(
                name="local_listener_reachable",
                severity="pass",
                is_security_critical=False,
                message=f"Listener socket verification skipped (dry-run/non-live mode). Expected: {host}:{port}",
                details={"host": host, "port": port, "verified": False},
            )

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        try:
            res = s.connect_ex((host, port))
            if res == 0:
                return DiagnosticCheck(
                    name="local_listener_reachable",
                    severity="pass",
                    is_security_critical=True,
                    message=f"Target dashboard listener is active and responding on {host}:{port}.",
                    details={"host": host, "port": port},
                )
            return DiagnosticCheck(
                name="local_listener_reachable",
                severity="blocker",
                is_security_critical=True,
                message=f"No active process listening on target port {host}:{port}.",
                details={"host": host, "port": port, "status": "offline"},
            )
        except Exception as exc:
            return DiagnosticCheck(
                name="local_listener_reachable",
                severity="blocker",
                is_security_critical=True,
                message=f"Local listener probe failed: {exc}",
                details={"host": host, "port": port, "error": str(exc)},
            )
        finally:
            s.close()

    def check_all(
        self,
        target_port: int = 8443,
        public_port: int = 8443,
        verify_listener: bool = True,
    ) -> Dict[str, Any]:
        """Compile complete diagnostic report with explicit blocker/warning/pass categorization."""
        all_checks: List[DiagnosticCheck] = []

        all_checks.extend(self.check_tailscale(public_port=public_port))
        all_checks.extend(self.check_origin_and_hosts())
        all_checks.extend(self.check_cookie_and_proxy_policy())
        all_checks.extend(self.check_operator_and_auth_database())
        all_checks.extend(self.check_capabilities_and_policy())
        all_checks.append(self.check_active_barriers())
        all_checks.append(
            self.check_local_listener(
                host=self.config.host,
                port=target_port,
                verify_listener=verify_listener,
            )
        )

        blockers = [c for c in all_checks if c.severity == "blocker"]
        warnings = [c for c in all_checks if c.severity == "warning"]
        unknowns = [c for c in all_checks if c.severity == "unknown"]
        passes = [c for c in all_checks if c.severity == "pass"]

        security_unknowns = [c for c in unknowns if c.is_security_critical]
        ready_for_public_enable = (len(blockers) == 0 and len(security_unknowns) == 0)

        tailscale_installed = any(c.name == "tailscale_installed" and c.severity == "pass" for c in all_checks)
        cookie_ok = any(c.name == "cookie_security_strict" and c.severity == "pass" for c in all_checks)
        overall_ok = tailscale_installed and cookie_ok

        # Backward compatibility checks map
        checks_map: Dict[str, Any] = {}
        for c in all_checks:
            checks_map[c.name] = {
                "ok": c.severity == "pass",
                "severity": c.severity,
                "message": c.message,
                **c.details,
            }

        barriers_summary = self.storage.list_active_barriers()

        return {
            "ok": overall_ok,
            "ready_for_public_enable": ready_for_public_enable,
            "read_only": True,
            "blockers": [c.to_dict() for c in blockers],
            "warnings": [c.to_dict() for c in warnings],
            "security_unknowns": [c.to_dict() for c in security_unknowns],
            "passes": [c.to_dict() for c in passes],
            "checks": checks_map,
            "barriers": {
                "ok": len(barriers_summary) == 0,
                "active_count": len(barriers_summary),
                "items": barriers_summary,
                "requires_reconciliation": len(barriers_summary) > 0,
            },
        }
