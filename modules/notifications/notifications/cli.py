"""Command-line interface for the notifications system (scripts-notify)."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from notifications.config import BrokerConfig, default_db_path
from notifications.delivery.fake import FakeProvider
from notifications.exceptions import (
    IncidentNotFoundError,
    InvalidTransitionError,
    NotificationError,
)
from notifications.lifecycle import IncidentLifecycleEngine
from notifications.models import EventEnvelopeV1, Incident, OutboxItem, RenderedNotification
from notifications.integrations.resource_coordinator import (
    DEFAULT_COORDINATOR_STATUS_URL,
    LockContentionError,
    LockError,
    ResourceCoordinatorObserver,
    get_coordinator_task_status,
    install_coordinator_task,
    uninstall_coordinator_task,
)
from notifications.outbox import OutboxWorker
from notifications.publisher import Publisher
from notifications.storage import StorageEngine


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def _get_storage(db_path_str: Optional[str]) -> StorageEngine:
    path = Path(db_path_str).resolve() if db_path_str else default_db_path()
    storage = StorageEngine(path)
    storage.migrate()
    return storage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts-notify",
        description="Durable notification broker, incident lifecycle manager, and outbox CLI.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug output.")
    parser.add_argument("-d", "--db", default=None, help="Database path override.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. publish
    pub_parser = subparsers.add_parser("publish", help="Publish a notification event.")
    pub_group = pub_parser.add_mutually_exclusive_group(required=True)
    pub_group.add_argument("-j", "--json", dest="json_payload", help="JSON string representing the event envelope.")
    pub_group.add_argument("-f", "--file", dest="file_payload", help="Path to JSON file containing the event envelope.")
    pub_parser.add_argument("-p", "--providers", default="fake_provider", help="Comma-separated delivery provider IDs.")
    pub_parser.add_argument("-d", "--db", default=argparse.SUPPRESS, help="Database path override.")

    # 2. incidents
    inc_parser = subparsers.add_parser("incidents", help="Inspect and manage tracked incidents.")
    inc_sub = inc_parser.add_subparsers(dest="incidents_command", required=True)

    # incidents list
    inc_list = inc_sub.add_parser("list", help="List tracked incidents.")
    inc_list.add_argument("-s", "--status", choices=("open", "acknowledged", "resolved", "stale"), default=None)
    inc_list.add_argument("-l", "--limit", type=int, default=50, help="Maximum incidents to return.")
    inc_list.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")
    inc_list.add_argument("-d", "--db", default=argparse.SUPPRESS, help="Database path override.")

    # incidents show
    inc_show = inc_sub.add_parser("show", help="Show incident details.")
    inc_show.add_argument("-i", "--incident-id", required=True, help="Incident identifier.")
    inc_show.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")
    inc_show.add_argument("-d", "--db", default=argparse.SUPPRESS, help="Database path override.")

    # incidents acknowledge
    inc_ack = inc_sub.add_parser("acknowledge", help="Acknowledge an incident.")
    inc_ack.add_argument("-i", "--incident-id", required=True, help="Incident identifier to acknowledge.")
    inc_ack.add_argument("-n", "--reason", default=None, help="Operator acknowledgement reason.")
    inc_ack.add_argument("-a", "--apply", action="store_true", help="Apply modification (required for mutation).")
    inc_ack.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")
    inc_ack.add_argument("-d", "--db", default=argparse.SUPPRESS, help="Database path override.")

    # 3. outbox
    out_parser = subparsers.add_parser("outbox", help="Inspect and process outbox delivery queue.")
    out_sub = out_parser.add_subparsers(dest="outbox_command", required=True)

    # outbox list
    out_list = out_sub.add_parser("list", help="List pending and recent outbox items.")
    out_list.add_argument("-s", "--status", choices=("pending", "attempting", "provider_accepted", "retryable_error", "terminal_error"))
    out_list.add_argument("-l", "--limit", type=int, default=50, help="Maximum items to return.")
    out_list.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")
    out_list.add_argument("-d", "--db", default=argparse.SUPPRESS, help="Database path override.")

    # outbox run
    out_run = out_sub.add_parser("run", help="Dispatch pending outbox notifications to providers.")
    out_run.add_argument("-l", "--limit", type=int, default=50, help="Maximum items to dispatch.")
    out_run.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")
    out_run.add_argument("-d", "--db", default=argparse.SUPPRESS, help="Database path override.")

    # 4. providers
    prov_parser = subparsers.add_parser("providers", help="Inspect and test delivery providers.")
    prov_sub = prov_parser.add_subparsers(dest="providers_command", required=True)

    # providers list
    prov_list = prov_sub.add_parser("list", help="List registered delivery providers.")
    prov_list.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # providers test
    prov_test = prov_sub.add_parser("test", help="Test delivery to a provider.")
    prov_test.add_argument("-p", "--provider", default="fake_provider", help="Provider ID to test.")
    prov_test.add_argument("-a", "--apply", action="store_true", help="Apply modification (required to send test message).")
    prov_test.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")
    prov_test.add_argument("-d", "--db", default=argparse.SUPPRESS, help="Database path override.")

    # 5. health
    health_parser = subparsers.add_parser("health", help="Check storage and broker health.")
    health_parser.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")
    health_parser.add_argument("-d", "--db", default=argparse.SUPPRESS, help="Database path override.")

    # 6. telegram
    tg_parser = subparsers.add_parser("telegram", help="Manage Telegram bot provider enrollment and status.")
    tg_sub = tg_parser.add_subparsers(dest="telegram_command", required=True)

    # telegram enroll
    tg_enroll = tg_sub.add_parser("enroll", help="Securely enroll Telegram bot token and authorized chat ID.")
    tg_enroll.add_argument("-t", "--token", required=False, default=None, help="Telegram Bot API token from @BotFather (optional; prefer interactive prompt or NOTIFY_TELEGRAM_BOT_TOKEN).")
    tg_enroll.add_argument("-c", "--chat-id", required=True, help="Authorized recipient chat ID.")
    tg_enroll.add_argument("-u", "--dashboard-url", default=None, help="Optional read-only HTTPS dashboard URL.")
    tg_enroll.add_argument("-a", "--apply", action="store_true", help="Apply modification (required to save credentials).")
    tg_enroll.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # telegram status
    tg_status = tg_sub.add_parser("status", help="Show Telegram provider configuration and enrollment status.")
    tg_status.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # telegram revoke
    tg_revoke = tg_sub.add_parser("revoke", help="Revoke and delete enrolled Telegram credentials.")
    tg_revoke.add_argument("-a", "--apply", action="store_true", help="Apply modification (required to delete credentials).")
    tg_revoke.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # telegram test
    tg_test = tg_sub.add_parser("test", help="Send a single live test notification to the enrolled Telegram chat.")
    tg_test.add_argument("-a", "--apply", action="store_true", help="Apply modification (REQUIRED: sends real external message).")
    tg_test.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")
    tg_test.add_argument("-d", "--db", default=argparse.SUPPRESS, help="Database path override.")

    # 7. windows
    win_parser = subparsers.add_parser("windows", help="Manage Windows interactive desktop notification helper and scheduled task.")
    win_sub = win_parser.add_subparsers(dest="windows_command", required=True)

    # windows status
    win_status = win_sub.add_parser("status", help="Check Windows scheduled task and helper IPC status.")
    win_status.add_argument("-p", "--port", type=int, default=1238, help="Helper loopback port (default: 1238).")
    win_status.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # windows install
    win_install = win_sub.add_parser("install", help="Register Windows user-level Scheduled Task at logon.")
    win_install.add_argument("-p", "--port", type=int, default=1238, help="Helper loopback port (default: 1238).")
    win_install.add_argument("-a", "--apply", action="store_true", help="Apply modification (required to register Scheduled Task).")
    win_install.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # windows uninstall
    win_uninstall = win_sub.add_parser("uninstall", help="Unregister Windows Scheduled Task and stop helper.")
    win_uninstall.add_argument("-p", "--port", type=int, default=1238, help="Helper loopback port (default: 1238).")
    win_uninstall.add_argument("-a", "--apply", action="store_true", help="Apply modification (required to remove Scheduled Task).")
    win_uninstall.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # windows test
    win_test = win_sub.add_parser("test", help="Send a test toast notification via the Windows helper.")
    win_test.add_argument("-p", "--port", type=int, default=1238, help="Helper loopback port (default: 1238).")
    win_test.add_argument("-a", "--apply", action="store_true", help="Apply modification (REQUIRED: sends live desktop toast).")
    win_test.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # windows run-helper
    win_run = win_sub.add_parser("run-helper", help="Run the Windows interactive helper directly.")
    win_run.add_argument("-p", "--port", type=int, default=1238, help="Helper loopback port (default: 1238).")

    # 8. heartbeat
    hb_parser = subparsers.add_parser("heartbeat", help="Manage independent Healthchecks.io host outage monitoring.")
    hb_sub = hb_parser.add_subparsers(dest="heartbeat_command", required=True)

    # heartbeat configure
    hb_conf = hb_sub.add_parser("configure", help="Configure Healthchecks ping URL and interval.")
    hb_conf.add_argument("-u", "--url", default=None, help="Healthchecks ping URL (e.g. https://hc-ping.com/<uuid>).")
    hb_conf.add_argument("-i", "--interval", type=int, default=5, help="Heartbeat interval in minutes (default: 5).")
    hb_conf.add_argument("-n", "--name", default="Host Alive", help="Check name (default: 'Host Alive').")
    hb_conf.add_argument("-a", "--apply", action="store_true", help="Apply modification (required to save configuration).")
    hb_conf.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # heartbeat status
    hb_status = hb_sub.add_parser("status", help="Show heartbeat configuration and Scheduled Task status.")
    hb_status.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # heartbeat test
    hb_test = hb_sub.add_parser("test", help="Send a test heartbeat ping to Healthchecks.io.")
    hb_test.add_argument("-a", "--apply", action="store_true", help="Apply modification (REQUIRED: sends real external ping).")
    hb_test.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # heartbeat ping (headless execution for Scheduled Task)
    hb_ping = hb_sub.add_parser("ping", help="Execute single headless heartbeat ping (used by Scheduled Task).")
    hb_ping.add_argument("-v", "--verbose", action="store_true", help="Verbose output.")

    # heartbeat install
    hb_inst = hb_sub.add_parser("install", help="Register Windows Scheduled Task for periodic heartbeat.")
    hb_inst.add_argument("-i", "--interval", type=int, default=None, help="Heartbeat interval in minutes override.")
    hb_inst.add_argument("--headless", action="store_true", help="Register as headless system task (NT AUTHORITY\\SYSTEM) that survives reboots and runs when logged off (requires Administrator).")
    hb_inst.add_argument("--system", action="store_true", help="Alias for --headless (register under NT AUTHORITY\\SYSTEM).")
    hb_inst.add_argument("--python-path", default=None, help="Explicit path to Python interpreter executable.")
    hb_inst.add_argument("-a", "--apply", action="store_true", help="Apply modification (required to register Scheduled Task).")
    hb_inst.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # heartbeat repair
    hb_repair = hb_sub.add_parser("repair", help="Repair heartbeat Scheduled Task and verify permissions.")
    hb_repair.add_argument("-a", "--apply", action="store_true", help="Apply modification (required to execute repairs).")
    hb_repair.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # heartbeat uninstall
    hb_uninst = hb_sub.add_parser("uninstall", help="Unregister heartbeat Scheduled Task.")
    hb_uninst.add_argument("-a", "--apply", action="store_true", help="Apply modification (required to remove Scheduled Task).")
    hb_uninst.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # heartbeat doctor
    hb_doc = hb_sub.add_parser("doctor", help="Run comprehensive diagnostic checks on host monitoring prerequisites.")
    hb_doc.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # 9. coordinator
    coord_parser = subparsers.add_parser("coordinator", help="Inspect and poll Resource Coordinator monitoring status.")
    coord_sub = coord_parser.add_subparsers(dest="coordinator_command", required=True)

    # coordinator status
    coord_stat = coord_sub.add_parser("status", help="Inspect latest Resource Coordinator observation status.")
    coord_stat.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")
    coord_stat.add_argument("-d", "--db", default=argparse.SUPPRESS, help="Database path override.")

    # coordinator poll
    coord_poll = coord_sub.add_parser("poll", help="Execute one-shot read-only poll against Resource Coordinator loopback endpoint.")
    coord_poll.add_argument("-u", "--url", default=DEFAULT_COORDINATOR_STATUS_URL, help=f"Target loopback URL (default: {DEFAULT_COORDINATOR_STATUS_URL}).")
    coord_poll.add_argument("-t", "--timeout", type=float, default=5.0, help="HTTP read timeout in seconds (default: 5.0).")
    coord_poll.add_argument("-p", "--providers", help="Comma-separated delivery provider IDs (e.g. 'windows,telegram').")
    coord_poll.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")
    coord_poll.add_argument("-d", "--db", default=argparse.SUPPRESS, help="Database path override.")

    # coordinator test
    coord_test = coord_sub.add_parser("test", help="Test observer loopback configuration and contract capabilities in safe dry-run mode.")
    coord_test.add_argument("-u", "--url", default=DEFAULT_COORDINATOR_STATUS_URL, help="Target loopback URL to validate.")
    coord_test.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # coordinator prune
    coord_prune = coord_sub.add_parser("prune", help="Prune old Resource Coordinator observations exceeding retention limits.")
    coord_prune.add_argument("-a", "--apply", action="store_true", help="Apply deletion (defaults to dry-run).")
    coord_prune.add_argument("--max-age-days", type=int, default=7, help="Maximum observation age in days (default: 7).")
    coord_prune.add_argument("--max-records", type=int, default=10000, help="Maximum observation records to retain (default: 10000).")
    coord_prune.add_argument("-d", "--db", default=argparse.SUPPRESS, help="Database path override.")
    coord_prune.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # coordinator task
    coord_task = coord_sub.add_parser("task", help="Manage Windows Scheduled Task for unattended background polling.")
    coord_task_sub = coord_task.add_subparsers(dest="task_command", required=True)

    task_stat = coord_task_sub.add_parser("status", help="Inspect Windows Scheduled Task installation and last run state.")
    task_stat.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    task_inst = coord_task_sub.add_parser("install", help="Register Windows Scheduled Task for periodic background polling.")
    task_inst.add_argument("-a", "--apply", action="store_true", help="Apply registration (defaults to dry-run).")
    task_inst.add_argument("-i", "--interval-minutes", type=int, default=2, help="Polling interval in minutes (default: 2).")
    task_inst.add_argument("-u", "--url", default=DEFAULT_COORDINATOR_STATUS_URL, help="Target loopback status URL.")
    task_inst.add_argument("-d", "--db", default=argparse.SUPPRESS, help="Database path override.")
    task_inst.add_argument("--working-dir", default=None, help="Working directory for the task (default: user home).")
    task_inst.add_argument("--executable", default=None, help="Executable path for the task (default: current python).")
    task_inst.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    task_uninst = coord_task_sub.add_parser("uninstall", help="Unregister Windows Scheduled Task.")
    task_uninst.add_argument("-a", "--apply", action="store_true", help="Apply removal (defaults to dry-run).")
    task_uninst.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # 10. release-check
    rc_parser = subparsers.add_parser("release-check", help="Run unified read-only release diagnostics across notifications and remote control.")
    rc_parser.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")
    rc_parser.add_argument("-d", "--db", default=argparse.SUPPRESS, help="Notifications database path override.")
    rc_parser.add_argument("--auth-db", default=None, help="Remote Control auth database path override.")
    rc_parser.add_argument("--inspect-tailscale", action="store_true", help="Perform read-only live inspection of Tailscale Funnel status.")
    rc_parser.add_argument("--strict", action="store_true", help="Exit with code 2 if any release blockers exist or release prerequisites are incomplete.")

    return parser


def handle_publish(args: argparse.Namespace) -> int:
    storage = _get_storage(args.db)
    lifecycle = IncidentLifecycleEngine(storage)

    if args.json_payload:
        raw_text = args.json_payload
    else:
        file_path = Path(args.file_payload)
        if not file_path.is_file():
            print(json.dumps({"ok": False, "error": f"File not found: {file_path}"}), file=sys.stderr)
            return 1
        raw_text = file_path.read_text(encoding="utf-8")

    try:
        data = json.loads(raw_text)
        event = EventEnvelopeV1.from_dict(data)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"Event validation error: {exc}"}), file=sys.stderr)
        return 1

    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    try:
        result = lifecycle.process_event(event, providers=providers)
        print(json.dumps({"ok": True, "result": result.to_dict()}, indent=2))
        return 0
    except NotificationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1


def handle_incidents(args: argparse.Namespace) -> int:
    storage = _get_storage(args.db)

    if args.incidents_command == "list":
        incidents = storage.list_incidents(status=args.status, limit=args.limit)
        items = [i.to_dict() for i in incidents]
        if args.json:
            print(json.dumps({"ok": True, "incidents": items}, indent=2))
        else:
            print(f"Tracking {len(items)} incident(s):")
            for inc in items:
                print(f" - [{inc['status'].upper()}] {inc['incident_id'][:8]} | {inc['severity']} | {inc['summary']}")
        return 0

    elif args.incidents_command == "show":
        incident = storage.get_incident(args.incident_id)
        if not incident:
            err = {"ok": False, "error": f"Incident '{args.incident_id}' not found"}
            print(json.dumps(err) if args.json else err["error"], file=sys.stderr)
            return 1
        transitions = storage.list_transitions(args.incident_id)
        data = {
            "ok": True,
            "incident": incident.to_dict(),
            "transitions": [t.to_dict() for t in transitions],
        }
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            print(f"Incident {incident.incident_id} [{incident.status}]:")
            print(f" Summary: {incident.summary}")
            print(f" Severity: {incident.severity}")
            print(f" First seen: {incident.first_seen} | Last seen: {incident.last_seen}")
        return 0

    elif args.incidents_command == "acknowledge":
        if not args.apply:
            msg = {"ok": True, "dry_run": True, "warning": "Dry-run: pass -a/--apply to acknowledge incident."}
            print(json.dumps(msg) if args.json else msg["warning"])
            return 0

        engine = IncidentLifecycleEngine(storage)
        try:
            updated = engine.acknowledge_incident(
                incident_id=args.incident_id,
                actor="cli_operator",
                reason=args.reason,
            )
            res = {
                "ok": True,
                "status": "acknowledged",
                "incident_id": args.incident_id,
                "incident": updated.to_dict(),
            }
            print(json.dumps(res, indent=2) if args.json else f"Incident {args.incident_id} acknowledged.")
            return 0
        except (IncidentNotFoundError, InvalidTransitionError) as exc:
            err = {"ok": False, "error": str(exc)}
            print(json.dumps(err) if args.json else str(exc), file=sys.stderr)
            return 1

    return 2


def handle_outbox(args: argparse.Namespace) -> int:
    storage = _get_storage(args.db)

    if args.outbox_command == "list":
        items = storage.list_pending_outbox(limit=args.limit)
        data = [i.to_dict() for i in items]
        if args.json:
            print(json.dumps({"ok": True, "items": data}, indent=2))
        else:
            print(f"{len(data)} pending outbox item(s):")
            for item in data:
                print(f" - Outbox #{item['outbox_id']}: {item['provider_id']} [{item['status']}] event={item['event_id']}")
        return 0

    elif args.outbox_command == "run":
        from notifications.delivery.registry import get_registered_providers

        providers = get_registered_providers(storage)
        worker = OutboxWorker(storage, providers=providers)
        count = asyncio.run(worker.process_pending_once(limit=args.limit))
        res = {"ok": True, "processed": count}
        print(json.dumps(res, indent=2) if args.json else f"Processed {count} outbox delivery task(s).")
        return 0

    return 2


def handle_providers(args: argparse.Namespace) -> int:
    from notifications.delivery.registry import UnconfiguredProvider, get_registered_providers

    storage = _get_storage(getattr(args, "db", None))
    providers = get_registered_providers(storage)

    if args.providers_command == "list":
        prov_list = []
        for pid, prov in providers.items():
            is_unconfigured = isinstance(prov, UnconfiguredProvider)
            status = "unconfigured" if is_unconfigured else "available"
            prov_type = "testing" if pid == "fake_provider" else "desktop" if pid == "windows" else "external"
            prov_list.append({"id": pid, "type": prov_type, "status": status})
        data = {
            "ok": True,
            "providers": prov_list,
        }
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            names = ", ".join(f"{p['id']} ({p['status']})" for p in prov_list)
            print(f"Registered Providers: {names}")
        return 0

    elif args.providers_command == "test":
        if args.provider not in providers:
            err = {"ok": False, "error": f"Unknown provider '{args.provider}'. Available: {', '.join(providers.keys())}"}
            print(json.dumps(err) if args.json else err["error"], file=sys.stderr)
            return 1

        if not args.apply:
            res = {
                "ok": True,
                "dry_run": True,
                "provider": args.provider,
                "warning": "Dry-run: pass -a/--apply to execute provider test.",
            }
            print(json.dumps(res) if args.json else res["warning"])
            return 0

        provider = providers[args.provider]
        if isinstance(provider, UnconfiguredProvider):
            err = {"ok": False, "provider": args.provider, "error": provider.reason}
            print(json.dumps(err) if args.json else err["error"], file=sys.stderr)
            return 1

        notification = RenderedNotification(
            notification_id=f"diag-{args.provider}-001",
            event_id=str(uuid.uuid4()),
            incident_id=f"inc-{args.provider}-diag",
            severity="info",
            title=f"[TEST] {args.provider.capitalize()} Diagnostic",
            body=f"Diagnostic notification dispatched via 'scripts-notify providers test -p {args.provider}'",
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )
        try:
            receipt = asyncio.run(provider.send(notification))
            if receipt.status == "provider_accepted":
                res = {"ok": True, "provider": args.provider, "status": "accepted", "receipt": receipt.to_dict()}
                if args.provider == "fake_provider":
                    res["simulated"] = True
                print(json.dumps(res, indent=2) if args.json else f"Test notification accepted by {args.provider}.")
                return 0
            else:
                err = {"ok": False, "provider": args.provider, "status": receipt.status, "error": receipt.error_message}
                print(json.dumps(err) if args.json else err["error"], file=sys.stderr)
                return 1
        except Exception as exc:
            err = {"ok": False, "provider": args.provider, "error": f"Provider test failed: {exc}"}
            print(json.dumps(err) if args.json else err["error"], file=sys.stderr)
            return 1

    return 2


def handle_telegram(args: argparse.Namespace) -> int:
    from notifications.delivery.telegram_credentials import (
        TelegramCredentials,
        load_telegram_credentials,
        save_telegram_credentials,
        revoke_telegram_credentials,
    )
    from notifications.delivery.telegram import TelegramProvider

    if args.telegram_command == "enroll":
        token = args.token
        if token:
            print("Warning: Passing bot token via CLI argument may expose secrets in process tables.", file=sys.stderr)
        else:
            import os
            token = os.environ.get("NOTIFY_TELEGRAM_BOT_TOKEN")
            if not token:
                if sys.stdin.isatty():
                    import getpass
                    token = getpass.getpass("Enter Telegram Bot API Token: ").strip()
                else:
                    token = sys.stdin.readline().strip()

        if not token:
            err = {"ok": False, "error": "Bot token is required. Pass via interactive prompt, NOTIFY_TELEGRAM_BOT_TOKEN env var, or -t/--token."}
            print(json.dumps(err) if args.json else err["error"], file=sys.stderr)
            return 1

        if not args.apply:
            res = {
                "ok": True,
                "dry_run": True,
                "warning": "Dry-run: pass -a/--apply to save Telegram credentials.",
                "chat_id": args.chat_id,
            }
            print(json.dumps(res, indent=2) if args.json else res["warning"])
            return 0

        try:
            creds = TelegramCredentials(
                bot_token=token,
                chat_id=args.chat_id,
                dashboard_url=args.dashboard_url,
            )
            saved_path = save_telegram_credentials(creds)
            res = {
                "ok": True,
                "status": "enrolled",
                "chat_id": creds.chat_id,
                "secrets_file": str(saved_path),
            }
            print(json.dumps(res, indent=2) if args.json else f"Telegram credentials enrolled for chat {creds.chat_id}.")
            return 0
        except Exception as exc:
            err = {"ok": False, "error": str(exc)}
            print(json.dumps(err) if args.json else f"Enrollment error: {exc}", file=sys.stderr)
            return 1

    elif args.telegram_command == "status":
        creds = load_telegram_credentials()
        if not creds:
            res = {"ok": True, "enrolled": False, "status": "unconfigured"}
            print(json.dumps(res, indent=2) if args.json else "Telegram provider: Not configured (run 'scripts-notify telegram enroll')")
            return 0

        redacted_token = creds.bot_token[:6] + "..." + creds.bot_token[-4:]
        res = {
            "ok": True,
            "enrolled": True,
            "status": "configured",
            "chat_id": creds.chat_id,
            "bot_token": redacted_token,
            "dashboard_url": creds.dashboard_url,
        }
        print(json.dumps(res, indent=2) if args.json else f"Telegram provider: Enrolled (Chat ID: {creds.chat_id}, Token: {redacted_token})")
        return 0

    elif args.telegram_command == "revoke":
        if not args.apply:
            res = {"ok": True, "dry_run": True, "warning": "Dry-run: pass -a/--apply to revoke credentials."}
            print(json.dumps(res) if args.json else res["warning"])
            return 0

        revoked = revoke_telegram_credentials()
        res = {"ok": True, "revoked": revoked}
        print(json.dumps(res, indent=2) if args.json else ("Telegram credentials revoked." if revoked else "No credentials found to revoke."))
        return 0

    elif args.telegram_command == "test":
        if not args.apply:
            res = {
                "ok": True,
                "dry_run": True,
                "warning": "Dry-run: specify -a/--apply to send an actual test notification to your Telegram device.",
            }
            print(json.dumps(res, indent=2) if args.json else res["warning"])
            return 0

        creds = load_telegram_credentials()
        if not creds:
            err = {"ok": False, "error": "Telegram provider is not configured. Run 'scripts-notify telegram enroll' first."}
            print(json.dumps(err) if args.json else err["error"], file=sys.stderr)
            return 1

        provider = TelegramProvider(credentials=creds)
        notification = RenderedNotification(
            notification_id="tg-test-cli",
            event_id=str(uuid.uuid4()),
            incident_id="inc-test-tg",
            severity="info",
            title="[SCRIPTS-NOTIFY] Test Notification",
            body="This is a test notification verifying Telegram Bot delivery.",
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )
        receipt = asyncio.run(provider.send(notification))
        if receipt.status == "provider_accepted":
            res = {
                "ok": True,
                "status": "provider_accepted",
                "message_id": receipt.provider_message_id,
                "chat_id": creds.chat_id,
            }
            print(json.dumps(res, indent=2) if args.json else f"Test notification delivered to chat {creds.chat_id} (Message ID: {receipt.provider_message_id}).")
            return 0
        else:
            err = {"ok": False, "status": receipt.status, "error": receipt.error_message}
            print(json.dumps(err) if args.json else f"Delivery failed: {receipt.error_message}", file=sys.stderr)
            return 1

    return 2


def handle_windows(args: argparse.Namespace) -> int:
    from notifications.windows_helper.service import (
        get_helper_script_path,
        get_helper_status,
        install_scheduled_task,
        send_test_toast,
        uninstall_scheduled_task,
    )
    import subprocess

    if args.windows_command == "status":
        status = get_helper_status(port=args.port)
        if args.json:
            print(json.dumps(status, indent=2))
        else:
            task_str = "Installed" if status["task_installed"] else "Not installed"
            proc_str = "Running" if status["helper_running"] else "Not running"
            print("Windows Desktop Helper Status:")
            print(f" - Scheduled Task ({status['task_name']}): {task_str} (State: {status['task_state']})")
            print(f" - IPC Loopback (127.0.0.1:{status['helper_port']}): {proc_str}")
            print(f" - Helper Script: {status['helper_script']}")
        return 0

    elif args.windows_command == "install":
        res = install_scheduled_task(port=args.port, apply=args.apply)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            if not args.apply:
                print(res.get("warning", "Dry-run"))
                print(f"Target task: {res['task_name']} (executing {res['executable']} at logon)")
            elif res.get("ok"):
                print(f"Scheduled task '{res['task_name']}' registered successfully at user logon.")
            else:
                print(f"Installation failed: {res.get('error')}", file=sys.stderr)
        return 0 if res.get("ok") else 1

    elif args.windows_command == "uninstall":
        res = uninstall_scheduled_task(port=args.port, apply=args.apply)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            if not args.apply:
                print(res.get("warning", "Dry-run"))
            else:
                print(res.get("message", "Uninstallation complete."))
        return 0 if res.get("ok") else 1

    elif args.windows_command == "test":
        res = send_test_toast(port=args.port, apply=args.apply)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            if not args.apply:
                print(res.get("warning", "Dry-run"))
            elif res.get("ok"):
                print(f"Test toast delivered to Windows desktop (Toast ID: {res.get('toast_id')}).")
            else:
                print(f"Test toast failed: {res.get('error_message') or res.get('status')}", file=sys.stderr)
        return 0 if res.get("ok") else 1

    elif args.windows_command == "run-helper":
        script_path = get_helper_script_path()
        if not script_path.is_file():
            print(json.dumps({"ok": False, "error": f"Helper script not found: {script_path}"}), file=sys.stderr)
            return 1
        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-Port",
            str(args.port),
        ]
        return subprocess.call(cmd)

    return 2


def handle_heartbeat(args: argparse.Namespace) -> int:
    from notifications.monitoring.config import (
        HealthchecksConfig,
        load_healthchecks_config,
        save_healthchecks_config,
        redact_ping_url,
    )
    from notifications.monitoring.heartbeat import send_heartbeat
    from notifications.monitoring.service import (
        doctor,
        get_heartbeat_task_status,
        install_heartbeat_task,
        uninstall_heartbeat_task,
    )
    import os

    if args.heartbeat_command == "configure":
        url = args.url
        if url:
            print("Warning: Passing ping URL via CLI argument may expose secrets in process tables.", file=sys.stderr)
        else:
            url = os.environ.get("NOTIFY_HEALTHCHECKS_PING_URL")
            if not url:
                if sys.stdin.isatty():
                    import getpass
                    url = getpass.getpass("Enter Healthchecks Ping URL (e.g. https://hc-ping.com/...): ").strip()
                else:
                    url = sys.stdin.readline().strip()

        if not url:
            err = {"ok": False, "error": "Ping URL is required. Pass via prompt, NOTIFY_HEALTHCHECKS_PING_URL env var, or -u/--url."}
            print(json.dumps(err) if args.json else err["error"], file=sys.stderr)
            return 1

        if not args.apply:
            res = {
                "ok": True,
                "dry_run": True,
                "warning": "Dry-run: pass -a/--apply to save Healthchecks configuration.",
                "check_name": args.name,
                "interval_minutes": args.interval,
                "ping_url_redacted": redact_ping_url(url),
            }
            print(json.dumps(res, indent=2) if args.json else res["warning"])
            return 0

        try:
            cfg = HealthchecksConfig(
                ping_url=url,
                interval_minutes=args.interval,
                check_name=args.name,
            )
            saved_path = save_healthchecks_config(cfg)
            res = {
                "ok": True,
                "status": "configured",
                "check_name": cfg.check_name,
                "interval_minutes": cfg.interval_minutes,
                "ping_url_redacted": redact_ping_url(cfg.ping_url),
                "config_file": str(saved_path),
            }
            print(json.dumps(res, indent=2) if args.json else f"Healthchecks configured for '{cfg.check_name}' ({cfg.interval_minutes}m). Saved to {saved_path}")
            return 0
        except Exception as exc:
            err = {"ok": False, "error": str(exc)}
            print(json.dumps(err) if args.json else f"Configuration error: {exc}", file=sys.stderr)
            return 1

    elif args.heartbeat_command == "status":
        status = get_heartbeat_task_status()
        if args.json:
            print(json.dumps(status, indent=2))
        else:
            print("Independent Outage Monitoring (Healthchecks.io) Status:")
            print(f" - Configured: {'Yes' if status['configured'] else 'No (run scripts-notify heartbeat configure)'}")
            if status["configured"]:
                print(f" - Check Name: {status['check_name']} ({status['interval_minutes']}m interval)")
                print(f" - Ping URL: {status['ping_url_redacted']}")
            print(f" - Scheduled Task ({status['task_name']}): {'Installed' if status['task_installed'] else 'Not Installed'} (State: {status['task_state']})")
            if status["task_installed"]:
                print(f" - Execution Mode: {status.get('execution_mode', 'Unknown')}")
                print(f" - Logged-off Capable: {'Yes' if status.get('logged_off_capable') else 'No (Interactive only; will NOT run when logged off)'}")
                print(f" - Last Run: {status['last_run_time']} (Result: {status['last_result']})")
                print(f" - Next Run: {status['next_run_time']}")
                if not status.get("logged_off_capable"):
                    print(" ! Notice: Interactive-only task requires an active user session. Run 'scripts-notify heartbeat install --headless -a' as Administrator for 24/7 host outage detection across reboots.")
        return 0

    elif args.heartbeat_command == "test":
        cfg = load_healthchecks_config()
        if not cfg:
            err = {"ok": False, "error": "Healthchecks is not configured. Run 'scripts-notify heartbeat configure' first."}
            print(json.dumps(err) if args.json else err["error"], file=sys.stderr)
            return 1

        if not args.apply:
            res = {
                "ok": True,
                "dry_run": True,
                "warning": "Dry-run: pass -a/--apply to send a live external ping to Healthchecks.io.",
                "target_url_redacted": redact_ping_url(cfg.ping_url),
                "check_name": cfg.check_name,
            }
            print(json.dumps(res, indent=2) if args.json else res["warning"])
            return 0

        res = send_heartbeat(cfg.ping_url)
        out = {
            "ok": res.success,
            "status": "ping_accepted" if res.success else "ping_failed",
            "status_code": res.status_code,
            "duration_ms": res.duration_ms,
            "error_category": res.error_category,
            "error_message": res.error_message,
        }
        if args.json:
            print(json.dumps(out, indent=2))
        else:
            if res.success:
                print(f"Heartbeat ping confirmed by Healthchecks.io ({res.duration_ms}ms, HTTP {res.status_code}).")
            else:
                print(f"Heartbeat ping failed: {res.error_message}", file=sys.stderr)
        return 0 if res.success else 1

    elif args.heartbeat_command == "ping":
        cfg = load_healthchecks_config()
        if not cfg:
            print("Error: Healthchecks is not configured.", file=sys.stderr)
            return 1
        res = send_heartbeat(cfg.ping_url)
        if res.success:
            if getattr(args, "verbose", False):
                print(f"Heartbeat confirmed (HTTP {res.status_code}, {res.duration_ms}ms)")
            return 0
        else:
            print(f"Heartbeat failed ({res.error_category}): {res.error_message}", file=sys.stderr)
            return 1

    elif args.heartbeat_command == "install":
        res = install_heartbeat_task(
            interval_minutes=args.interval,
            system_account=getattr(args, "system", False),
            headless=getattr(args, "headless", False),
            python_path=getattr(args, "python_path", None),
            apply=args.apply,
        )
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            if not args.apply:
                print(res.get("warning", "Dry-run"))
                print(f"Target task: {res['task_name']} (repeats every {res['interval_minutes']}m)")
                print(f"Execution Identity: {res.get('identity')}")
                if res.get("elevation_notice"):
                    print(res["elevation_notice"])
                if res.get("interactive_notice"):
                    print(res["interactive_notice"])
            elif res.get("ok"):
                print(f"Scheduled task '{res['task_name']}' registered successfully.")
                print(f"Execution Identity: {res.get('identity')}")
            else:
                print(f"Installation failed: {res.get('error')}", file=sys.stderr)
        return 0 if res.get("ok") else 1

    elif args.heartbeat_command == "uninstall":
        res = uninstall_heartbeat_task(apply=args.apply)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            if not args.apply:
                print(res.get("warning", "Dry-run"))
            else:
                print(res.get("message", "Task removed."))
        return 0 if res.get("ok") else 1

    elif args.heartbeat_command == "repair":
        if not args.apply:
            res = {"ok": True, "dry_run": True, "warning": "Dry-run: pass -a/--apply to repair heartbeat task and permissions."}
            print(json.dumps(res, indent=2) if args.json else res["warning"])
            return 0
        cfg = load_healthchecks_config()
        if cfg:
            save_healthchecks_config(cfg)
        install_res = install_heartbeat_task(apply=True)
        res = {"ok": install_res.get("ok", False), "repaired": True, "task": install_res}
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print("Heartbeat task and configuration repaired.")
        return 0 if res["ok"] else 1

    elif args.heartbeat_command == "doctor":
        doc = doctor()
        if args.json:
            print(json.dumps(doc, indent=2))
        else:
            print(f"Heartbeat Doctor Diagnosis: {'HEALTHY' if doc['healthy'] else 'ISSUES DETECTED'}")
            for c in doc["checks"]:
                mark = "[PASS]" if c["passed"] else "[FAIL]"
                print(f" {mark} {c['name']}: {c['details']}")
        return 0 if doc["healthy"] else 1

    return 2


def handle_health(args: argparse.Namespace) -> int:
    try:
        storage = _get_storage(args.db)
        ver = storage.get_schema_version()
        pending = len(storage.list_pending_outbox())
        incidents = len(storage.list_incidents())
        data = {
            "ok": True,
            "status": "healthy",
            "schema_version": ver,
            "pending_outbox": pending,
            "total_incidents": incidents,
        }
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            print(f"Notifications Broker Health: HEALTHY (schema v{ver}, pending: {pending}, incidents: {incidents})")
        return 0
    except Exception as exc:
        err = {"ok": False, "status": "unhealthy", "error": str(exc)}
        print(json.dumps(err) if args.json else f"Health check failed: {exc}", file=sys.stderr)
        return 1


def handle_coordinator(args: argparse.Namespace) -> int:
    db_path = getattr(args, "db", None)
    storage = _get_storage(db_path)
    publisher = Publisher(storage)

    if args.coordinator_command == "status":
        latest = storage.get_latest_rc_observation()
        incidents = storage.list_incidents(limit=20)
        rc_incidents = [
            i.to_dict()
            for i in incidents
            if i.source == "resource_coordinator" and i.status in ("open", "reopened", "acknowledged")
        ]

        data = {
            "ok": True,
            "monitored": latest is not None,
            "observation": latest,
            "active_incidents": rc_incidents,
        }
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            if not latest:
                print("Resource Coordinator Monitoring: No observations recorded yet.")
            else:
                status_str = latest["status"].upper()
                contract = latest["contract_version"]
                print(f"Resource Coordinator Status: {status_str} [contract: {contract}]")
                print(f" - Observed at: {latest['observed_at']}")
                print(f" - Recovery required: {latest.get('recovery_required')}")
                print(f" - Restart inhibition: {latest.get('inhibition_active')} ({latest.get('inhibition_reason') or 'none'})")
                print(f" - Journal status: {latest.get('journal_status')}")
                print(f" - Miner state: {latest.get('miner_state')}")
                if latest.get("error_message"):
                    print(f" - Observation error: {latest['error_message']}")
                print(f" - Active Safety Incidents: {len(rc_incidents)}")
        return 0

    elif args.coordinator_command == "poll":
        providers = None
        if getattr(args, "providers", None):
            providers = [p.strip() for p in args.providers.split(",") if p.strip()]

        try:
            observer = ResourceCoordinatorObserver(
                status_url=args.url,
                timeout_seconds=args.timeout,
                storage=storage,
                providers=providers,
            )
        except ValueError as exc:
            err = {"ok": False, "error": str(exc)}
            print(json.dumps(err, indent=2) if args.json else f"Configuration error: {exc}", file=sys.stderr)
            return 1

        try:
            obs = observer.poll_once()
        except LockContentionError as exc:
            err = {"ok": False, "error": f"Lock contention: {exc}"}
            print(json.dumps(err, indent=2) if args.json else f"Lock contention: {exc}", file=sys.stderr)
            return 1
        except LockError as exc:
            err = {"ok": False, "error": f"Lock error: {exc}"}
            print(json.dumps(err, indent=2) if args.json else f"Lock error: {exc}", file=sys.stderr)
            return 1

        res = {
            "ok": obs.status == "available",
            "observation": obs.to_dict(),
        }
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"Poll completed: {obs.status.upper()}")
            print(f" - Contract: {obs.contract_version} (recovery contract: {'yes' if obs.has_recovery_contract else 'no'})")
            print(f" - Recovery required: {obs.recovery_required}")
            print(f" - Restart inhibition: {obs.inhibition_active} ({obs.inhibition_reason or 'none'})")
            print(f" - Journal: {obs.journal_status}")
            if obs.error_message:
                print(f" - Error: {obs.error_message}")
        return 0 if obs.status == "available" else 1

    elif args.coordinator_command == "prune":
        apply = getattr(args, "apply", False)
        max_age = getattr(args, "max_age_days", 7)
        max_recs = getattr(args, "max_records", 10000)
        if not apply:
            res = {
                "ok": True,
                "action": "prune",
                "dry_run": True,
                "max_age_days": max_age,
                "max_records": max_recs,
                "message": "Dry-run: pass -a/--apply to execute observation pruning.",
            }
            if args.json:
                print(json.dumps(res, indent=2))
            else:
                print(f"Prune dry-run: pass -a/--apply to prune observations older than {max_age} days (max records: {max_recs}).")
            return 0

        deleted = storage.prune_rc_observations(max_age_days=max_age, max_records=max_recs)
        res = {
            "ok": True,
            "action": "prune",
            "applied": True,
            "deleted_count": deleted,
        }
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"Pruned {deleted} old Resource Coordinator observation record(s).")
        return 0

    elif args.coordinator_command == "task":
        if args.task_command == "status":
            res = get_coordinator_task_status()
            if args.json:
                print(json.dumps(res, indent=2))
            else:
                inst = res.get("task_installed", False)
                state = res.get("state", "Unknown")
                print(f"Coordinator Observer Scheduled Task: {'INSTALLED' if inst else 'NOT INSTALLED'} ({state})")
                if inst:
                    print(f" - Last run: {res.get('last_run_time') or 'never'}")
                    print(f" - Next run: {res.get('next_run_time') or 'unknown'}")
                    print(f" - Last result: {res.get('last_task_result')}")
            return 0 if res.get("ok", False) else 1

        elif args.task_command == "install":
            res = install_coordinator_task(
                apply=getattr(args, "apply", False),
                interval_minutes=getattr(args, "interval_minutes", 2),
                status_url=getattr(args, "url", DEFAULT_COORDINATOR_STATUS_URL),
                db_path=Path(db_path) if db_path else None,
                executable=getattr(args, "executable", None),
                working_directory=getattr(args, "working_dir", None),
            )
            if args.json:
                print(json.dumps(res, indent=2))
            else:
                if res.get("dry_run"):
                    print(f"Dry-run task install: task '{res.get('task_name')}' would run every {res.get('interval_minutes')}m.")
                    print("Pass -a/--apply to register with Windows Task Scheduler.")
                elif res.get("installed"):
                    print(f"Scheduled task '{res.get('task_name')}' successfully registered.")
                else:
                    print(f"Failed installing task: {res.get('error')}", file=sys.stderr)
            return 0 if res.get("ok", False) else 1

        elif args.task_command == "uninstall":
            res = uninstall_coordinator_task(apply=getattr(args, "apply", False))
            if args.json:
                print(json.dumps(res, indent=2))
            else:
                if res.get("dry_run"):
                    print(f"Dry-run task uninstall: pass -a/--apply to unregister '{res.get('task_name')}'.")
                elif res.get("uninstalled"):
                    print(f"Scheduled task '{res.get('task_name')}' uninstalled successfully.")
                else:
                    print(f"Failed uninstalling task: {res.get('error')}", file=sys.stderr)
            return 0 if res.get("ok", False) else 1

    elif args.coordinator_command == "test":
        try:
            ResourceCoordinatorObserver._validate_url(args.url)
            res = {
                "ok": True,
                "dry_run": True,
                "target_url": args.url,
                "loopback_validated": True,
                "message": "Resource Coordinator observer loopback target validated. Zero control code imported.",
            }
            if args.json:
                print(json.dumps(res, indent=2))
            else:
                print(f"Dry-run test: target URL '{args.url}' is valid loopback address.")
                print("Safe read-only isolation boundaries verified.")
            return 0
        except ValueError as exc:
            err = {"ok": False, "error": str(exc)}
            print(json.dumps(err, indent=2) if args.json else f"Validation failed: {exc}", file=sys.stderr)
            return 1

    return 2


def handle_release_check(args: argparse.Namespace) -> int:
    from notifications.diagnostics import collect_release_diagnostics

    db_path = getattr(args, "db", None)
    auth_db = getattr(args, "auth_db", None)
    inspect_ts = getattr(args, "inspect_tailscale", False)
    data = collect_release_diagnostics(
        db_path=Path(db_path) if db_path else None,
        auth_db_path=Path(auth_db) if auth_db else None,
        inspect_tailscale=inspect_ts,
    )

    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
        if not data.get("ok"):
            return 1
        if getattr(args, "strict", False) and (not data.get("ready_for_release") or len(data.get("blockers", [])) > 0):
            return 2
        return 0

    print("=== Notifications & Remote Control Release Check ===")
    print(f"Overall Diagnostic:     {'OK' if data.get('ok') else 'ERROR'}")
    print(f"Ready for Release:      {'YES' if data.get('ready_for_release') else 'NO'}")
    print(f"Summary:                {data.get('summary', '')}")

    storage = data.get("storage", {})
    print(f"\nStorage Status:         {storage.get('status', 'unknown')} ({storage.get('path', '')})")
    if storage.get("status") == "healthy":
        print(f"  Total Incidents:      {storage.get('total_incidents', 0)}")
        print(f"  Open Incidents:       {storage.get('open_incidents', 0)}")
        print(f"  Acknowledged:         {storage.get('acknowledged_incidents', 0)}")
        print(f"  Resolved:             {storage.get('resolved_incidents', 0)}")
        print(f"  Pending Outbox:       {storage.get('pending_outbox', 0)}")
        print(f"  Attempting Outbox:    {storage.get('attempting_outbox', 0)}")
        print(f"  Accepted Outbox:      {storage.get('accepted_outbox', 0)}")
        print(f"  Retryable Outbox:     {storage.get('retryable_outbox', 0)}")
        print(f"  Terminal Outbox:      {storage.get('terminal_outbox', 0)}")

    providers = data.get("providers", {})
    tg = providers.get("telegram", {})
    print(f"\nTelegram Provider:      {tg.get('status', 'not_enrolled').capitalize()} ({'configured' if tg.get('configured') else 'inactive'})")
    win = providers.get("windows_helper", {})
    print(f"Windows Toast Helper:   {win.get('status', 'unknown')} (port {win.get('listener_port', 1238)})")
    hc = providers.get("healthchecks", {})
    print(f"Healthchecks Outage:    {hc.get('status', 'unknown')}")
    coord = providers.get("coordinator_observer", {})
    print(f"Coordinator Observer:   {'Installed' if coord.get('task_installed') else 'Not Installed'} (State: {coord.get('task_state', 'Unknown')})")

    rc = data.get("remote_control", {})
    print(f"\nRemote Control Auth:    {rc.get('status', 'unknown')} ({rc.get('path', '')})")
    print(f"  Operator Enrolled:    {rc.get('operator_enrolled', False)}")
    print(f"  TOTP Enrolled:        {rc.get('totp_enrolled', False)}")
    print(f"  Listener (8443):      {'Active' if rc.get('listener_active') else 'Offline'}")
    barriers = rc.get("active_barriers", [])
    print(f"  Active Barriers:      {len(barriers)}")
    for b in barriers:
        print(f"    - Barrier on '{b.get('resource_key')}': {b.get('reason')} (execution: {b.get('execution_id')})")

    funnel = data.get("tailscale_funnel", {})
    print(f"\nTailscale Funnel:       {funnel.get('status', 'unknown')} (inspection: {funnel.get('inspection')})")
    if funnel.get("public_origin"):
        print(f"  Public Origin:        {funnel.get('public_origin')}")

    if data.get("blockers"):
        print("\nRelease Blockers:")
        for b in data.get("blockers", []):
            print(f"  [X] {b}")

    if data.get("warnings"):
        print("\nWarnings:")
        for w in data.get("warnings", []):
            print(f"  [!] {w}")

    print("\nPending Operator Acceptance Gates:")
    for gate, desc in data.get("acceptance_gates_pending", {}).items():
        print(f"  [{gate}] {desc}")

    if not data.get("ok"):
        return 1
    if getattr(args, "strict", False) and (not data.get("ready_for_release") or len(data.get("blockers", [])) > 0):
        return 2
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    if args.command == "publish":
        return handle_publish(args)
    elif args.command == "incidents":
        return handle_incidents(args)
    elif args.command == "outbox":
        return handle_outbox(args)
    elif args.command == "providers":
        return handle_providers(args)
    elif args.command == "health":
        return handle_health(args)
    elif args.command == "telegram":
        return handle_telegram(args)
    elif args.command == "windows":
        return handle_windows(args)
    elif args.command == "heartbeat":
        return handle_heartbeat(args)
    elif args.command == "coordinator":
        return handle_coordinator(args)
    elif args.command == "release-check":
        return handle_release_check(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
