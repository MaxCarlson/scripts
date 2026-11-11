"""Tailscale CLI adapter and mock simulation runner for Funnel and Serve management."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)

SIMULATED_STATE_PATH = Path.home() / ".scripts" / "remote_control" / ".simulated_tailscale.json"


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

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


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
    ) -> None:
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
        self._ensure_state()

    def _ensure_state(self) -> Dict[str, Any]:
        if self.state_file.is_file():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

        initial = {
            "installed": self.default_installed,
            "version": "1.54.0-simulated",
            "logged_in": True,
            "node_name": self.default_node,
            "tailnet_name": self.default_tailnet,
            "funnel_available": self.default_available,
            "funnel_active": False,
            "public_url": None,
        }
        self._save_state(initial)
        return initial

    def _save_state(self, state: Dict[str, Any]) -> None:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
        except Exception as exc:
            logger.warning("Failed saving simulated tailscale state: %s", exc)

    def get_status(self) -> TailscaleStatus:
        st = self._ensure_state()
        return TailscaleStatus(
            installed=st.get("installed", False),
            version=st.get("version", "unknown"),
            logged_in=st.get("logged_in", False),
            node_name=st.get("node_name", ""),
            tailnet_name=st.get("tailnet_name", ""),
            funnel_available=st.get("funnel_available", False),
            funnel_active=st.get("funnel_active", False),
            public_url=st.get("public_url"),
        )

    def plan_funnel(self, port: int = 8443, public_port: int = 8443) -> List[str]:
        st = self.get_status()
        url = f"https://{st.node_name}.{st.tailnet_name}:{public_port}" if public_port != 443 else f"https://{st.node_name}.{st.tailnet_name}"
        return [
            f"tailscale serve --bg --https={public_port} http://127.0.0.1:{port}",
            f"tailscale funnel --bg {public_port} on",
            f"# Expected Public Ingress: {url}",
        ]

    def enable_funnel(self, port: int = 8443, public_port: int = 8443) -> Dict[str, Any]:
        st = self._ensure_state()
        url = f"https://{st['node_name']}.{st['tailnet_name']}:{public_port}" if public_port != 443 else f"https://{st['node_name']}.{st['tailnet_name']}"
        st["funnel_active"] = True
        st["public_url"] = url
        self._save_state(st)
        return {
            "ok": True,
            "applied": True,
            "public_url": url,
            "commands_executed": [
                f"tailscale serve --bg --https={public_port} http://127.0.0.1:{port}",
                f"tailscale funnel --bg {public_port} on",
            ],
        }

    def disable_funnel(self, public_port: int = 8443) -> Dict[str, Any]:
        st = self._ensure_state()
        st["funnel_active"] = False
        st["public_url"] = None
        self._save_state(st)
        return {
            "ok": True,
            "applied": True,
            "commands_executed": [
                f"tailscale funnel {public_port} off",
                f"tailscale serve --https={public_port} off",
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

    def _run_cmd(self, args: List[str], timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
        cmd = [self.bin] + args
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
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
            if proc_funnel.returncode == 0 and proc_funnel.stdout:
                try:
                    fdata = json.loads(proc_funnel.stdout)
                    funnel_active = bool(fdata.get("Web") or fdata.get("TCP"))
                    if funnel_active and dns_name:
                        public_url = f"https://{dns_name}:8443"
                except Exception:
                    pass

            return TailscaleStatus(
                installed=True,
                version=version,
                logged_in=True,
                node_name=node_name,
                tailnet_name=tailnet_name,
                funnel_available=True,
                funnel_active=funnel_active,
                public_url=public_url,
            )
        except Exception:
            return TailscaleStatus(installed=True, version=version, logged_in=True)

    def plan_funnel(self, port: int = 8443, public_port: int = 8443) -> List[str]:
        st = self.get_status()
        url = f"https://{st.node_name}.{st.tailnet_name}:{public_port}" if st.node_name and st.tailnet_name else f"https://<node>.<tailnet>.ts.net:{public_port}"
        return [
            f"{self.bin} serve --bg --https={public_port} http://127.0.0.1:{port}",
            f"{self.bin} funnel --bg {public_port} on",
            f"# Target Public Ingress: {url}",
        ]

    def enable_funnel(self, port: int = 8443, public_port: int = 8443) -> Dict[str, Any]:
        p1 = self._run_cmd(["serve", "--bg", f"--https={public_port}", f"http://127.0.0.1:{port}"])
        if p1.returncode != 0:
            return {"ok": False, "error": "serve_failed", "output": p1.stderr}

        p2 = self._run_cmd(["funnel", "--bg", str(public_port), "on"])
        if p2.returncode != 0:
            return {"ok": False, "error": "funnel_failed", "output": p2.stderr}

        st = self.get_status()
        return {
            "ok": True,
            "applied": True,
            "public_url": st.public_url,
            "commands_executed": [
                f"tailscale serve --bg --https={public_port} http://127.0.0.1:{port}",
                f"tailscale funnel --bg {public_port} on",
            ],
        }

    def disable_funnel(self, public_port: int = 8443) -> Dict[str, Any]:
        self._run_cmd(["funnel", str(public_port), "off"])
        self._run_cmd(["serve", f"--https={public_port}", "off"])
        return {
            "ok": True,
            "applied": True,
            "commands_executed": [
                f"tailscale funnel {public_port} off",
                f"tailscale serve --https={public_port} off",
            ],
        }


def get_tailscale_client(simulate: Optional[bool] = None) -> TailscaleClientProtocol:
    """Return appropriate Tailscale client (simulated or real)."""
    force_sim = os.environ.get("REMOTE_CONTROL_SIMULATE_TAILSCALE", "0") in ("1", "true", "True")
    if simulate is True or force_sim:
        return SimulatedTailscaleClient()

    found = shutil.which("tailscale")
    default_win = Path(r"C:\Program Files\Tailscale\tailscale.exe")
    if found or default_win.is_file():
        return RealTailscaleClient(found or str(default_win))

    # Fallback to simulation if not installed
    return SimulatedTailscaleClient(installed=False)
