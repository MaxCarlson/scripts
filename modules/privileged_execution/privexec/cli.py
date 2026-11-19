"""CLI entry point for privexec."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import __version__
from .protocol import (
    DEFAULT_PIPE_NAME,
    ProtocolValidationError,
    build_result_request,
    build_run_request,
    build_status_request,
    build_stop_request,
    load_params_file,
)
from .transport import (
    BrokerNotRunningError,
    PipeAccessDeniedError,
    TransportError,
    UnsupportedPlatformError,
    WindowsNamedPipeClient,
)

TERMINAL_OPERATION_STATES = frozenset({"succeeded", "failed", "denied", "outcome_unknown"})


def _module_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _default_broker_dll() -> Path:
    return _module_root() / "broker" / "bin" / "PrivExecBroker.dll"


def _default_descriptors_dir() -> Path:
    return _module_root() / "descriptors"


def _default_state_dir() -> Path:
    return _module_root() / ".privexec_state"


def _format_output(data: dict[str, Any], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(data, indent=2, ensure_ascii=False)
    lines = []
    for key in (
        "operation_id",
        "request_id",
        "capability",
        "target_id",
        "mode",
        "state",
        "authorized",
        "exit_code",
        "diagnostic_category",
        "error",
        "status",
        "session_id",
        "expires_at",
    ):
        if key in data and data[key] is not None:
            lines.append(f"{key}: {data[key]}")
    if "result" in data and data["result"]:
        lines.append(f"result: {json.dumps(data['result'], ensure_ascii=False)}")
    if not lines:
        return json.dumps(data, indent=2, ensure_ascii=False)
    return "\n".join(lines)


def _send_request(
    *,
    pipe_name: str,
    payload: dict[str, Any],
    client_factory: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    client = client_factory(pipe_name) if client_factory else WindowsNamedPipeClient(pipe_name)
    return client.send(payload)


def _cmd_status(args: argparse.Namespace, client_factory: Callable[[str], Any] | None) -> int:
    resp = _send_request(
        pipe_name=args.pipe,
        payload=build_status_request(),
        client_factory=client_factory,
    )
    print(_format_output(resp, args.format))
    return 0 if resp.get("ok", True) else 1


def _cmd_run(args: argparse.Namespace, client_factory: Callable[[str], Any] | None) -> int:
    if args.dry_run and args.apply:
        raise ProtocolValidationError("Cannot combine -n/--dry-run and -A/--apply.")
    mode = "apply" if args.apply else "dry_run"
    params = load_params_file(Path(args.params_file)) if args.params_file else {}
    req = build_run_request(
        capability=args.capability,
        target_id=args.target,
        target_type=args.target_type,
        mode=mode,
        request_id=args.request_id,
        parameters=params,
    )
    resp = _send_request(pipe_name=args.pipe, payload=req, client_factory=client_factory)
    print(_format_output(resp, args.format))
    state = resp.get("state")
    if state in {"denied", "failed", "outcome_unknown"} or resp.get("ok") is False:
        return 1
    return 0


def _cmd_result(args: argparse.Namespace, client_factory: Callable[[str], Any] | None) -> int:
    req = build_result_request(args.operation_id)
    deadline = time.monotonic() + max(0, int(args.wait_timeout))
    while True:
        resp = _send_request(pipe_name=args.pipe, payload=req, client_factory=client_factory)
        state = resp.get("state")
        if not args.wait or state in TERMINAL_OPERATION_STATES or resp.get("ok") is False:
            print(_format_output(resp, args.format))
            if resp.get("ok") is False or state in {"denied", "failed", "outcome_unknown"}:
                return 1
            return 0
        if time.monotonic() >= deadline:
            print(_format_output(resp, args.format))
            return 2
        time.sleep(0.25)


def _cmd_broker_start(args: argparse.Namespace) -> int:
    if os.name != "nt":
        raise UnsupportedPlatformError("PrivExec broker is supported only on Windows 11.")
    broker_dll = Path(args.broker_dll) if args.broker_dll else _default_broker_dll()
    descriptors_dir = Path(args.descriptors_dir) if args.descriptors_dir else _default_descriptors_dir()
    state_dir = Path(args.state_dir) if args.state_dir else _default_state_dir()

    cmd = [
        "dotnet",
        str(broker_dll),
        "--pipe",
        args.pipe,
        "--descriptors-dir",
        str(descriptors_dir),
        "--state-dir",
        str(state_dir),
        "--ttl-seconds",
        str(args.ttl_seconds),
    ]
    if args.config:
        cmd.extend(["--grant-file", str(Path(args.config))])
    if args.allow_same_user:
        cmd.append("--allow-same-user")
    if args.prompt_guest_credential:
        cmd.append("--prompt-guest-credential")

    if args.dry_run:
        plan = {
            "action": "broker_start_plan",
            "broker_dll": str(broker_dll),
            "broker_exists": broker_dll.is_file(),
            "descriptors_dir": str(descriptors_dir),
            "state_dir": str(state_dir),
            "pipe": args.pipe,
            "ttl_seconds": args.ttl_seconds,
            "command": cmd,
        }
        print(json.dumps(plan, indent=2))
        return 0

    if not broker_dll.is_file():
        raise FileNotFoundError(
            f"Compiled broker assembly not found at '{broker_dll}'. Run scripts/Build-PrivExecBroker.ps1 first."
        )
    if shutil.which("dotnet") is None:
        raise FileNotFoundError("'dotnet' runtime was not found on PATH.")
    proc = subprocess.run(cmd, check=False)
    return proc.returncode


def _cmd_broker_stop(args: argparse.Namespace, client_factory: Callable[[str], Any] | None) -> int:
    resp = _send_request(
        pipe_name=args.pipe,
        payload=build_stop_request(),
        client_factory=client_factory,
    )
    print(_format_output(resp, args.format))
    return 0 if resp.get("ok", True) else 1


def build_parser() -> argparse.ArgumentParser:
    """Create the privexec CLI argument parser (all flags have short + long forms)."""
    parser = argparse.ArgumentParser(
        prog="privexec",
        description="PrivExec — request narrowly authorized privileged operations from an operator-started broker.",
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # status
    p_status = subparsers.add_parser("status", help="Check broker reachability and non-secret session status.")
    p_status.add_argument("-P", "--pipe", default=DEFAULT_PIPE_NAME, help="Local Windows named pipe name.")
    p_status.add_argument("-f", "--format", choices=("json", "text"), default="text", help="Output format.")

    # run
    p_run = subparsers.add_parser("run", help="Submit an approved capability request to the broker.")
    p_run.add_argument("capability", help="Registered capability ID (e.g. synthetic.echo, h4.preflight).")
    p_run.add_argument("-t", "--target", required=True, help="Exact target ID authorized for the operation.")
    p_run.add_argument("-T", "--target-type", default="hyperv_vm", help="Target resource type (default: hyperv_vm).")
    p_run.add_argument("-p", "--params-file", help="Path to JSON file containing untrusted capability parameters.")
    p_run.add_argument("-n", "--dry-run", action="store_true", help="Request dry-run execution (default).")
    p_run.add_argument("-A", "--apply", action="store_true", help="Request mutating execution (requires grant).")
    p_run.add_argument("-r", "--request-id", help="Client-generated idempotency request ID.")
    p_run.add_argument("-P", "--pipe", default=DEFAULT_PIPE_NAME, help="Local Windows named pipe name.")
    p_run.add_argument("-f", "--format", choices=("json", "text"), default="json", help="Output format.")

    # result
    p_result = subparsers.add_parser("result", help="Retrieve an existing operation result without re-executing.")
    p_result.add_argument("operation_id", help="Broker-issued operation ID.")
    p_result.add_argument("-w", "--wait", action="store_true", help="Poll briefly until operation completes.")
    p_result.add_argument(
        "-W", "--wait-timeout", type=int, default=30, help="Maximum seconds to wait when -w/--wait is set."
    )
    p_result.add_argument("-P", "--pipe", default=DEFAULT_PIPE_NAME, help="Local Windows named pipe name.")
    p_result.add_argument("-f", "--format", choices=("json", "text"), default="json", help="Output format.")

    # broker
    p_broker = subparsers.add_parser("broker", help="Operator-only broker session commands.")
    broker_sub = p_broker.add_subparsers(dest="broker_command", required=True)

    p_bstart = broker_sub.add_parser("start", help="Operator-only: start the privileged session broker.")
    p_bstart.add_argument("-c", "--config", help="Path to operator session grant JSON file.")
    p_bstart.add_argument("-d", "--descriptors-dir", help="Protected capability descriptors directory.")
    p_bstart.add_argument("-s", "--state-dir", help="Protected SQLite/evidence state directory.")
    p_bstart.add_argument("-b", "--broker-dll", help="Path to compiled PrivExecBroker.dll.")
    p_bstart.add_argument("-P", "--pipe", default=DEFAULT_PIPE_NAME, help="Local Windows named pipe name.")
    p_bstart.add_argument("-t", "--ttl-seconds", type=int, default=1800, help="Session lifetime in seconds.")
    p_bstart.add_argument(
        "-a", "--allow-same-user", action="store_true", help="Dev mode: authorize current operator SID as client."
    )
    p_bstart.add_argument(
        "-g",
        "--prompt-guest-credential",
        action="store_true",
        help="Prompt operator in console for PowerShell Direct guest credential.",
    )
    p_bstart.add_argument("-n", "--dry-run", action="store_true", help="Print launch plan without starting broker.")

    p_bstop = broker_sub.add_parser("stop", help="Operator-only: revoke session and shut down broker.")
    p_bstop.add_argument("-P", "--pipe", default=DEFAULT_PIPE_NAME, help="Local Windows named pipe name.")
    p_bstop.add_argument("-f", "--format", choices=("json", "text"), default="text", help="Output format.")

    return parser


def main(
    argv: list[str] | None = None,
    *,
    client_factory: Callable[[str], Any] | None = None,
) -> int:
    """CLI main entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            return _cmd_status(args, client_factory)
        if args.command == "run":
            return _cmd_run(args, client_factory)
        if args.command == "result":
            return _cmd_result(args, client_factory)
        if args.command == "broker":
            if args.broker_command == "start":
                return _cmd_broker_start(args)
            if args.broker_command == "stop":
                return _cmd_broker_stop(args, client_factory)
        parser.print_help()
        return 2
    except (
        ProtocolValidationError,
        UnsupportedPlatformError,
        BrokerNotRunningError,
        PipeAccessDeniedError,
        TransportError,
        FileNotFoundError,
        ValueError,
    ) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - top-level CLI boundary
        print(json.dumps({"ok": False, "error": f"Unexpected privexec error: {exc}"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
