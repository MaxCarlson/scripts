"""
Command-line interface for Resource Coordinator.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import os
import sys
import time
import re
from typing import Any, List, Optional

import httpx
import uvicorn

from resource_coordinator import __version__
from resource_coordinator.cli_dispatch import normalize_dispatch_args
from resource_coordinator.cli_parser import parse_args
from resource_coordinator.presentation import (
    emit_error,
    emit_json,
    emit_text,
    render_coordinator_status,
    render_result,
    set_color_mode,
)
from resource_coordinator.core.operator_credentials import (
    CredentialError,
    doctor as credential_doctor,
    load_or_create_token,
    load_token,
    reinitialize_token,
    repair_permissions,
)
from resource_coordinator.config import build_system, load_config

logger = logging.getLogger("resource_coordinator")


def _operator_token() -> Optional[str]:
    try:
        return (
            os.environ.get("RESOURCE_COORDINATOR_OPERATOR_TOKEN")
            or os.environ.get("RESOURCE_COORDINATOR_RECOVERY_TOKEN")
            or load_or_create_token()
        )
    except CredentialError as exc:
        emit_error(f"Operator credential unavailable: {exc}. Run 'resource-coordinator system auth doctor'.")
        return None


def cmd_auth(args: argparse.Namespace) -> int:
    try:
        if args.auth_command == "doctor":
            report = credential_doctor()
            if getattr(args, "json", False):
                emit_json(report)
            else:
                render_result("Operator Credentials", report)
            return 0 if (
                report["credential_valid"]
                and report["credential_file_readable"]
                and report["acl_restricted"]
                and report["environment_override_matches_file"] is not False
            ) else 1
        if args.auth_command == "repair":
            repair_permissions()
            result = {"status": "repaired", "message": "Operator credential ACL repaired; token unchanged."}
            if getattr(args, "json", False):
                emit_json(result)
            else:
                emit_text(result["message"], style="green")
            return 0
        if os.environ.get("RESOURCE_COORDINATOR_OPERATOR_TOKEN"):
            raise CredentialError("Unset RESOURCE_COORDINATOR_OPERATOR_TOKEN before reinitializing")
        reinitialize_token()
        result = {"status": "reinitialized", "message": "Operator credential reinitialized. It was not displayed."}
        if getattr(args, "json", False):
            emit_json(result)
        else:
            emit_text(result["message"], style="green")
        return 0
    except CredentialError as exc:
        if getattr(args, "json", False):
            emit_json({"status": "error", "operation": "auth", "message": str(exc)})
        else:
            emit_error(f"Authentication maintenance failed: {exc}")
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

        emit_text(f"Starting Resource Coordinator Gateway v{__version__}", style="bold")
        emit_text(f"Listening on:  http://{config.service.listen_host}:{config.service.listen_port}")
        emit_text(f"Upstream host: {config.service.upstream_url}")
        emit_text(f"Managed procs: {', '.join(system.supervisors.keys()) or 'None'}")
        emit_text(f"Service state: {service.state.value}")
        server.run()
        if not app.state.restart_requested or service.state.value != "stopped":
            break
    return 0


def cmd_lifecycle(args: argparse.Namespace) -> int:
    token = _operator_token()
    if not token:
        message = "Lifecycle control requires a local operator credential; run 'resource-coordinator system auth doctor'."
        if getattr(args, "json", False):
            emit_json({"status": "error", "operation": args.command, "message": message})
        else:
            emit_error(message)
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
            if args.json:
                emit_json(payload)
            else:
                render_result(f"Coordinator {args.command.title()}", payload)
            return 0
        detail = response.text
        try:
            body = response.json()
            if isinstance(body, dict):
                detail = body.get("message") or body.get("error") or body.get("reason") or detail
            else:
                detail = body
        except ValueError:
            body = {"message": detail}
        if args.json:
            emit_json({"status": "error", "operation": args.command, "http_status": response.status_code,
                       "detail": body})
        else:
            emit_error(f"Coordinator {args.command} failed ({response.status_code}): {detail}")
    except Exception as exc:
        message = f"Failed to contact coordinator at {args.url}: {exc}"
        if args.json:
            emit_json({"status": "error", "operation": args.command, "message": message})
        else:
            emit_error(message)
    return 1


def cmd_status(args: argparse.Namespace) -> int:
    target = getattr(args, "status_target", None)
    endpoint = {
        "miner": "miner/status", "inference": "inference/status", "gaming": "gaming/status",
        "maintenance": "maintenance/status",
    }.get(target, "status")
    url = f"{args.url.rstrip('/')}/_coordinator/{endpoint}"
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                if args.json:
                    emit_json(data)
                elif target == "inference":
                    from resource_coordinator.presentation import render_inference_status
                    render_inference_status(data)
                elif target == "maintenance":
                    from resource_coordinator.presentation import render_maintenance_status
                    render_maintenance_status(data)
                elif target == "miner":
                    from resource_coordinator.presentation import render_miner_status
                    render_miner_status(data)
                elif target == "gaming":
                    from resource_coordinator.presentation import render_gaming_status
                    render_gaming_status(data)
                else:
                    render_coordinator_status(data, gateway_url=args.url)
                return 0
            else:
                detail = resp.text
                try:
                    body = resp.json()
                    detail = body.get("message") or body.get("error") or detail if isinstance(body, dict) else body
                except ValueError:
                    body = {"message": detail}
                if args.json:
                    emit_json({"status": "error", "operation": "status", "http_status": resp.status_code,
                               "detail": body})
                else:
                    emit_error(f"Error querying coordinator ({resp.status_code}): {detail}")
                return 1
    except Exception as exc:
        message = f"Failed to connect to coordinator at {args.url}: {exc}"
        if args.json:
            emit_json({"status": "error", "operation": "status", "message": message})
        else:
            emit_error(message)
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
            emit_json(data)
        else:
            render_result("Configuration", {
                "status": "valid", "version": config.version,
                "listen": f"{config.service.listen_host}:{config.service.listen_port}",
                "upstream": config.service.upstream_url,
                "processes": list(config.processes.keys()),
                "policies": [p.name for p in config.policies],
            })
        return 0

    elif args.config_command == "validate":
        try:
            load_config(args.config)
            if getattr(args, "json", False):
                emit_json({"status": "valid", "path": args.config})
            else:
                render_result("Configuration Validation", {"status": "valid", "path": args.config})
            return 0
        except Exception as exc:
            if getattr(args, "json", False):
                emit_json({"status": "error", "path": args.config, "message": str(exc)})
            else:
                emit_error(f"Configuration validation failed: {exc}")
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
                    emit_error(str(exc))
                    return 2
            else:
                try:
                    payload["duration_seconds"] = _parse_hold_duration(args.duration)
                except argparse.ArgumentTypeError as exc:
                    emit_error(str(exc))
                    return 2
    headers = {}
    if method == "POST":
        token = _operator_token()
        if not token:
            message = "Miner control requires a local operator credential; run 'resource-coordinator system auth doctor'."
            if getattr(args, "json", False):
                emit_json({"status": "error", "operation": args.miner_command, "message": message})
            else:
                emit_error(message)
            return 1
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(method, f"{args.url.rstrip('/')}/_coordinator/miner/{endpoint}",
                                            headers=headers, json=payload)
        data = response.json()
        if response.status_code != 200:
            if getattr(args, "json", False):
                emit_json({"status": "error", "operation": args.miner_command,
                           "http_status": response.status_code, "detail": data})
            else:
                reason = data.get("reason") or data.get("error") or data.get("message") if isinstance(data, dict) else str(data)
                emit_error(f"Miner {args.miner_command} failed ({response.status_code}): {reason}")
            return 1
        if getattr(args, "json", False):
            emit_json(data)
        else:
            from resource_coordinator.presentation import render_miner_status
            if getattr(args, "miner_command", None) == "status":
                render_miner_status(data)
            else:
                render_result("Miner", data)
        return 0
    except Exception as exc:
        message = f"Failed to contact coordinator at {args.url}: {exc}"
        if getattr(args, "json", False):
            emit_json({"status": "error", "operation": args.miner_command, "message": message})
        else:
            emit_error(message)
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
            message = "Gaming control requires a local operator credential; run 'resource-coordinator system auth doctor'."
            if getattr(args, "json", False):
                emit_json({"status": "error", "operation": action, "message": message})
            else:
                emit_error(message)
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
            if getattr(args, "json", False):
                emit_json({"status": "error", "operation": action, "http_status": response.status_code,
                           "detail": data})
            else:
                reason = data.get("reason") or data.get("error") or data.get("message") if isinstance(data, dict) else str(data)
                emit_error(f"Gaming {action} failed ({response.status_code}): {reason}")
            return 1
        if getattr(args, "json", False):
            emit_json(data)
        else:
            from resource_coordinator.presentation import render_gaming_status
            if action == "status":
                render_gaming_status(data)
            else:
                render_result("Gaming Mode", data)
        return 0
    except Exception as exc:
        message = f"Failed to contact coordinator at {args.url}: {exc}"
        if getattr(args, "json", False):
            emit_json({"status": "error", "operation": action, "message": message})
        else:
            emit_error(message)
        return 1


def cmd_gaming(args: argparse.Namespace) -> int:
    return asyncio.run(_async_gaming_command(args))


async def _async_logs(args: argparse.Namespace) -> int:
    token = _operator_token()
    if not token:
        emit_error("Captured logs require a local operator credential; run 'resource-coordinator system auth doctor'.")
        return 1
    if not 0 <= args.tail_bytes <= 262144:
        emit_error("--tail-bytes must be between 0 and 262144.")
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
                    detail = response.text
                    try:
                        body = response.json()
                        if isinstance(body, dict):
                            detail = body.get("message") or body.get("error") or body.get("reason") or detail
                        else:
                            detail = body
                    except ValueError:
                        pass
                    emit_error(f"Log request failed ({response.status_code}): {detail}")
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
        emit_error(f"Failed to follow logs at {args.url}: {exc}")
        return 1


def cmd_logs(args: argparse.Namespace) -> int:
    return asyncio.run(_async_logs(args))


def _redact_recovery_credential(value: Any, token: str) -> Any:
    """Remove the selected bearer secret from server-controlled recovery output."""
    if isinstance(value, str):
        return value.replace("Bearer " + token, "Bearer [REDACTED]").replace(token, "[REDACTED]")
    if isinstance(value, list):
        return [_redact_recovery_credential(item, token) for item in value]
    if isinstance(value, dict):
        return {key: _redact_recovery_credential(item, token) for key, item in value.items()}
    return value


def cmd_recover(args: argparse.Namespace) -> int:
    if getattr(args, "maintenance", False):
        maintenance_args = argparse.Namespace(
            maintenance_command="reconcile", url=args.url, force=args.force, reason=args.reason,
            operation_id=getattr(args, "operation_id", None), session_id=getattr(args, "session_id", None),
            no_resume_miner=getattr(args, "no_resume_miner", False), json=getattr(args, "json", False),
        )
        return cmd_maintenance(maintenance_args)
    if getattr(args, "apply", False):
        recovery_override = os.environ.get("RESOURCE_COORDINATOR_RECOVERY_TOKEN")
        operator_override = os.environ.get("RESOURCE_COORDINATOR_OPERATOR_TOKEN")
        try:
            token = recovery_override or operator_override or load_token(require_secure=True)
        except CredentialError as exc:
            token = None
            credential_error = str(exc)
        else:
            credential_error = None
        if not token:
            result = {"schema_version": 1, "status": "error", "classification": "blocked", "exit_code": 2,
                      "reason_codes": ["operator_credential_unavailable"],
                      "message": credential_error or "Verified automatic recovery requires an operator credential."}
            code = 2
        else:
            try:
                with httpx.Client(timeout=20.0) as client:
                    response = client.post(
                        f"{args.url.rstrip('/')}/_coordinator/recovery/auto",
                        headers={"Authorization": f"Bearer {token}"}, json={},
                    )
                try:
                    body = response.json()
                except ValueError:
                    body = {"status": "error", "reason_code": "invalid_server_response"}
                result = _redact_recovery_credential(body, token)
                if not isinstance(result, dict):
                    result = {"status": "error", "reason_code": "invalid_server_response"}
                if response.status_code == 200 and result.get("status") in {"reconciled", "no_action_required"}:
                    code = 0
                else:
                    result.setdefault("status", "blocked")
                    result.setdefault("classification", "blocked")
                    result.setdefault("exit_code", 2)
                    result["http_status"] = response.status_code
                    code = 2
            except Exception as exc:
                logger.debug("Automatic recovery request failed (%s)", type(exc).__name__)
                result = {"schema_version": 1, "status": "blocked", "classification": "blocked", "exit_code": 2,
                          "reason_codes": ["coordinator_service_unreachable"]}
                code = 2
        if getattr(args, "json", False):
            emit_json(result)
        else:
            from resource_coordinator.presentation import render_recovery_assessment
            render_recovery_assessment(result)
        return code
    if not getattr(args, "force", False):
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"{args.url.rstrip('/')}/_coordinator/recovery/assessment")
            if response.status_code == 200:
                result = response.json()
                code = int(result.get("exit_code", 2))
            else:
                result = {"schema_version": 1, "assessment_mode": "online_read_only",
                          "service_reachable": True, "classification": "blocked", "exit_code": 2,
                          "reason_codes": ["assessment_endpoint_rejected"], "http_status": response.status_code}
                code = 2
        except Exception as exc:
            result = _offline_recovery_assessment(args.url, type(exc).__name__)
            code = 2
        if getattr(args, "json", False):
            emit_json(result)
        else:
            from resource_coordinator.presentation import render_recovery_assessment
            render_recovery_assessment(result)
        return code

    reason = getattr(args, "reason", None)
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 512:
        emit_error("--reason is required with --force and must contain 1 to 512 characters.")
        return 2
    recovery_override = os.environ.get("RESOURCE_COORDINATOR_RECOVERY_TOKEN")
    operator_override = os.environ.get("RESOURCE_COORDINATOR_OPERATOR_TOKEN")
    try:
        token = recovery_override or operator_override or load_token(require_secure=True)
    except CredentialError as exc:
        token = None
        credential_error = str(exc)
    else:
        credential_error = None
    if not token:
        if credential_error:
            message = f"Recovery credential unavailable: {credential_error}. Run 'resource-coordinator system auth doctor'."
        else:
            message = "Recovery requires --force and a valid operator credential; verify upstream has stopped first."
        if getattr(args, "json", False):
            emit_json({"status": "error", "operation": "recover", "message": message})
        else:
            emit_error(message)
        return 1
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(
                f"{args.url.rstrip('/')}/_coordinator/recover",
                params={"resource": args.resource},
                headers={"Authorization": f"Bearer {token}"},
                json={"override": True, "operator": getpass.getuser(), "reason": reason.strip()},
            )
        if response.status_code == 200:
            result = _redact_recovery_credential(response.json(), token)
            if getattr(args, "json", False):
                emit_json(result)
            else:
                from resource_coordinator.presentation import render_recovery_assessment
                render_recovery_assessment({"classification": "operator_required", "status": "recovery_submitted",
                                            "disposition": result})
            return 0
        if response.status_code == 403:
            body = {"message": "Recovery credential was rejected; check configured operator and recovery credentials."}
        else:
            try:
                body = response.json() if response.content else {"message": "Recovery rejected"}
            except ValueError:
                body = {"message": response.text or "Recovery rejected"}
        safe_body = _redact_recovery_credential(body, token)
        if getattr(args, "json", False):
            emit_json({"status": "error", "operation": "recover", "http_status": response.status_code,
                       "detail": safe_body})
        else:
            message = body.get("message", "Recovery rejected") if isinstance(body, dict) else str(body)
            emit_error(f"Recovery rejected ({response.status_code}): {_redact_recovery_credential(message, token)}")
        return 1
    except Exception as exc:
        logger.debug("Recovery request failed (%s)", type(exc).__name__)
        message = f"Failed to connect to coordinator at {args.url}"
        if getattr(args, "json", False):
            emit_json({"status": "error", "operation": "recover", "message": message})
        else:
            emit_error(message)
        return 1


def _offline_recovery_assessment(url: str, error_kind: str) -> dict[str, Any]:
    """Provide local diagnostics only; an offline journal cannot authorize recovery."""
    from resource_coordinator.core.recovery_assessment import read_upgrade_receipt_summary

    journal_status = "unavailable"
    inhibitions: list[str] = []
    unresolved: list[str] = []
    try:
        config = load_config(None)
        state_path = getattr(config.service, "state_persistence_path", "")
        if state_path:
            from resource_coordinator.core.durable_state import StateCodec
            state = StateCodec.load(state_path)
            journal_status = "available"
            inhibitions = sorted(state.inhibitions)
            unresolved = [request.request_id for request in state.requests.values()
                          if request.phase in {"reserved", "possibly_forwarded", "uncertain"}]
    except Exception:
        journal_status = "unavailable"
    upgrade_receipt = read_upgrade_receipt_summary()
    recommended_actions = ["Restore Coordinator connectivity; offline records cannot authorize recovery."]
    if upgrade_receipt.get("status") in {"pending", "recovery_required", "unavailable"}:
        recommended_actions.append("Inspect the interrupted upgrade with 'rc system recovery status'.")
    return {
        "schema_version": 1, "assessment_mode": "offline_diagnostic_only", "service_reachable": False,
        "classification": "blocked", "exit_code": 2, "reason_codes": ["coordinator_service_unreachable"],
        "connection_error": error_kind, "coordinator_url": url, "local_journal_status": journal_status,
        "local_inhibition_resources": inhibitions, "local_unresolved_request_ids": unresolved,
        "upgrade_receipt": upgrade_receipt,
        "upgrade_recovery_command": ("rc system recovery status" if upgrade_receipt.get("status") in
                                     {"pending", "recovery_required", "unavailable"} else None),
        "automatic_recovery_available": False,
        "recommended_actions": recommended_actions,
    }


def cmd_maintenance(args: argparse.Namespace) -> int:
    if getattr(args, "maintenance_command", None) == "status":
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"{args.url.rstrip('/')}/_coordinator/maintenance/status")
            result = response.json()
            code = 0 if result.get("state") == "idle" else 2 if result.get("state") == "recovery_required" else 1
        except Exception as exc:
            result = {"state": "unavailable", "error": type(exc).__name__}
            code = 2
        if getattr(args, "json", False):
            emit_json(result)
        else:
            from resource_coordinator.presentation import render_maintenance_status
            render_maintenance_status(result)
        return code

    reason = getattr(args, "reason", None)
    force = bool(getattr(args, "force", False))
    try:
        with httpx.Client(timeout=5.0) as client:
            status_response = client.get(f"{args.url.rstrip('/')}/_coordinator/maintenance/status")
            if status_response.status_code != 200:
                status = None
            else:
                status = status_response.json()
            if status is None:
                result = {"status": "blocked", "classification": "blocked",
                          "reason": "Coordinator maintenance status could not be authoritatively read",
                          "http_status": status_response.status_code}
                code = 2
            elif not force:
                # The general status endpoint provides readiness and miner state for a useful read-only view.
                general = client.get(f"{args.url.rstrip('/')}/_coordinator/status")
                state = status.get("state")
                classification = ("no_action_required" if state == "idle" else
                                  "operator_required" if state == "recovery_required" else "wait")
                result = {"schema_version": 1, "status": state, "classification": classification,
                          "maintenance": status, "coordinator": general.json() if general.status_code == 200 else None,
                          "recommended_command": ('rc maintenance reconcile -f -r "<reason>"'
                                                  if state == "recovery_required" else None)}
                code = {"idle": 0, "recovery_required": 2}.get(state, 1)
            elif status.get("state") == "idle":
                result = {"status": "no_action_required", "maintenance": status}
                code = 0
            elif status.get("state") != "recovery_required":
                result = {"status": "blocked", "reason": "Maintenance owner must reach recovery_required before override",
                          "maintenance": status}
                code = 1
            elif not isinstance(reason, str) or not reason.strip() or len(reason) > 512:
                result = {"status": "invalid", "reason": "A 1..512 character reason is required with --force"}
                code = 2
            else:
                operation_id = status.get("operation_id")
                session_id = status.get("session_id")
                requested_operation = getattr(args, "operation_id", None)
                requested_session = getattr(args, "session_id", None)
                if requested_operation and requested_operation != operation_id:
                    result = {"status": "stale", "reason": "operation_id does not match current recovery record"}
                    code = 2
                elif requested_session and requested_session != session_id:
                    result = {"status": "stale", "reason": "session_id does not match current recovery record"}
                    code = 2
                elif not operation_id and not session_id:
                    result = {"status": "invalid", "reason": "Recovery record has no resolvable operation or session identity"}
                    code = 2
                else:
                    token = _operator_token()
                    if not token:
                        result = {"status": "unauthorized", "reason": "A protected operator credential is required"}
                        code = 2
                    else:
                        payload = {
                            "operator": getpass.getuser(), "operation_id": operation_id,
                            "session_id": session_id, "restoration_verified": False,
                            "resume_miner": not getattr(args, "no_resume_miner", False),
                            "operator_override": True, "override_reason": reason.strip(),
                            "restoration_evidence": {},
                        }
                        response = client.post(
                            f"{args.url.rstrip('/')}/_coordinator/maintenance/release",
                            headers={"Authorization": f"Bearer {token}"}, json=payload,
                        )
                        result = response.json()
                        disposition = result.get("disposition") if isinstance(result, dict) else None
                        restoration = disposition.get("restoration") if isinstance(disposition, dict) else None
                        valid_ack = (
                            response.status_code == 200
                            and isinstance(result, dict)
                            and result.get("status") == "released"
                            and result.get("session_id") == session_id
                            and isinstance(disposition, dict)
                            and disposition.get("operation_id") == operation_id
                            and disposition.get("session_id") == session_id
                            and disposition.get("operator") == getpass.getuser()
                            and isinstance(disposition.get("miner_restart_eligible"), bool)
                            and isinstance(restoration, dict)
                            and restoration.get("operator_override") is True
                            and restoration.get("independently_verified") is False
                        )
                        if valid_ack:
                            code = 0
                        else:
                            result = {"status": "error", "reason": "Release response did not contain the matching audited disposition",
                                      "http_status": response.status_code}
                            code = 2
    except Exception as exc:
        result = {"status": "unavailable", "reason": f"Maintenance reconciliation failed ({type(exc).__name__})"}
        code = 2
    if getattr(args, "json", False):
        emit_json(result)
    else:
        from resource_coordinator.presentation import render_maintenance_reconcile_result
        render_maintenance_reconcile_result(result)
    return code
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
                data = _redact_recovery_credential(resp.json(), token)
                if getattr(args, "json", False):
                    emit_json(data)
                else:
                    render_result("Safety Recovery", data)
                return 0
            else:
                detail = resp.text
                body = {"message": detail}
                if resp.status_code == 403:
                    detail = "Recovery credential was rejected; check the configured operator and recovery credentials."
                    body = {"message": detail}
                try:
                    if resp.status_code != 403:
                        body = resp.json()
                        detail = body.get("message") or body.get("error") or body.get("reason") or detail if isinstance(body, dict) else body
                except ValueError:
                    body = {"message": detail}
                if getattr(args, "json", False):
                    emit_json(
                        {
                            "status": "error",
                            "operation": "recover",
                            "http_status": resp.status_code,
                            "detail": _redact_recovery_credential(body, token),
                        }
                    )
                else:
                    safe_detail = _redact_recovery_credential(str(detail), token)
                    emit_error(f"Error recovering coordinator ({resp.status_code}): {safe_detail}")
                return 1
    except Exception as exc:
        logger.debug("Recovery request failed (%s)", type(exc).__name__)
        message = f"Failed to connect to coordinator at {args.url}"
        if getattr(args, "json", False):
            emit_json({"status": "error", "operation": "recover", "message": message})
        else:
            emit_error(message)
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

    miner_names = [name for name in config.processes if "miner" in name.casefold() or "krig" in name.casefold()]
    miner_status_info = None
    if gateway_online:
        processes = gateway_data.get("processes") if isinstance(gateway_data.get("processes"), dict) else {}
        selected = next((name for name in miner_names if name in processes), None)
        if selected is None and len(processes) == 1:
            selected = next(iter(processes))
        if selected is not None:
            process = dict(processes[selected]) if isinstance(processes[selected], dict) else {}
            owner_verified = process.get("is_coordinator_owned") is True
            miner_status_info = {"name": selected, **process, "ownership_verified": owner_verified,
                                 "ownership_provenance": "running_coordinator_status"}
    elif miner_names:
        system = build_system(config)
        try:
            if system.miner_adapter:
                status = await system.miner_adapter.status()
                miner_status_info = {**status.to_dict(), "ownership_verified": False,
                                     "ownership_note": "ownership_unverifiable_offline (Coordinator service unreachable)",
                                     "ownership_provenance": "local_read_only_process_observation"}
        finally:
            await system.gateway.close()

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
        emit_json(diag)
    else:
        from resource_coordinator.presentation import render_telemetry_result
        render_telemetry_result(diag)
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
            emit_json(live_result)
        else:
            from resource_coordinator.presentation import render_preflight_result
            render_preflight_result({"status": "ready" if ready else "blocked", **live_result})
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
        emit_json(data)
    else:
        from resource_coordinator.presentation import render_preflight_result
        render_preflight_result({"status": "passed" if passed else "failed", "messages": messages,
                                 "errors": [m for m in messages if m.startswith("ERROR")],
                                 "warnings": [m for m in messages if m.startswith("WARNING")]})
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
        report_data = report.to_dict()
        if getattr(args, "json", False):
            emit_json(report_data)
        else:
            from resource_coordinator.presentation import render_acceptance_result
            render_acceptance_result(report_data)
        return 0 if report.summary.get("all_passed") else 1
    except Exception as exc:
        if getattr(args, "json", False):
            emit_json({"status": "error", "operation": "accept", "message": str(exc)})
        else:
            emit_error(f"Acceptance run failed: {exc}")
        return 1


def cmd_accept(args: argparse.Namespace) -> int:
    return asyncio.run(_async_accept(args))


def cmd_help(args: argparse.Namespace) -> int:
    topic = getattr(args, "topic", None)
    try:
        parse_args(["--help"] if topic is None else [topic, "--help"])
    except SystemExit as exc:
        return 0 if exc.code == 0 else int(exc.code)
    return 0


def cmd_abort(args: argparse.Namespace) -> int:
    token = _operator_token()
    if not token:
        message = "Abort requires a local operator credential; run 'resource-coordinator system auth doctor'."
        if getattr(args, "json", False):
            emit_json({"status": "error", "operation": "abort", "message": message})
        else:
            emit_error(message)
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
                    emit_json(data)
                else:
                    render_result("Emergency Abort", data)
                return 0
            else:
                detail = resp.text
                try:
                    body = resp.json()
                    detail = body.get("message") or body.get("error") or body.get("reason") or detail if isinstance(body, dict) else body
                except ValueError:
                    body = {"message": detail}
                if getattr(args, "json", False):
                    emit_json({"status": "error", "operation": "abort", "http_status": resp.status_code,
                               "detail": body})
                else:
                    emit_error(f"Error triggering coordinator abort ({resp.status_code}): {detail}")
                return 1
    except Exception as exc:
        message = f"Failed to connect to coordinator at {args.url}: {exc}"
        if getattr(args, "json", False):
            emit_json({"status": "error", "operation": "abort", "message": message})
        else:
            emit_error(message)
        return 1


def main(argv: Optional[List[str]] = None) -> None:
    parsed = parse_args(argv)
    set_color_mode(parsed.color)
    args = normalize_dispatch_args(parsed)
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                        stream=sys.stderr)
    logging.getLogger("httpx").setLevel(logging.DEBUG if args.verbose else logging.WARNING)

    operation_id = args.operation_id
    handlers = {
        "status": cmd_status,
        "control.miner.status": cmd_miner, "control.miner.start": cmd_miner,
        "control.miner.stop": cmd_miner, "control.miner.pause": cmd_miner,
        "control.miner.resume": cmd_miner,
        "control.gaming.status": cmd_gaming, "control.gaming.on": cmd_gaming,
        "control.gaming.off": cmd_gaming,
        "service.restart": cmd_lifecycle, "service.shutdown": cmd_lifecycle,
        "service.abort": cmd_abort, "service.recover": cmd_recover, "service.run": cmd_serve,
        "system.setup": _cmd_installation, "system.upgrade": _cmd_installation,
        "system.repair": _cmd_installation, "system.teardown": _cmd_installation,
        "system.recovery.status": _cmd_installation, "system.recovery.diagnose": _cmd_installation,
        "system.recovery.restore": _cmd_installation, "system.recovery.resume": _cmd_installation,
        "system.recovery.reconcile": _cmd_installation,
        "system.startup.status": _cmd_installation, "system.startup.install": _cmd_installation,
        "system.startup.enable": _cmd_installation, "system.startup.disable": _cmd_installation,
        "system.startup.repair": _cmd_installation, "system.startup.uninstall": _cmd_installation,
        "system.auth.doctor": cmd_auth, "system.auth.repair": cmd_auth,
        "system.auth.reinitialize": cmd_auth,
        "check.health": _cmd_installation, "check.telemetry": cmd_diagnose,
        "check.preflight": cmd_preflight, "check.accept": cmd_accept,
        "maintenance.status": cmd_maintenance, "maintenance.reconcile": cmd_maintenance,
        "config.show": cmd_config, "config.validate": cmd_config,
        "logs": cmd_logs, "help": cmd_help,
    }
    handler = handlers.get(operation_id)
    if handler is None:
        emit_error(f"Unsupported Resource Coordinator operation: {operation_id}")
        sys.exit(2)
    try:
        code = handler(args)
    except Exception as exc:
        if args.verbose:
            logger.exception("Operation %s failed", operation_id)
        else:
            logger.error("Operation %s failed: %s", operation_id, exc)
        if getattr(args, "json", False):
            emit_json({"status": "error", "operation": operation_id, "message": str(exc)})
        else:
            emit_error(f"Resource Coordinator {operation_id} failed: {exc}")
        code = 1
    sys.exit(code)


def _cmd_installation(args: argparse.Namespace) -> int:
    from resource_coordinator.installation import handle_installation_command

    return handle_installation_command(args)


if __name__ == "__main__":
    main()
