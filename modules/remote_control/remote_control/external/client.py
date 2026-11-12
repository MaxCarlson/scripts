"""Tailscale CLI adapter and mock simulation runner for Funnel and Serve management.

Stage B Requirements:
- Modern direct Funnel command: tailscale funnel --bg --https=<public_port> http://127.0.0.1:<port>
- Direct loopback target, no simultaneous serve-then-funnel duplication.
- Port and target validation (public ports in 443, 8443, 10000; loopback target).
- Read-only inspection of existing exposure configuration.
- Rejection of conflicting configuration owned by another service.
- Strict capture of return codes and bounded stderr.
- Post-activation status verification.
- Post-disable verification that the public endpoint is no longer active.
- Partial-failure rollback with failure reporting if rollback itself fails.
- Disable operates independently of application preflight.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)

SIMULATED_STATE_PATH = Path.home() / ".scripts" / "remote_control" / ".simulated_tailscale.json"
SUPPORTED_FUNNEL_PORTS = {443, 8443, 10000}


def parse_endpoint_port(ep: str) -> Optional[int]:
    """Extract port integer from endpoint string like 'node.tailnet:8443', ':8443', or '8443'."""
    ep_str = str(ep).strip().rstrip("/")
    if ":" in ep_str:
        try:
            return int(ep_str.rsplit(":", 1)[-1])
        except ValueError:
            return None
    elif ep_str.isdigit():
        return int(ep_str)
    return None


def parse_endpoint_host(ep: str) -> str:
    """Extract hostname from endpoint string like 'node.tailnet:8443'."""
    ep_str = str(ep).strip()
    if ":" in ep_str:
        return ep_str.rsplit(":", 1)[0].strip()
    if ep_str.isdigit():
        return ""
    return ep_str


@dataclass
class TailscaleStatus:
    """Tailscale node and Funnel reachability status."""

    installed: bool = False
    version: str = "unknown"
    logged_in: bool = False
    node_name: str = ""
    tailnet_name: str = ""
    funnel_available: bool = False
    funnel_active: bool = False
    public_url: Optional[str] = None
    routes: Dict[str, Any] = field(default_factory=dict)
    allow_funnel: Dict[str, bool] = field(default_factory=dict)
    status_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def get_exact_route(self, public_port: int) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Find the route matching the exact public port."""
        for ep, details in self.routes.items():
            if parse_endpoint_port(ep) == public_port:
                if isinstance(details, dict):
                    return ep, details
                elif isinstance(details, str):
                    return ep, {"Handlers": {"/": {"Proxy": details}}}
        return None

    def is_route_funnel_active(
        self,
        public_port: int,
        expected_target: Optional[str] = None,
        expected_host: Optional[str] = None,
    ) -> bool:
        """Verify that an exact managed route is active with Funnel enabled."""
        found = self.get_exact_route(public_port)
        if not found:
            return False
        ep, details = found

        # Must be permitted in allow_funnel
        if not self.allow_funnel.get(ep, False) and not self.allow_funnel.get(str(public_port), False):
            return False

        if expected_host:
            ep_host = parse_endpoint_host(ep)
            if ep_host and ep_host != expected_host and not expected_host.startswith(ep_host):
                return False

        if expected_target:
            handlers = details.get("Handlers", {}) if isinstance(details, dict) else {}
            proxy = handlers.get("/", {}).get("Proxy", "")
            if proxy and proxy != expected_target:
                return False

        return True


class TailscaleClientProtocol(Protocol):
    """Protocol for Tailscale CLI interactions."""

    def get_status(self) -> TailscaleStatus: ...
    def plan_funnel(self, port: int, public_port: int) -> List[str]: ...
    def enable_funnel(self, port: int, public_port: int) -> Dict[str, Any]: ...
    def disable_funnel(self, public_port: int) -> Dict[str, Any]: ...


class SimulatedTailscaleClient:
    """In-memory and file-backed simulation for testing when Tailscale is not installed on host."""

    def __init__(
        self,
        installed: bool = True,
        node_name: str = "workstation",
        tailnet_name: str = "tailnet-dev.ts.net",
        funnel_available: bool = True,
        state_file: Optional[Path] = None,
        read_only: bool = False,
        version: str = "1.54.0-simulated",
        fail_on_enable: Optional[str] = None,
        fail_on_disable: Optional[str] = None,
        fail_post_verify: bool = False,
        fail_rollback: bool = False,
        existing_conflicts: Optional[Dict[str, str]] = None,
    ) -> None:
        self.read_only = read_only
        if state_file is None:
            env_state = os.environ.get("REMOTE_CONTROL_SIMULATED_STATE_PATH")
            if env_state:
                state_file = Path(env_state)
            else:
                state_file = SIMULATED_STATE_PATH
        self.state_file = state_file
        self.default_installed = installed
        self.default_node = node_name
        self.default_tailnet = tailnet_name
        self.default_available = funnel_available
        self.default_version = version
        self.fail_on_enable = fail_on_enable
        self.fail_on_disable = fail_on_disable
        self.fail_post_verify = fail_post_verify
        self.fail_rollback = fail_rollback
        self.existing_conflicts = existing_conflicts or {}
        self._ensure_state()

    def _ensure_state(self) -> Dict[str, Any]:
        if self.state_file.is_file():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "allow_funnel" not in data:
                        data["allow_funnel"] = {ep: True for ep in data.get("routes", {})}
                    return data
            except Exception:
                pass

        routes = dict(self.existing_conflicts)
        allow_funnel = {ep: True for ep in routes}
        initial = {
            "installed": self.default_installed,
            "version": self.default_version,
            "logged_in": True,
            "node_name": self.default_node,
            "tailnet_name": self.default_tailnet,
            "funnel_available": self.default_available,
            "funnel_active": len(routes) > 0,
            "public_url": None,
            "routes": routes,
            "allow_funnel": allow_funnel,
        }
        if not self.read_only:
            self._save_state(initial)
        return initial

    def _save_state(self, state: Dict[str, Any]) -> None:
        if self.read_only:
            return
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
        except Exception as exc:
            logger.warning("Failed saving simulated tailscale state: %s", exc)

    def get_status(self) -> TailscaleStatus:
        st = self._ensure_state()
        routes = st.get("routes", {})
        allow_funnel = st.get("allow_funnel", {})
        active = any(allow_funnel.get(ep, False) for ep in routes) or st.get("funnel_active", False)
        return TailscaleStatus(
            installed=st.get("installed", False),
            version=st.get("version", "unknown"),
            logged_in=st.get("logged_in", False),
            node_name=st.get("node_name", ""),
            tailnet_name=st.get("tailnet_name", ""),
            funnel_available=st.get("funnel_available", False),
            funnel_active=active,
            public_url=st.get("public_url"),
            routes=routes,
            allow_funnel=allow_funnel,
        )

    def plan_funnel(self, port: int = 8443, public_port: int = 8443) -> List[str]:
        st = self.get_status()
        url = (
            f"https://{st.node_name}.{st.tailnet_name}:{public_port}"
            if public_port != 443
            else f"https://{st.node_name}.{st.tailnet_name}"
        )
        return [
            f"tailscale funnel --bg --https={public_port} http://127.0.0.1:{port}",
            f"# Expected Public Ingress: {url}",
        ]

    def enable_funnel(self, port: int = 8443, public_port: int = 8443) -> Dict[str, Any]:
        # Validate port
        if public_port not in SUPPORTED_FUNNEL_PORTS:
            return {
                "ok": False,
                "applied": False,
                "error": "unsupported_public_port",
                "message": f"Port {public_port} is not in supported Funnel ports {sorted(SUPPORTED_FUNNEL_PORTS)}.",
            }

        st = self._ensure_state()
        routes = st.setdefault("routes", {})
        allow_funnel = st.setdefault("allow_funnel", {})

        # Conflict detection using exact port extraction
        target_uri = f"http://127.0.0.1:{port}"
        for ep, details in routes.items():
            if parse_endpoint_port(ep) == public_port:
                existing_proxy = details if isinstance(details, str) else details.get("Handlers", {}).get("/", {}).get("Proxy", "")
                if existing_proxy and existing_proxy != target_uri:
                    return {
                        "ok": False,
                        "applied": False,
                        "error": "port_conflict",
                        "message": f"Port {public_port} is already configured for another service: {existing_proxy}",
                    }

        if self.fail_on_enable:
            return {
                "ok": False,
                "applied": False,
                "error": self.fail_on_enable,
                "message": f"Simulated enable failure: {self.fail_on_enable}",
            }

        url = (
            f"https://{st['node_name']}.{st['tailnet_name']}:{public_port}"
            if public_port != 443
            else f"https://{st['node_name']}.{st['tailnet_name']}"
        )
        ep_key = f"{st['node_name']}.{st['tailnet_name']}:{public_port}"
        routes[ep_key] = {"Handlers": {"/": {"Proxy": target_uri}}}
        allow_funnel[ep_key] = True
        st["funnel_active"] = True
        st["public_url"] = url
        self._save_state(st)

        # Post-activation verification simulation
        if self.fail_post_verify:
            # Trigger rollback
            if self.fail_rollback:
                return {
                    "ok": False,
                    "applied": False,
                    "error": "post_activation_verification_failed",
                    "rolled_back": False,
                    "rollback_error": "rollback_command_failed",
                    "message": "Activation verification failed and rollback could not be completed.",
                }
            routes.pop(ep_key, None)
            allow_funnel.pop(ep_key, None)
            st["funnel_active"] = any(allow_funnel.values())
            st["public_url"] = None
            self._save_state(st)
            return {
                "ok": False,
                "applied": False,
                "error": "post_activation_verification_failed",
                "rolled_back": True,
                "message": "Endpoint was not reachable after activation; rolled back safely.",
            }

        return {
            "ok": True,
            "applied": True,
            "public_url": url,
            "commands_executed": [
                f"tailscale funnel --bg --https={public_port} http://127.0.0.1:{port}",
            ],
        }

    def disable_funnel(self, public_port: int = 8443) -> Dict[str, Any]:
        if self.fail_on_disable:
            return {
                "ok": False,
                "applied": False,
                "error": self.fail_on_disable,
                "message": f"Simulated disable failure: {self.fail_on_disable}",
            }

        st = self._ensure_state()
        routes = st.setdefault("routes", {})
        allow_funnel = st.setdefault("allow_funnel", {})
        for ep in list(routes.keys()):
            if parse_endpoint_port(ep) == public_port:
                routes.pop(ep, None)
                allow_funnel.pop(ep, None)
        st["funnel_active"] = any(allow_funnel.values())
        if not st["funnel_active"]:
            st["public_url"] = None
        self._save_state(st)
        return {
            "ok": True,
            "applied": True,
            "commands_executed": [
                f"tailscale funnel --https={public_port} off",
            ],
        }
        return {
            "ok": True,
            "applied": True,
            "commands_executed": [
                f"tailscale funnel --https={public_port} off",
            ],
        }


class RealTailscaleClient:
    """Wrapper executing real tailscale.exe CLI commands on Windows host."""

    def __init__(self, executable_path: Optional[str] = None) -> None:
        self.bin = executable_path or self._find_tailscale()

    @staticmethod
    def _find_tailscale() -> str:
        found = shutil.which("tailscale")
        if found:
            return found
        default_win = Path(r"C:\Program Files\Tailscale\tailscale.exe")
        if default_win.is_file():
            return str(default_win)
        return "tailscale"

    def _run_cmd(self, args: List[str], timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
        cmd = [self.bin] + args
        try:
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=-1,
                stdout="",
                stderr=f"Command '{' '.join(args)}' timed out after {timeout}s",
            )
        except Exception as exc:
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=-1,
                stdout="",
                stderr=str(exc),
            )

    def get_status(self) -> TailscaleStatus:
        if not shutil.which(self.bin) and not Path(self.bin).is_file():
            return TailscaleStatus(installed=False)

        proc_ver = self._run_cmd(["version"])
        version = proc_ver.stdout.splitlines()[0].strip() if proc_ver.returncode == 0 and proc_ver.stdout else "unknown"

        proc_stat = self._run_cmd(["status", "--json"])
        if proc_stat.returncode != 0:
            return TailscaleStatus(installed=True, version=version, logged_in=False)

        try:
            data = json.loads(proc_stat.stdout)
            self_node = data.get("Self", {})
            dns_name = self_node.get("DNSName", "").rstrip(".")
            parts = dns_name.split(".", 1)
            node_name = parts[0] if parts else ""
            tailnet_name = parts[1] if len(parts) > 1 else ""

            # Check funnel status
            proc_funnel = self._run_cmd(["funnel", "status", "--json"])
            funnel_active = False
            public_url = None
            routes: Dict[str, Any] = {}
            allow_funnel: Dict[str, bool] = {}
            status_error: Optional[str] = None

            if proc_funnel.returncode == 0 and proc_funnel.stdout:
                try:
                    fdata = json.loads(proc_funnel.stdout)
                    web = fdata.get("Web", {})
                    tcp = fdata.get("TCP", {})
                    allow_raw = fdata.get("AllowFunnel", {})
                    for k, v in allow_raw.items():
                        allow_funnel[k] = bool(v)

                    # Extract active routes
                    for host_port, details in web.items():
                        routes[host_port] = details
                        if allow_funnel.get(host_port, False):
                            funnel_active = True

                    for host_port, details in tcp.items():
                        routes[host_port] = details
                        if allow_funnel.get(host_port, False):
                            funnel_active = True

                    if funnel_active and dns_name:
                        public_url = f"https://{dns_name}:8443"
                except json.JSONDecodeError as exc:
                    logger.warning("Tailscale funnel status returned malformed JSON: %s", exc)
                    status_error = f"malformed_json: {exc}"
                except Exception as exc:
                    logger.warning("Error parsing Tailscale funnel status: %s", exc)
                    status_error = f"parse_error: {exc}"
            elif proc_funnel.returncode != 0:
                status_error = f"status_command_failed: {proc_funnel.stderr[:256]}"

            return TailscaleStatus(
                installed=True,
                version=version,
                logged_in=True,
                node_name=node_name,
                tailnet_name=tailnet_name,
                funnel_available=True,
                funnel_active=funnel_active,
                public_url=public_url,
                routes=routes,
                allow_funnel=allow_funnel,
                status_error=status_error,
            )
        except Exception:
            return TailscaleStatus(installed=True, version=version, logged_in=True)

    def plan_funnel(self, port: int = 8443, public_port: int = 8443) -> List[str]:
        st = self.get_status()
        url = (
            f"https://{st.node_name}.{st.tailnet_name}:{public_port}"
            if st.node_name and st.tailnet_name
            else f"https://<node>.<tailnet>.ts.net:{public_port}"
        )
        return [
            f"{self.bin} funnel --bg --https={public_port} http://127.0.0.1:{port}",
            f"# Target Public Ingress: {url}",
        ]

    def enable_funnel(self, port: int = 8443, public_port: int = 8443) -> Dict[str, Any]:
        """Enable Funnel exposure using modern direct command syntax with conflict check and rollback."""
        # 1. Target & Port Validation
        if public_port not in SUPPORTED_FUNNEL_PORTS:
            return {
                "ok": False,
                "applied": False,
                "error": "unsupported_public_port",
                "message": f"Public port {public_port} is not supported by Funnel {sorted(SUPPORTED_FUNNEL_PORTS)}.",
            }

        # 2. Read-only inspection of existing exposure configuration
        current_st = self.get_status()
        target_uri = f"http://127.0.0.1:{port}"
        for ep, details in current_st.routes.items():
            if parse_endpoint_port(ep) == public_port:
                # Check handler target
                handlers = details.get("Handlers", {}) if isinstance(details, dict) else {}
                root_proxy = handlers.get("/", {}).get("Proxy", "")
                if root_proxy and root_proxy != target_uri:
                    return {
                        "ok": False,
                        "applied": False,
                        "error": "port_conflict",
                        "message": f"Port {public_port} is already owned by another service ({root_proxy}).",
                    }

        # 3. Modern direct funnel command execution
        cmd_args = ["funnel", "--bg", f"--https={public_port}", f"http://127.0.0.1:{port}"]
        p = self._run_cmd(cmd_args)
        if p.returncode != 0:
            stderr_bounded = p.stderr[:2048] if p.stderr else "Unknown error"
            return {
                "ok": False,
                "applied": False,
                "error": "funnel_enable_failed",
                "output": stderr_bounded,
                "commands_executed": [f"{self.bin} {' '.join(cmd_args)}"],
            }

        # 4. Post-activation status verification for exact managed Funnel route
        post_st = self.get_status()
        if not post_st.is_route_funnel_active(public_port, expected_target=target_uri):
            # Activation verification failed: trigger rollback
            logger.error("Post-activation verification failed for exact route on port %d. Rolling back...", public_port)
            rollback_res = self.disable_funnel(public_port)
            return {
                "ok": False,
                "applied": False,
                "error": "post_activation_verification_failed",
                "rolled_back": rollback_res.get("ok", False),
                "rollback_output": rollback_res.get("output"),
                "message": "Funnel command exited 0 but exact managed route is not active in Funnel mode. Rolled back.",
            }

        return {
            "ok": True,
            "applied": True,
            "public_url": post_st.public_url,
            "commands_executed": [
                f"{self.bin} {' '.join(cmd_args)}",
            ],
        }

    def disable_funnel(self, public_port: int = 8443) -> Dict[str, Any]:
        """Disable Funnel exposure with captured returncode and post-disable verification."""
        executed: List[str] = []
        # Attempt modern flag syntax
        cmd1 = ["funnel", f"--https={public_port}", "off"]
        p1 = self._run_cmd(cmd1)
        executed.append(f"{self.bin} {' '.join(cmd1)}")

        if p1.returncode != 0:
            # Fallback to positional argument syntax
            cmd2 = ["funnel", str(public_port), "off"]
            p2 = self._run_cmd(cmd2)
            executed.append(f"{self.bin} {' '.join(cmd2)}")
            if p2.returncode != 0:
                stderr_bounded = (p2.stderr or p1.stderr or "Unknown disable error")[:2048]
                return {
                    "ok": False,
                    "applied": False,
                    "error": "funnel_disable_failed",
                    "output": stderr_bounded,
                    "commands_executed": executed,
                }

        # Post-disable status verification for exact managed route
        post_st = self.get_status()
        if post_st.is_route_funnel_active(public_port):
            return {
                "ok": False,
                "applied": False,
                "error": "post_disable_verification_failed",
                "message": f"Port {public_port} remains active in Funnel mode after disable command.",
                "commands_executed": executed,
            }

        return {
            "ok": True,
            "applied": True,
            "commands_executed": executed,
        }


def get_tailscale_client(simulate: Optional[bool] = None, read_only: bool = False) -> TailscaleClientProtocol:
    """Return appropriate Tailscale client (simulated or real)."""
    force_sim = os.environ.get("REMOTE_CONTROL_SIMULATE_TAILSCALE", "0") in ("1", "true", "True")
    if simulate is True or force_sim:
        return SimulatedTailscaleClient(read_only=read_only)

    found = shutil.which("tailscale")
    default_win = Path(r"C:\Program Files\Tailscale\tailscale.exe")
    if found or default_win.is_file():
        return RealTailscaleClient(found or str(default_win))

    # Fallback to simulation if not installed
    return SimulatedTailscaleClient(installed=False, read_only=read_only)
