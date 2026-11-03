"""Non-inference Harbor 0.25.0 container probe for the SV study egress policy."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import shlex
import subprocess
import tempfile
from typing import Any
from uuid import uuid4
from urllib.parse import urlsplit

from .study_network_policy import NETWORK_POLICY, NETWORK_POLICY_ID

HARBOR_VERSION = "0.25.0"
DEFAULT_MONITOR_URL = "http://host.docker.internal:8788/v1/chat/completions"
DEFAULT_IMAGE = "node:20"


def _probe_command(monitor_url: str) -> str:
    script = r"""
const dns = require("node:dns").promises;
const Resolver = require("node:dns").Resolver;
const net = require("node:net");
const tls = require("node:tls");
const fs = require("node:fs");
const monitorUrl = __MONITOR_URL__;
function tcp(host, port) {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host, port });
    const timer = setTimeout(() => socket.destroy(new Error("timeout")), 3500);
    socket.once("connect", () => { clearTimeout(timer); socket.destroy(); resolve({ connected: true }); });
    socket.once("error", (error) => { clearTimeout(timer); resolve({ connected: false, error: error.code || error.name }); });
  });
}
function tlsConnect(host, port, servername) {
  return new Promise((resolve) => {
    const socket = tls.connect({ host, port, servername, rejectUnauthorized: false });
    const timer = setTimeout(() => socket.destroy(new Error("timeout")), 4500);
    socket.once("secureConnect", () => { clearTimeout(timer); socket.destroy(); resolve({ connected: true }); });
    socket.once("error", (error) => { clearTimeout(timer); resolve({ connected: false, error: error.code || error.name }); });
  });
}
async function main() {
  let monitor;
  try {
    const response = await fetch(monitorUrl, {
      method: "OPTIONS", signal: AbortSignal.timeout(4500), redirect: "manual"
    });
    monitor = { reachable: response.status === 405, status: response.status, method: "OPTIONS" };
    if (response.body) await response.body.cancel();
  } catch (error) {
    monitor = { reachable: false, status: null, error: error.cause?.code || error.name };
  }
  let dnsResult;
  try { dnsResult = { resolved: true, addresses: (await dns.lookup("example.com", { all: true })).length }; }
  catch (error) { dnsResult = { resolved: false, error: error.code || error.name }; }
  let directDns;
  try {
    const resolver = new Resolver();
    resolver.setServers(["1.1.1.1"]);
    directDns = { resolved: true, answers: (await new Promise((resolve, reject) =>
      resolver.resolve4("example.com", (error, addresses) => error ? reject(error) : resolve(addresses)))).length };
  } catch (error) { directDns = { resolved: false, error: error.code || error.name }; }
  const proxyNames = Object.keys(process.env).filter((name) => /(^|_)https?_proxy$|^all_proxy$|^no_proxy$/i.test(name));
  const routes = fs.existsSync("/proc/net/route") ? fs.readFileSync("/proc/net/route", "utf8").trim().split("\n").slice(1) : [];
  process.stdout.write(JSON.stringify({
    local_monitor_gateway_route: monitor,
    local_resolver_external_name_lookup: dnsResult,
    external_dns_direct: directDns,
    external_https_unlisted_sni: await tlsConnect("example.com", 443, "example.com"),
    external_https_direct_ip_no_sni: await tlsConnect("1.1.1.1", 443, undefined),
    proxy_environment_names: proxyNames,
    default_route_count: routes.filter((line) => line.split(/\s+/)[1] === "00000000").length
  }));
}
main().catch((error) => { process.stderr.write(String(error)); process.exitCode = 2; });
"""
    return "node -e " + shlex.quote(script.replace("__MONITOR_URL__", json.dumps(monitor_url)))


def _result_fields(result: Any) -> tuple[int, str, str]:
    return (
        int(getattr(result, "return_code", getattr(result, "returncode", 1))),
        str(getattr(result, "stdout", "")),
        str(getattr(result, "stderr", "") or ""),
    )


def _probe_gates(observed: dict[str, Any], effective_agent: dict[str, Any]) -> dict[str, str]:
    """Evaluate required isolation probes without treating DNS resolution as egress success."""
    results = {
        "policy": effective_agent == {
            "network_mode": "allowlist", "allowed_hosts": ["host.docker.internal"]
        },
        "local_monitor_gateway_route": observed.get("local_monitor_gateway_route", {}).get("reachable") is True,
        "external_dns_direct_denied": observed.get("external_dns_direct", {}).get("resolved") is False,
        "external_dns_name_lookup_denied": observed.get("local_resolver_external_name_lookup", {}).get(
            "resolved"
        ) is False,
        "external_https_unlisted_sni_denied": observed.get("external_https_unlisted_sni", {}).get(
            "connected"
        ) is False,
        "external_https_direct_ip_no_sni_denied": observed.get(
            "external_https_direct_ip_no_sni", {}
        ).get("connected") is False,
        "no_outbound_proxy_environment": observed.get("proxy_environment_names") == [],
    }
    return {name: "PASS" if passed else "FAIL" for name, passed in results.items()}


def _egress_control_blocker(enabled: bool) -> str | None:
    if enabled:
        return None
    return "Harbor egress-control sidecar is not enabled; no probe container started"


async def _qualify(*, monitor_url: str, image: str) -> dict[str, Any]:
    try:
        actual_version = importlib.metadata.version("harbor")
    except importlib.metadata.PackageNotFoundError:
        actual_version = None
    if actual_version != HARBOR_VERSION:
        raise RuntimeError(f"Harbor {HARBOR_VERSION} is required; found {actual_version!r}")
    parsed_monitor_url = urlsplit(monitor_url)
    if (parsed_monitor_url.scheme != "http" or parsed_monitor_url.hostname != "host.docker.internal"
            or parsed_monitor_url.username or parsed_monitor_url.password or parsed_monitor_url.query
            or parsed_monitor_url.fragment):
        raise ValueError("monitor probe URL must use the allowlisted host.docker.internal hostname")
    image_check = subprocess.run(
        ["docker", "image", "inspect", image], capture_output=True, text=True, timeout=10, check=False
    )
    if image_check.returncode:
        raise RuntimeError(f"synthetic probe image is not cached; refusing to pull {image!r}")

    from harbor.environments.docker.docker import DockerEnvironment
    from harbor.models.task.config import EnvironmentConfig, NetworkPolicy, TaskConfig, TaskOS
    from harbor.models.trial.paths import TrialPaths

    probe_id = uuid4().hex[:12]
    temporary_root = Path(__file__).resolve().parent.parent / ".pytest_tmp_root"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"sv-network-{probe_id}-", dir=temporary_root) as temporary:
        root = Path(temporary)
        task_dir = root / "synthetic-task"
        environment_dir = task_dir / "environment"
        trial_dir = root / "trial"
        environment_dir.mkdir(parents=True)
        trial_dir.mkdir()
        (task_dir / "task.toml").write_text(
            '[environment]\nnetwork_mode = "public"\n'
            '[agent]\nnetwork_mode = "allowlist"\nallowed_hosts = ["host.docker.internal"]\n'
            '[verifier]\nnetwork_mode = "no-network"\n',
            encoding="utf-8",
        )
        task_text = (task_dir / "task.toml").read_text(encoding="utf-8")
        task_config = TaskConfig.model_validate_toml(task_text)
        config = EnvironmentConfig(
            docker_image=image, os=TaskOS.LINUX, workdir="/tmp",
            network_mode=task_config.environment.network_mode,
        )
        baseline = NetworkPolicy(network_mode=task_config.environment.network_mode)
        agent_policy = NetworkPolicy(
            network_mode=task_config.agent.network_mode,
            allowed_hosts=task_config.agent.allowed_hosts or [],
        )
        verifier_policy = NetworkPolicy(network_mode=task_config.verifier.network_mode)
        environment = DockerEnvironment(
            environment_dir=environment_dir,
            environment_name=f"svnet-{probe_id}",
            session_id=f"svnet-{probe_id}__agent",
            trial_paths=TrialPaths(trial_dir=trial_dir),
            task_env_config=config,
            network_policy=baseline,
            phase_network_policies=[agent_policy, verifier_policy],
            enable_environment_dir_upload=False,
        )
        report: dict[str, Any] = {
            "schema": "sv-harbor-network-qualification-v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "inference": "never",
            "benchmark_tasks": "never",
            "harbor_version": actual_version,
            "docker_image": image,
            "policy_id": NETWORK_POLICY_ID,
            "network_policy": NETWORK_POLICY,
            "harbor_task_config_network_policy": {
                "environment": {"network_mode": task_config.environment.network_mode.value},
                "agent": {"network_mode": task_config.agent.network_mode.value,
                          "allowed_hosts": list(task_config.agent.allowed_hosts or [])},
                "verifier": {"network_mode": task_config.verifier.network_mode.value},
            },
            "container_created": False,
            "container_cleanup": "not_required",
            "egress_sidecar_enabled": bool(environment._enable_egress_control),
            "probes": {},
        }
        sidecar_blocker = _egress_control_blocker(environment._enable_egress_control)
        if sidecar_blocker:
            report["status"] = "FAIL"
            report["blocker"] = sidecar_blocker
            return report
        try:
            await environment.start(force_build=False)
            report["container_created"] = True
            await environment.set_network_policy(agent_policy)
            report["effective_agent_policy"] = {
                "network_mode": environment.network_policy.network_mode.value,
                "allowed_hosts": list(environment.network_policy.allowed_hosts),
            }
            command = _probe_command(monitor_url)
            result = await environment.exec(command, timeout_sec=15)
            code, stdout, stderr = _result_fields(result)
            report["probes"]["agent_phase_exit_code"] = code
            if code != 0:
                report["probes"]["agent_phase_stdout"] = stdout[-4000:]
                report["probes"]["agent_phase_stderr"] = stderr[-2000:]
                report["status"] = "FAIL"
            else:
                try:
                    observed = json.loads(stdout)
                except json.JSONDecodeError as error:
                    raise RuntimeError("synthetic container returned malformed probe JSON") from error
                report["probes"].update(observed)
                effective = report["effective_agent_policy"]
                report["gates"] = _probe_gates(observed, effective)
                report["status"] = "PASS" if all(value == "PASS" for value in report["gates"].values()) else "FAIL"
                await environment.set_network_policy(verifier_policy)
                verifier_probe = await environment.exec(
                    "node -e " + shlex.quote(
                        "fetch(" + json.dumps(monitor_url) + ", {signal: AbortSignal.timeout(2500)})"
                        ".then(() => process.exit(1)).catch(() => process.exit(0))"
                    ),
                    timeout_sec=5,
                )
                verifier_code, _, verifier_stderr = _result_fields(verifier_probe)
                report["probes"]["verifier_no_network_exit_code"] = verifier_code
                report["gates"]["verifier_no_network_denies_monitor"] = "PASS" if verifier_code == 0 else "FAIL"
                if verifier_code != 0:
                    report["status"] = "FAIL"
                if verifier_stderr:
                    report["probes"]["verifier_no_network_stderr"] = verifier_stderr[-1000:]
        except Exception as error:
            report["status"] = "FAIL"
            report["blocker"] = f"{type(error).__name__}: {error}"
        finally:
            try:
                await environment.stop(delete=True)
                report["container_cleanup"] = "PASS"
            except Exception as error:
                report["container_cleanup"] = f"FAIL: {type(error).__name__}: {error}"
                report["status"] = "FAIL"
        return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-x", "--execute", action="store_true", help="create and clean up one synthetic Harbor container")
    parser.add_argument("-m", "--monitor-url", default=DEFAULT_MONITOR_URL)
    parser.add_argument("-i", "--image", default=DEFAULT_IMAGE, help="must already be cached locally")
    parser.add_argument("-o", "--output", type=Path, help="write machine-readable JSON evidence to this path")
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({
            "status": "UNKNOWN",
            "execution_required": True,
            "harbor_version_required": HARBOR_VERSION,
            "monitor_url": args.monitor_url,
            "docker_image": args.image,
            "policy_id": NETWORK_POLICY_ID,
            "network_policy": NETWORK_POLICY,
            "inference": "never",
            "benchmark_tasks": "never",
        }, indent=2, sort_keys=True))
        return 0
    try:
        result = asyncio.run(_qualify(monitor_url=args.monitor_url, image=args.image))
    except Exception as error:
        result = {"schema": "sv-harbor-network-qualification-v1", "status": "FAIL",
                  "blocker": f"{type(error).__name__}: {error}", "inference": "never"}
    serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
