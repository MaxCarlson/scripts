"""
Command-line interface for Resource Coordinator.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import logging
import os
import sys
import time
from typing import List, Optional

import httpx
import uvicorn

from resource_coordinator import __version__
from resource_coordinator.config import build_system, load_config

logger = logging.getLogger("resource_coordinator")


def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="resource-coordinator",
        description="General-purpose resource coordination framework and LM Studio proxy gateway.",
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # serve
    serve_parser = subparsers.add_parser("serve", help="Run the coordination reverse proxy service.")
    serve_parser.add_argument(
        "-l",
        "--listen",
        default=None,
        help="Host:port to bind the gateway (default: 127.0.0.1:1235).",
    )
    serve_parser.add_argument(
        "-u",
        "--upstream",
        default=None,
        help="Upstream LM Studio URL (default: http://127.0.0.1:1234).",
    )
    serve_parser.add_argument("-c", "--config", default=None, help="Path to policy configuration YAML.")
    serve_parser.add_argument(
        "-f",
        "--fake-miner",
        action="store_true",
        help="Use in-memory fake miner backend instead of real process.",
    )

    # status
    status_parser = subparsers.add_parser("status", help="Query coordinator service status.")
    status_parser.add_argument(
        "-u",
        "--url",
        default="http://127.0.0.1:1235",
        help="Coordinator gateway URL (default: http://127.0.0.1:1235).",
    )
    status_parser.add_argument("-j", "--json", action="store_true", help="Output status in JSON format.")

    # recover
    recover_parser = subparsers.add_parser("recover", help="Clear restart inhibition on coordinator.")
    recover_parser.add_argument(
        "-u",
        "--url",
        default="http://127.0.0.1:1235",
        help="Coordinator gateway URL (default: http://127.0.0.1:1235).",
    )
    recover_parser.add_argument(
        "-r",
        "--resource",
        default="gpu.inference",
        help="Resource name to clear inhibition for (default: gpu.inference).",
    )

    recover_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Explicitly override unverifiable upstream state.",
    )
    recover_parser.add_argument("-n", "--reason", required=True, help="Operator evidence/reason for recovery.")

    # config
    config_parser = subparsers.add_parser("config", help="Inspect or validate configuration.")
    config_sub = config_parser.add_subparsers(dest="config_command", required=True)
    show_parser = config_sub.add_parser("show", help="Show active configuration.")
    show_parser.add_argument("-c", "--config", default=None, help="Path to configuration YAML.")
    show_parser.add_argument("-j", "--json", action="store_true", help="Output in JSON format.")

    validate_parser = config_sub.add_parser("validate", help="Validate a configuration file.")
    validate_parser.add_argument("-c", "--config", required=True, help="Path to configuration YAML.")

    # miner
    miner_parser = subparsers.add_parser("miner", help="Manage miner workload and overrides.")
    miner_sub = miner_parser.add_subparsers(dest="miner_command", required=True)
    m_status = miner_sub.add_parser("status", help="Get current miner process status.")
    m_status.add_argument("-c", "--config", default=None, help="Path to configuration YAML.")
    m_status.add_argument("-j", "--json", action="store_true", help="Output in JSON format.")

    m_pause = miner_sub.add_parser("pause", help="Pause mining process and set manual override.")
    m_pause.add_argument("-c", "--config", default=None, help="Path to configuration YAML.")
    m_pause.add_argument("-t", "--timeout", type=float, default=10.0, help="Stop timeout in seconds.")

    m_resume = miner_sub.add_parser("resume", help="Clear manual override and resume mining.")
    m_resume.add_argument("-c", "--config", default=None, help="Path to configuration YAML.")

    # diagnose
    diag_parser = subparsers.add_parser(
        "diagnose",
        help="Run read-only preflight diagnostic checks on hardware and coordinator.",
    )
    diag_parser.add_argument("-c", "--config", default=None, help="Path to configuration YAML.")
    diag_parser.add_argument(
        "-u",
        "--url",
        default="http://127.0.0.1:1235",
        help="Coordinator URL (default: http://127.0.0.1:1235).",
    )
    diag_parser.add_argument("-j", "--json", action="store_true", help="Output diagnostics in JSON format.")

    return parser.parse_args(args)


def cmd_serve(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.listen:
        parts = args.listen.split(":")
        config.service.listen_host = parts[0]
        config.service.listen_port = int(parts[1]) if len(parts) > 1 else 1235
    if args.upstream:
        config.service.upstream_url = args.upstream

    system = build_system(config, use_fake_processes=args.fake_miner)
    app = system.gateway.create_app()

    print(f"Starting Resource Coordinator Gateway v{__version__}")
    print(f"Listening on:  http://{config.service.listen_host}:{config.service.listen_port}")
    print(f"Upstream host: {config.service.upstream_url}")
    print(f"Managed procs: {list(system.supervisors.keys())}")
    print("Press Ctrl+C to terminate.")

    uvicorn.run(
        app,
        host=config.service.listen_host,
        port=config.service.listen_port,
        log_level="info" if args.verbose else "warning",
    )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    url = f"{args.url.rstrip('/')}/_coordinator/status"
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                if args.json:
                    print(json.dumps(data, indent=2))
                else:
                    print(f"Coordinator Status: {data.get('status')}")
                    print(f"Upstream URL:       {data.get('upstream_url')}")
                    gpu_data = data.get("gpu_inference", {})
                    print(f"Active inferences:  {gpu_data.get('active_count')}")
                    print(f"Pending requests:   {gpu_data.get('pending_count')}")
                    print(f"Cooling down:       {gpu_data.get('is_cooling_down')}")
                    if gpu_data.get("is_cooling_down"):
                        print(f"Cooldown remaining: {gpu_data.get('cooldown_remaining')}s")
                    inhibited = gpu_data.get("is_restart_inhibited", False)
                    print(f"Restart inhibited:  {inhibited}")
                    if inhibited and gpu_data.get("inhibition"):
                        inh = gpu_data["inhibition"]
                        print(f"  Reason:           {inh.get('reason')}")
                        print(f"  Holder ID:        {inh.get('holder_id')}")
                return 0
            else:
                print(
                    f"Error querying coordinator ({resp.status_code}): {resp.text}",
                    file=sys.stderr,
                )
                return 1
    except Exception as exc:
        print(f"Failed to connect to coordinator at {args.url}: {exc}", file=sys.stderr)
        return 1


def cmd_config(args: argparse.Namespace) -> int:
    if args.config_command == "show":
        config = load_config(args.config)
        data = {
            "version": config.version,
            "service": config.service.__dict__,
            "resources": config.resources,
            "processes": {k: v.__dict__ for k, v in config.processes.items()},
            "policies": [p.__dict__ for p in config.policies],
        }
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            print(f"Version:   {config.version}")
            print(f"Listen:    {config.service.listen_host}:{config.service.listen_port}")
            print(f"Upstream:  {config.service.upstream_url}")
            print(f"Processes: {list(config.processes.keys())}")
            print(f"Policies:  {[p.name for p in config.policies]}")
        return 0

    elif args.config_command == "validate":
        try:
            load_config(args.config)
            print("Configuration is valid.")
            return 0
        except Exception as exc:
            print(f"Configuration validation failed: {exc}", file=sys.stderr)
            return 1
    return 0


async def _async_miner_status(config_path: Optional[str], as_json: bool) -> int:
    config = load_config(config_path)
    system = build_system(config)
    if not system.miner_adapter:
        print("No miner process configured.", file=sys.stderr)
        return 1
    st = await system.miner_adapter.status()
    override = system.miner_adapter.is_manual_override
    data = {**st.to_dict(), "manual_override": override}
    if as_json:
        print(json.dumps(data, indent=2))
    else:
        print(f"Miner Name:       {st.name}")
        print(f"State:            {st.state.value}")
        print(f"PID:              {st.pid}")
        print(f"Coordinator owned:{st.is_coordinator_owned}")
        print(f"Manual override:  {override}")
    return 0


async def _async_miner_pause(config_path: Optional[str], timeout: float) -> int:
    print(
        "Standalone miner mutation is disabled: it cannot access the running coordinator's leases or overrides.",
        file=sys.stderr,
    )
    return 1


async def _async_miner_resume(config_path: Optional[str]) -> int:
    print(
        "Standalone miner mutation is disabled: it cannot access the running coordinator's leases or overrides.",
        file=sys.stderr,
    )
    return 1


def cmd_miner(args: argparse.Namespace) -> int:
    if args.miner_command == "status":
        return asyncio.run(_async_miner_status(args.config, args.json))
    elif args.miner_command == "pause":
        return asyncio.run(_async_miner_pause(args.config, args.timeout))
    elif args.miner_command == "resume":
        return asyncio.run(_async_miner_resume(args.config))
    return 0


def cmd_recover(args: argparse.Namespace) -> int:
    token = os.environ.get("RESOURCE_COORDINATOR_RECOVERY_TOKEN")
    if not args.force or not token:
        print(
            "Recovery requires --force and RESOURCE_COORDINATOR_RECOVERY_TOKEN; verify upstream has stopped first.",
            file=sys.stderr,
        )
        return 1
    url = f"{args.url.rstrip('/')}/_coordinator/recover"
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(
                url,
                params={"resource": args.resource},
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "override": True,
                    "operator": getpass.getuser(),
                    "reason": args.reason,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "cleared":
                    print(f"Cleared restart inhibition on resource '{args.resource}'. Idle cooldown restored.")
                else:
                    print(f"No active restart inhibition found on resource '{args.resource}'.")
                return 0
            else:
                print(
                    f"Error recovering coordinator ({resp.status_code}): {resp.text}",
                    file=sys.stderr,
                )
                return 1
    except Exception as exc:
        print(f"Failed to connect to coordinator at {args.url}: {exc}", file=sys.stderr)
        return 1


async def _async_diagnose(config_path: Optional[str], url: str, as_json: bool) -> int:
    from resource_coordinator.monitors.cpu import CpuMonitor
    from resource_coordinator.monitors.gpu import NvidiaGpuMonitor

    config = load_config(config_path)
    cpu_mon = CpuMonitor()
    gpu_mon = NvidiaGpuMonitor()

    cpu_pct = cpu_mon.sample()
    gpu_metrics = await gpu_mon.get_metrics()

    gateway_online = False
    gateway_data = {}
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{url.rstrip('/')}/_coordinator/status")
            if resp.status_code == 200:
                gateway_online = True
                gateway_data = resp.json()
    except Exception:
        pass

    miner_configured = bool(config.processes)
    miner_status_info = None
    if miner_configured:
        system = build_system(config)
        if system.miner_adapter:
            st = await system.miner_adapter.status()
            miner_status_info = st.to_dict()

    diag = {
        "timestamp": time.time(),
        "execution_state": "unverified",
        "restart_authorized": False,
        "cpu_utilization_pct": cpu_pct,
        "gpus": [
            {
                "device_id": g.device_id,
                "utilization_pct": g.utilization_pct,
                "memory_used_mb": g.memory_used_mb,
                "memory_total_mb": g.memory_total_mb,
                "power_draw_w": g.power_draw_w,
            }
            for g in gpu_metrics
        ],
        "gateway": {
            "url": url,
            "online": gateway_online,
            "data": gateway_data,
        },
        "managed_miner": miner_status_info,
    }

    if as_json:
        print(json.dumps(diag, indent=2))
    else:
        print("=== Resource Coordinator Read-Only Diagnostics ===")
        print("Execution state: UNVERIFIED. Telemetry does not authorize recovery or restart.")
        print(f"CPU Utilization:    {cpu_pct:.1f}%")
        if gpu_metrics:
            for g in gpu_metrics:
                print(
                    f"GPU [{g.device_id}]:        {g.utilization_pct:.1f}% util | {g.memory_used_mb:.0f}/{g.memory_total_mb:.0f} MB VRAM | {g.power_draw_w:.1f} W"
                )
        else:
            print("GPU Telemetry:      nvidia-smi not detected or no NVIDIA devices found")
        print(f"Gateway ({url}): {'ONLINE' if gateway_online else 'OFFLINE (not running)'}")
        if miner_status_info:
            print(
                f"Managed Miner:      {miner_status_info.get('name')} (State: {miner_status_info.get('state')}, PID: {miner_status_info.get('pid')})"
            )
        else:
            print("Managed Miner:      None configured")
    return 0


def cmd_diagnose(args: argparse.Namespace) -> int:
    return asyncio.run(_async_diagnose(args.config, args.url, args.json))


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    code = 0
    if args.command == "serve":
        code = cmd_serve(args)
    elif args.command == "status":
        code = cmd_status(args)
    elif args.command == "recover":
        code = cmd_recover(args)
    elif args.command == "config":
        code = cmd_config(args)
    elif args.command == "miner":
        code = cmd_miner(args)
    elif args.command == "diagnose":
        code = cmd_diagnose(args)

    sys.exit(code)


if __name__ == "__main__":
    main()
