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
import re
from typing import List, Optional

import httpx
import uvicorn

from resource_coordinator import __version__
from resource_coordinator.core.operator_credentials import (
    CredentialError,
    doctor as credential_doctor,
    load_or_create_token,
    reinitialize_token,
    repair_permissions,
)
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

    auth_parser = subparsers.add_parser("auth", help="Diagnose or repair local operator credential storage.")
    auth_sub = auth_parser.add_subparsers(dest="auth_command", required=True)
    auth_sub.add_parser("doctor", help="Offline credential and ACL check.")
    auth_sub.add_parser("repair", help="Repair credential ACLs without changing the token.")
    auth_sub.add_parser("reinitialize", help="Rotate credential while the coordinator is stopped.")

    for action in ("restart", "shutdown"):
        lifecycle_parser = subparsers.add_parser(action, help=f"Gracefully {action} the running coordinator.")
        lifecycle_parser.add_argument("-u", "--url", default="http://127.0.0.1:1235", help="Coordinator URL.")
        lifecycle_parser.add_argument(
            "-r", "--reason", default=f"Operator requested {action}", help="Reason recorded with the request."
        )
        lifecycle_parser.add_argument("-j", "--json", action="store_true", help="Output the JSON response.")

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
        "--fake-process",
        action="store_true",
        help="Use in-memory fake process backends instead of real processes.",
    )
    serve_parser.add_argument(
        "-m",
        "--start-miner",
        action="store_true",
        dest="start_miner",
        help="Start the legacy miner target during service startup if configured.",
    )
    serve_parser.add_argument(
        "--start-process", metavar="NAME", help="Explicitly start a configured process at startup."
    )
    serve_parser.add_argument(
        "-s",
        "--stop-miner-on-shutdown",
        action="store_true",
        help="Stop miner during service shutdown if configured.",
    )
    serve_parser.add_argument(
        "--stop-process-on-shutdown", metavar="NAME", help="Stop a coordinator-owned configured process at shutdown."
    )
    serve_parser.add_argument(
        "-t",
        "--drain-timeout",
        type=float,
        default=30.0,
        help="Timeout in seconds for draining active requests during shutdown (default: 30.0).",
    )
    serve_parser.add_argument(
        "--first-boot",
        action="store_true",
        help="Initialize a fresh durable state journal if it does not already exist.",
    )

    # preflight
    preflight_parser = subparsers.add_parser(
        "preflight",
        help="Run preflight validation on coordinator configuration and environment.",
    )
    preflight_parser.add_argument("-c", "--config", default=None, help="Path to policy configuration YAML.")
    preflight_parser.add_argument(
        "-f",
        "--fake-miner",
        "--fake-process",
        action="store_true",
        help="Use in-memory fake process backends.",
    )
    preflight_parser.add_argument("-j", "--json", action="store_true", help="Output preflight result in JSON format.")
    preflight_parser.add_argument(
        "--check-live",
        action="store_true",
        help="Run read-only live acceptance preflight (checks external miners, locks, LM Studio model, and GPU VRAM).",
    )
    preflight_parser.add_argument(
        "--min-free-vram-mb",
        type=float,
        default=1024.0,
        help="Minimum free GPU VRAM (MiB) required for live preflight (default: 1024.0).",
    )

    # abort
    abort_parser = subparsers.add_parser(
        "abort",
        help="Trigger emergency abort on running coordinator service.",
    )
    abort_parser.add_argument(
        "-u",
        "--url",
        default="http://127.0.0.1:1235",
        help="Coordinator gateway URL (default: http://127.0.0.1:1235).",
    )
    abort_parser.add_argument(
        "-r",
        "--reason",
        default="Manual operator emergency abort",
        help="Reason for emergency abort.",
    )
    abort_parser.add_argument("-j", "--json", action="store_true", help="Output abort response in JSON format.")

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
    m_status.add_argument("-u", "--url", default="http://127.0.0.1:1235", help="Coordinator URL.")
    m_status.add_argument("-j", "--json", action="store_true", help="Output in JSON format.")

    for action in ("start", "stop", "resume", "pause"):
        miner_action = miner_sub.add_parser(action, help=f"Coordinator-mediated miner {action}.")
        miner_action.add_argument("-u", "--url", default="http://127.0.0.1:1235", help="Coordinator URL.")
        miner_action.add_argument("-r", "--reason", default=f"Operator requested miner {action}.")
        miner_action.add_argument("-j", "--json", action="store_true", help="Output the JSON response.")
        if action == "pause":
            pause_mode = miner_action.add_mutually_exclusive_group(required=True)
            pause_mode.add_argument("-d", "--duration", help="Hold duration, e.g. 2h, 30m, or 90s.")
            pause_mode.add_argument("--until-gpu-below", type=float, metavar="PCT",
                                    help="Resume after GPU utilization stays below this percent for a full window.")
            miner_action.add_argument("--window", default="60s", help="GPU sampling window, e.g. 60s or 2m.")
    m_status.add_argument("-c", "--config", default=None, help=argparse.SUPPRESS)

    gaming_parser = subparsers.add_parser("gaming", help="Safely unload and restore local models for gaming.")
    gaming_sub = gaming_parser.add_subparsers(dest="gaming_command", required=True)
    gaming_status = gaming_sub.add_parser("status", help="Show gaming mode state.")
    gaming_status.add_argument("-u", "--url", default="http://127.0.0.1:1235")
    gaming_status.add_argument("-j", "--json", action="store_true")
    for action in ("start", "stop"):
        gaming_action = gaming_sub.add_parser(action, help=f"Gaming mode {action}.")
        gaming_action.add_argument("-u", "--url", default="http://127.0.0.1:1235")
        gaming_action.add_argument("-r", "--reason", default=f"Operator requested gaming {action}.")
        gaming_action.add_argument("-j", "--json", action="store_true")

    logs_parser = subparsers.add_parser("logs", help="Read or follow captured raw process output.")
    logs_parser.add_argument("process_name", help="Configured process name, e.g. krig.")
    logs_parser.add_argument("-u", "--url", default="http://127.0.0.1:1235")
    logs_parser.add_argument("--tail-bytes", type=int, default=65536, help="Initial history bytes (max 256 KiB).")
    logs_parser.add_argument("-f", "--follow", action="store_true", help="Continue polling for appended output.")

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

    # accept
    accept_parser = subparsers.add_parser(
        "accept",
        help="Run automated supervised acceptance trials for miner/LLM coordination.",
    )
    accept_parser.add_argument("-c", "--config", default=None, help="Path to policy configuration YAML.")
    accept_parser.add_argument(
        "-m",
        "--mode",
        choices=["simulated", "disposable_helper", "live"],
        default="simulated",
        help="Execution mode (default: simulated).",
    )
    accept_parser.add_argument(
        "--allow-live-lmstudio",
        action="store_true",
        help="Explicitly authorize connection to live LM Studio upstream.",
    )
    accept_parser.add_argument(
        "--allow-real-miner",
        action="store_true",
        help="Explicitly authorize launching the configured real miner process.",
    )
    accept_parser.add_argument(
        "-u",
        "--upstream",
        default=None,
        help="Upstream LM Studio URL override.",
    )
    accept_parser.add_argument(
        "-w",
        "--work-dir",
        default=None,
        help="Work directory for isolated run evidence (default: creates temp dir or uses .live_acceptance_work).",
    )
    accept_parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Optional destination path to write acceptance_report.json.",
    )
    accept_parser.add_argument(
        "--trials",
        nargs="+",
        default=None,
        help="Specific trials to run (e.g. --trials T01 or --trials T02 T03 T04).",
    )
    accept_parser.add_argument(
        "--cooldown",
        type=float,
        default=None,
        help="Override cooldown seconds (live mode enforces >= 10.0s).",
    )
    accept_parser.add_argument("-j", "--json", action="store_true", help="Output acceptance report in JSON format.")

    return parser.parse_args(args)


def _operator_token() -> Optional[str]:
    try:
        return (
            os.environ.get("RESOURCE_COORDINATOR_OPERATOR_TOKEN")
            or os.environ.get("RESOURCE_COORDINATOR_RECOVERY_TOKEN")
            or load_or_create_token()
        )
    except CredentialError as exc:
        print(f"Operator credential unavailable: {exc}. Run 'resource-coordinator auth doctor'.", file=sys.stderr)
        return None


def cmd_auth(args: argparse.Namespace) -> int:
    try:
        if args.auth_command == "doctor":
            report = credential_doctor()
            print(json.dumps(report, indent=2))
            return 0 if (
                report["credential_valid"]
                and report["credential_file_readable"]
                and report["acl_restricted"]
                and report["environment_override_matches_file"] is not False
            ) else 1
        if args.auth_command == "repair":
            repair_permissions()
            print("Operator credential ACL repaired; token unchanged.")
            return 0
        if os.environ.get("RESOURCE_COORDINATOR_OPERATOR_TOKEN"):
            raise CredentialError("Unset RESOURCE_COORDINATOR_OPERATOR_TOKEN before reinitializing")
        reinitialize_token()
        print("Operator credential reinitialized. It was not displayed.")
        return 0
    except CredentialError as exc:
        print(f"Authentication maintenance failed: {exc}", file=sys.stderr)
        return 1


def cmd_serve(args: argparse.Namespace) -> int:
    from resource_coordinator.core.service import CoordinatorService
    while True:
        try:
            load_or_create_token()
        except CredentialError as exc:
            # Authentication failure disables privileged controls, not the coordinator.
            logger.error("Operator credential unavailable; service remains operational: %s", exc)
        config = load_config(args.config)
        if args.listen:
            parts = args.listen.split(":")
            config.service.listen_host = parts[0]
            config.service.listen_port = int(parts[1]) if len(parts) > 1 else 1235
        if args.upstream:
            config.service.upstream_url = args.upstream

        system = build_system(config, use_fake_processes=args.fake_miner)
        service = CoordinatorService(
            system=system,
            start_miner_on_ready=getattr(args, "start_miner", False),
            stop_miner_on_shutdown=getattr(args, "stop_miner_on_shutdown", False),
            start_process_on_ready=getattr(args, "start_process", None),
            stop_process_on_shutdown=getattr(args, "stop_process_on_shutdown", None),
            drain_timeout_seconds=getattr(args, "drain_timeout", 30.0),
            first_boot=getattr(args, "first_boot", False),
        )
        app = system.gateway.create_app(service)
        app.state.restart_requested = False
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=config.service.listen_host,
                port=config.service.listen_port,
                log_level="info" if args.verbose else "warning",
            )
        )
        app.state.request_server_exit = lambda: setattr(server, "should_exit", True)

        print(f"Starting Resource Coordinator Gateway v{__version__}")
        print(f"Listening on:  http://{config.service.listen_host}:{config.service.listen_port}")
        print(f"Upstream host: {config.service.upstream_url}")
        print(f"Managed procs: {list(system.supervisors.keys())}")
        print(f"Service state: {service.state.value}")
        server.run()
        if not app.state.restart_requested or service.state.value != "stopped":
            break
    return 0


def cmd_lifecycle(args: argparse.Namespace) -> int:
    token = _operator_token()
    if not token:
        print("Lifecycle control requires a local operator credential; run 'resource-coordinator auth doctor'.", file=sys.stderr)
        return 1
    url = f"{args.url.rstrip('/')}/_coordinator/{args.command}"
    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json={"operator": getpass.getuser(), "reason": args.reason},
            )
        if response.status_code == 202:
            payload = response.json()
            print(
                json.dumps(payload, indent=2)
                if args.json
                else f"Coordinator {args.command} requested; draining active work."
            )
            return 0
        print(f"Coordinator {args.command} failed ({response.status_code}): {response.text}", file=sys.stderr)
    except Exception as exc:
        print(f"Failed to contact coordinator at {args.url}: {exc}", file=sys.stderr)
    return 1


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
                    print(f"Service State:      {data.get('service_state')}")
                    print(f"Ready:              {data.get('is_ready')}")
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
                    processes = data.get("processes", {})
                    if processes:
                        for name, process in processes.items():
                            print(
                                f"Process {name}: {process.get('state')} "
                                f"(PID: {process.get('pid')}, owner: {process.get('lifecycle_owner')}, "
                                f"coordinator-owned: {process.get('is_coordinator_owned')}, "
                                f"stopped by coordinator: {process.get('was_stopped_by_coordinator')})"
                            )
                    else:
                        print("Managed processes:  None")
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


def _parse_hold_duration(value: str) -> float:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(s|m|h|d)\s*", value, re.IGNORECASE)
    if not match:
        raise argparse.ArgumentTypeError("Duration must use s, m, h, or d (for example 2h).")
    return float(match.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2).lower()]


async def _async_miner_command(args: argparse.Namespace) -> int:
    if args.miner_command == "status":
        method, endpoint, payload = "GET", "status", None
    else:
        method, endpoint = "POST", args.miner_command
        payload = {"operator": getpass.getuser(), "reason": args.reason}
        if args.miner_command == "pause":
            if args.until_gpu_below is not None:
                try:
                    payload["until_gpu_below_pct"] = args.until_gpu_below
                    payload["window_seconds"] = _parse_hold_duration(args.window)
                except argparse.ArgumentTypeError as exc:
                    print(str(exc), file=sys.stderr)
                    return 2
            else:
                try:
                    payload["duration_seconds"] = _parse_hold_duration(args.duration)
                except argparse.ArgumentTypeError as exc:
                    print(str(exc), file=sys.stderr)
                    return 2
    headers = {}
    if method == "POST":
        token = _operator_token()
        if not token:
            print("Miner control requires a local operator credential; run 'resource-coordinator auth doctor'.", file=sys.stderr)
            return 1
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(method, f"{args.url.rstrip('/')}/_coordinator/miner/{endpoint}",
                                            headers=headers, json=payload)
        data = response.json()
        if response.status_code != 200:
            print(f"Miner {args.miner_command} failed ({response.status_code}): {data}", file=sys.stderr)
            return 1
        if args.miner_command == "status" or getattr(args, "json", False):
            print(json.dumps(data, indent=2))
        else:
            print(f"Miner control: {data.get('status')}")
        return 0
    except Exception as exc:
        print(f"Failed to contact coordinator at {args.url}: {exc}", file=sys.stderr)
        return 1


def cmd_miner(args: argparse.Namespace) -> int:
    return asyncio.run(_async_miner_command(args))


async def _async_gaming_command(args: argparse.Namespace) -> int:
    action = args.gaming_command
    headers = {}
    payload = None
    if action != "status":
        token = _operator_token()
        if not token:
            print("Gaming control requires a local operator credential; run 'resource-coordinator auth doctor'.", file=sys.stderr)
            return 1
        headers["Authorization"] = f"Bearer {token}"
        payload = {"operator": getpass.getuser(), "reason": args.reason}
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.request(
                "GET" if action == "status" else "POST",
                f"{args.url.rstrip('/')}/_coordinator/gaming/{action}",
                headers=headers, json=payload,
            )
        data = response.json()
        if response.status_code != 200:
            print(f"Gaming {action} failed ({response.status_code}): {data}", file=sys.stderr)
            return 1
        if args.json or action == "status":
            print(json.dumps(data, indent=2))
        else:
            print(f"Gaming mode: {data.get('status')}")
        return 0
    except Exception as exc:
        print(f"Failed to contact coordinator at {args.url}: {exc}", file=sys.stderr)
        return 1


def cmd_gaming(args: argparse.Namespace) -> int:
    return asyncio.run(_async_gaming_command(args))


async def _async_logs(args: argparse.Namespace) -> int:
    token = _operator_token()
    if not token:
        print("Captured logs require a local operator credential; run 'resource-coordinator auth doctor'.", file=sys.stderr)
        return 1
    if not 0 <= args.tail_bytes <= 262144:
        print("--tail-bytes must be between 0 and 262144.", file=sys.stderr)
        return 2
    headers = {"Authorization": f"Bearer {token}"}
    offset = None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            while True:
                params = {"tail_bytes": args.tail_bytes} if offset is None else {"offset": offset}
                response = await client.get(
                    f"{args.url.rstrip('/')}/_coordinator/logs/{args.process_name}",
                    headers=headers, params=params,
                )
                if response.status_code != 200:
                    print(f"Log request failed ({response.status_code}): {response.text}", file=sys.stderr)
                    return 1
                data = response.content
                if data:
                    stream = getattr(sys.stdout, "buffer", None)
                    if stream is not None:
                        stream.write(data)
                        stream.flush()
                    else:
                        sys.stdout.write(data.decode("utf-8", errors="replace"))
                        sys.stdout.flush()
                offset = int(response.headers["x-log-offset"])
                if not args.follow:
                    return 0
                await asyncio.sleep(0.5)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"Failed to follow logs at {args.url}: {exc}", file=sys.stderr)
        return 1


def cmd_logs(args: argparse.Namespace) -> int:
    return asyncio.run(_async_logs(args))


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


async def _async_preflight(
    config_path: Optional[str],
    fake_miner: bool,
    as_json: bool,
    check_live: bool = False,
    min_free_vram_mb: float = 1024.0,
) -> int:
    config = load_config(config_path)
    if check_live:
        from resource_coordinator.acceptance_harness import run_live_acceptance_preflight

        live_result = await run_live_acceptance_preflight(config, min_free_vram_mb=min_free_vram_mb)
        ready = bool(live_result.get("ready_for_supervised_live"))
        if as_json:
            print(json.dumps(live_result, indent=2))
        else:
            print(f"Live Acceptance Preflight: {'READY' if ready else 'BLOCKED'}")
            loaded = live_result.get("loaded_model")
            if loaded:
                print(
                    f"  Loaded Model:     {loaded.get('model_id')} "
                    f"(source: {loaded.get('source')}, context: {loaded.get('loaded_context_length')})"
                )
            vram = live_result.get("vram_headroom")
            if vram:
                print(
                    f"  GPU VRAM Free:    {vram.get('free_mb'):.0f} MiB free / "
                    f"{vram.get('memory_total_mb'):.0f} MiB total "
                    f"(min required: {vram.get('min_required_free_mb'):.0f} MiB)"
                )
            for warn in live_result.get("warnings", []):
                print(f"  WARNING: {warn}")
            for reason in live_result.get("blocking_reasons", []):
                print(f"  BLOCKING: {reason}")
        return 0 if ready else 1

    system = build_system(config, use_fake_processes=fake_miner)
    from resource_coordinator.core.service import CoordinatorService

    service = CoordinatorService(system=system)
    passed, messages = service.preflight_check()
    await system.gateway.close()
    if as_json:
        data = {
            "passed": passed,
            "messages": messages,
            "errors": [m for m in messages if m.startswith("ERROR")],
            "warnings": [m for m in messages if m.startswith("WARNING")],
        }
        print(json.dumps(data, indent=2))
    else:
        print(f"Preflight status: {'PASSED' if passed else 'FAILED'}")
        for msg in messages:
            print(f"  {msg}")
    return 0 if passed else 1


def cmd_preflight(args: argparse.Namespace) -> int:
    config_path = args.config
    if config_path is None and getattr(args, "check_live", False) and os.path.exists("config.live-local.yaml"):
        config_path = "config.live-local.yaml"
    return asyncio.run(
        _async_preflight(
            config_path,
            args.fake_miner,
            args.json,
            check_live=getattr(args, "check_live", False),
            min_free_vram_mb=getattr(args, "min_free_vram_mb", 1024.0),
        )
    )


async def _async_accept(args: argparse.Namespace) -> int:
    from resource_coordinator.acceptance_harness import AcceptanceHarness

    config_path = args.config
    if config_path is None and args.mode == "live" and os.path.exists("config.live-local.yaml"):
        config_path = "config.live-local.yaml"

    trials_to_run = None
    if getattr(args, "trials", None):
        raw_trials = args.trials
        if isinstance(raw_trials, list):
            trials_to_run = []
            for item in raw_trials:
                for part in str(item).split(","):
                    p = part.strip()
                    if p:
                        trials_to_run.append(p)
        elif isinstance(raw_trials, str):
            trials_to_run = [p.strip() for p in raw_trials.split(",") if p.strip()]

    harness = AcceptanceHarness.from_config(
        config=config_path,
        mode=args.mode,
        allow_live_lmstudio=getattr(args, "allow_live_lmstudio", False),
        allow_real_miner=getattr(args, "allow_real_miner", False),
        work_dir=getattr(args, "work_dir", None),
        trials_to_run=trials_to_run,
    )
    if getattr(args, "upstream", None):
        harness.lmstudio_url = args.upstream
    if getattr(args, "cooldown", None) is not None:
        harness.cooldown_seconds = float(args.cooldown)

    try:
        report = await harness.run_all(output_file=getattr(args, "output", None))
        if getattr(args, "json", False):
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(f"=== Resource Coordinator Acceptance Run: {report.run_id} ===")
            print(f"Mode:               {report.mode}")
            print(f"Process Backend:    {report.process_backend}")
            print(f"Upstream Type:      {report.upstream_type}")
            print(f"Verification Level: {report.verification_level}")
            print(f"Run Directory:      {report.run_dir}")
            print(f"Trials executed:    {len(report.trials)}")
            for t in report.trials:
                print(f"  [{t.status}] {t.trial_id}: {t.name}")
                if getattr(t, "error", None):
                    print(f"      Error: {t.error}")
            summary = report.summary
            all_passed = bool(summary.get("all_passed"))
            print(f"Result:             {'PASS' if all_passed else 'FAIL'}")
            print(f"Passed:             {summary.get('passed', 0)} / {summary.get('total_trials', 0)}")
            if summary.get("mock_only_trials_skipped"):
                print(f"Mock trials skipped:{summary.get('mock_only_trials_skipped')}")
        return 0 if report.summary.get("all_passed") else 1
    except Exception as exc:
        print(f"Acceptance run failed: {exc}", file=sys.stderr)
        return 1


def cmd_accept(args: argparse.Namespace) -> int:
    return asyncio.run(_async_accept(args))


def cmd_abort(args: argparse.Namespace) -> int:
    token = _operator_token()
    if not token:
        print("Abort requires a local operator credential; run 'resource-coordinator auth doctor'.", file=sys.stderr)
        return 1
    url = f"{args.url.rstrip('/')}/_coordinator/abort"
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json={"reason": args.reason, "operator": getpass.getuser()},
            )
            if resp.status_code == 200:
                data = resp.json()
                if args.json:
                    print(json.dumps(data, indent=2))
                else:
                    print("Emergency abort acknowledged by coordinator:")
                    print(f"  Status:        {data.get('status')}")
                    print(f"  Service State: {data.get('service_state') or data.get('state')}")
                    print(f"  Reason:        {data.get('reason')}")
                    if data.get("inhibited_resources"):
                        print(f"  Inhibited:     {', '.join(data['inhibited_resources'])}")
                return 0
            else:
                print(
                    f"Error triggering coordinator abort ({resp.status_code}): {resp.text}",
                    file=sys.stderr,
                )
                return 1
    except Exception as exc:
        print(f"Failed to connect to coordinator at {args.url}: {exc}", file=sys.stderr)
        return 1


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    code = 0
    if args.command == "auth":
        code = cmd_auth(args)
    elif args.command == "serve":
        code = cmd_serve(args)
    elif args.command in {"restart", "shutdown"}:
        code = cmd_lifecycle(args)
    elif args.command == "status":
        code = cmd_status(args)
    elif args.command == "recover":
        code = cmd_recover(args)
    elif args.command == "config":
        code = cmd_config(args)
    elif args.command == "miner":
        code = cmd_miner(args)
    elif args.command == "gaming":
        code = cmd_gaming(args)
    elif args.command == "logs":
        code = cmd_logs(args)
    elif args.command == "diagnose":
        code = cmd_diagnose(args)
    elif args.command == "preflight":
        code = cmd_preflight(args)
    elif args.command == "accept":
        code = cmd_accept(args)
    elif args.command == "abort":
        code = cmd_abort(args)

    sys.exit(code)


if __name__ == "__main__":
    main()
