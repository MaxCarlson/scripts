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
from notifications.outbox import OutboxWorker
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
    tg_enroll.add_argument("-t", "--token", required=True, help="Telegram Bot API token from @BotFather.")
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
        fake_prov = FakeProvider(provider_id="fake_provider")
        worker = OutboxWorker(storage, providers={"fake_provider": fake_prov})
        count = asyncio.run(worker.process_pending_once(limit=args.limit))
        res = {"ok": True, "processed": count}
        print(json.dumps(res, indent=2) if args.json else f"Processed {count} outbox delivery task(s).")
        return 0

    return 2


def handle_providers(args: argparse.Namespace) -> int:
    if args.providers_command == "list":
        data = {
            "ok": True,
            "providers": [
                {"id": "fake_provider", "type": "testing", "status": "available"},
                {"id": "telegram", "type": "external", "status": "available"},
            ],
        }
        print(json.dumps(data, indent=2) if args.json else "Registered Providers: fake_provider, telegram")
        return 0

    elif args.providers_command == "test":
        known = ["fake_provider", "telegram"]
        if args.provider not in known:
            err = {"ok": False, "error": f"Unknown provider '{args.provider}'. Available: {', '.join(known)}"}
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

        if args.provider == "fake_provider":
            provider = FakeProvider(mode="success")
            notification = RenderedNotification(
                notification_id="notif-test-001",
                event_id="00000000-0000-4000-8000-000000000001",
                incident_id="inc-test-001",
                severity="info",
                title="[TEST] Provider Diagnostic",
                body="Simulated test message via fake_provider",
                created_at="2026-11-11T00:00:00Z",
            )
            receipt = asyncio.run(provider.send(notification))
            res = {
                "ok": True,
                "provider": "fake_provider",
                "simulated": True,
                "status": receipt.status,
                "receipt": receipt.to_dict(),
            }
            print(json.dumps(res, indent=2) if args.json else "Simulated notification delivered via fake_provider.")
            return 0

        elif args.provider == "telegram":
            try:
                from notifications.delivery.telegram_credentials import load_telegram_credentials
                from notifications.delivery.telegram import TelegramProvider

                creds = load_telegram_credentials()
            except (ImportError, ModuleNotFoundError):
                creds = None

            if not creds:
                err = {
                    "ok": False,
                    "provider": "telegram",
                    "error": "Telegram provider is not configured. Missing bot token or chat ID.",
                }
                print(json.dumps(err) if args.json else err["error"], file=sys.stderr)
                return 1

            try:
                provider = TelegramProvider(credentials=creds)
                notification = RenderedNotification(
                    notification_id="tg-diag-001",
                    event_id=str(uuid.uuid4()),
                    incident_id="inc-telegram-001",
                    severity="info",
                    title="[TEST] Telegram Diagnostic",
                    body="Testing Telegram provider delivery via 'scripts-notify providers test'",
                    created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                )
                receipt = asyncio.run(provider.send(notification))
                if receipt.status == "provider_accepted":
                    res = {"ok": True, "provider": "telegram", "status": "accepted", "receipt": receipt.to_dict()}
                    print(json.dumps(res, indent=2) if args.json else "Test notification accepted by Telegram API.")
                    return 0
                else:
                    err = {"ok": False, "provider": "telegram", "status": receipt.status, "error": receipt.error_message}
                    print(json.dumps(err) if args.json else err["error"], file=sys.stderr)
                    return 1
            except Exception as exc:
                err = {"ok": False, "provider": "telegram", "error": f"Telegram provider test failed: {exc}"}
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
                bot_token=args.token,
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

    return 0


if __name__ == "__main__":
    sys.exit(main())
