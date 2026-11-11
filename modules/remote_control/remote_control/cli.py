"""Command line interface for remote_control operator enrollment and server lifecycle."""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import sys
from pathlib import Path
from typing import Optional, Sequence

from remote_control.app import create_app
from remote_control.auth.service import AuthService
from remote_control.auth.storage import AuthStorage
from remote_control.config import RemoteControlConfig

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts-remote-control",
        description="Operator enrollment, security management, and server lifecycle for Remote Control.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging.")
    parser.add_argument("-d", "--auth-db", default=None, help="Override path to auth.db.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. bootstrap
    boot_p = subparsers.add_parser("bootstrap", help="Bootstrap single operator credentials and enroll TOTP.")
    boot_p.add_argument("-u", "--username", default=None, help="Operator username.")
    boot_p.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # 2. status
    stat_p = subparsers.add_parser("status", help="Show operator enrollment and session health status.")
    stat_p.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # 3. serve
    serve_p = subparsers.add_parser("serve", help="Run authenticated local HTTP development/production server.")
    serve_p.add_argument("-H", "--host", default="127.0.0.1", help="Host interface to bind (default: 127.0.0.1).")
    serve_p.add_argument("-p", "--port", type=int, default=8443, help="Port to listen on (default: 8443).")
    serve_p.add_argument("--reload", action="store_true", help="Enable auto-reload for local development.")

    # 4. reset-password
    pwd_p = subparsers.add_parser("reset-password", help="Reset operator password via authenticated local console.")
    pwd_p.add_argument("-u", "--username", default=None, help="Confirm operator username.")

    # 5. reset-totp
    totp_p = subparsers.add_parser("reset-totp", help="Regenerate operator TOTP two-factor seed.")
    totp_p.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # 6. revoke-device
    dev_p = subparsers.add_parser("revoke-device", help="Permanently revoke a personal device and terminate sessions.")
    dev_p.add_argument("--device-id", required=True, help="ID of device to revoke.")

    # 7. revoke-session
    sess_p = subparsers.add_parser("revoke-session", help="Invalidate an active operator session.")
    sess_p.add_argument("--session-id", required=True, help="ID of session to revoke.")

    return parser


def get_services(args: argparse.Namespace) -> tuple[RemoteControlConfig, AuthStorage, AuthService]:
    cfg = RemoteControlConfig.from_env()
    if args.auth_db:
        cfg = RemoteControlConfig(
            host=cfg.host,
            port=cfg.port,
            auth_db_path=Path(args.auth_db),
            notifications_db_path=cfg.notifications_db_path,
            healthchecks_config_path=cfg.healthchecks_config_path,
            cookie_secure=cfg.cookie_secure,
            cookie_samesite=cfg.cookie_samesite,
            allowed_hosts=cfg.allowed_hosts,
        )
    storage = AuthStorage(cfg.auth_db_path)
    auth_service = AuthService(storage, cfg)
    return cfg, storage, auth_service


def handle_bootstrap(args: argparse.Namespace) -> int:
    cfg, storage, auth = get_services(args)
    if auth.is_bootstrapped():
        err = {"ok": False, "error": "already_bootstrapped", "message": "Operator identity already bootstrapped."}
        print(json.dumps(err) if args.json else f"Error: {err['message']}", file=sys.stderr)
        return 1

    username = args.username
    if not username:
        if sys.stdin.isatty():
            username = input("Enter Operator Username: ").strip()
        else:
            username = sys.stdin.readline().strip()

    if not username:
        print("Error: Username cannot be empty.", file=sys.stderr)
        return 1

    if sys.stdin.isatty():
        pwd1 = getpass.getpass("Enter Operator Password: ")
        pwd2 = getpass.getpass("Confirm Operator Password: ")
        if pwd1 != pwd2:
            print("Error: Passwords do not match.", file=sys.stderr)
            return 1
        password = pwd1
    else:
        password = sys.stdin.readline().strip()

    if len(password) < 8:
        print("Error: Password must be at least 8 characters.", file=sys.stderr)
        return 1

    try:
        op, totp_secret, uri = auth.bootstrap(username=username, password=password)
        res = {
            "ok": True,
            "status": "bootstrapped",
            "username": op.username,
            "operator_id": op.operator_id,
            "totp_secret": totp_secret,
            "provisioning_uri": uri,
        }
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"Operator '{op.username}' ({op.operator_id}) enrolled successfully.")
            print(f"\nTOTP Base32 Secret: {totp_secret}")
            print(f"Provisioning URI:   {uri}")
            print("\nEnter this secret into Google Authenticator, Aegis, Bitwarden, or 1Password.")
        return 0
    except Exception as exc:
        err = {"ok": False, "error": str(exc)}
        print(json.dumps(err) if args.json else f"Bootstrap failed: {exc}", file=sys.stderr)
        return 1


def handle_status(args: argparse.Namespace) -> int:
    cfg, storage, auth = get_services(args)
    bootstrapped = auth.is_bootstrapped()
    op = storage.get_operator()
    active_sessions = len(storage.list_active_sessions())
    devices = storage.list_devices()

    data = {
        "ok": True,
        "bootstrapped": bootstrapped,
        "operator": op["username"] if op else None,
        "active_sessions": active_sessions,
        "registered_devices": len(devices),
        "auth_db": str(cfg.auth_db_path),
    }

    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print("Remote Control Service Status:")
        print(f" - Bootstrapped: {'Yes' if bootstrapped else 'No (run scripts-remote-control bootstrap)'}")
        if bootstrapped:
            print(f" - Operator: {op['username']}")
            print(f" - Active Sessions: {active_sessions}")
            print(f" - Registered Devices: {len(devices)}")
        print(f" - Auth Database: {cfg.auth_db_path}")
    return 0


def handle_serve(args: argparse.Namespace) -> int:
    import uvicorn

    cfg, storage, auth = get_services(args)
    # Strictly reject binding to non-loopback interfaces by default
    bind_host = args.host.strip().lower()
    if bind_host not in ("127.0.0.1", "localhost", "::1"):
        print(
            f"Security Error: Server binding to '{args.host}' is prohibited. Remote control binds strictly to loopback (127.0.0.1) in Phase 06.",
            file=sys.stderr,
        )
        return 1

    app_instance = create_app(cfg)

    print(f"Starting Remote Control server on http://{bind_host}:{args.port}")
    print("Press Ctrl+C to stop.")
    uvicorn.run(app_instance, host=bind_host, port=args.port, reload=args.reload)
    return 0


def handle_reset_password(args: argparse.Namespace) -> int:
    cfg, storage, auth = get_services(args)
    if not auth.is_bootstrapped():
        print("Error: Operator not bootstrapped.", file=sys.stderr)
        return 1

    pwd1 = getpass.getpass("Enter New Password: ")
    pwd2 = getpass.getpass("Confirm New Password: ")
    if pwd1 != pwd2:
        print("Error: Passwords do not match.", file=sys.stderr)
        return 1

    auth.reset_password(pwd1)
    print("Operator password successfully updated. All active sessions invalidated.")
    return 0


def handle_reset_totp(args: argparse.Namespace) -> int:
    cfg, storage, auth = get_services(args)
    if not auth.is_bootstrapped():
        print("Error: Operator not bootstrapped.", file=sys.stderr)
        return 1

    secret, uri = auth.reset_totp()
    if args.json:
        print(json.dumps({"ok": True, "totp_secret": secret, "provisioning_uri": uri}, indent=2))
    else:
        print(f"New TOTP Secret:  {secret}")
        print(f"Provisioning URI: {uri}")
        print("\nScan or enter into your authenticator app.")
    return 0


def handle_revoke_device(args: argparse.Namespace) -> int:
    cfg, storage, auth = get_services(args)
    success = auth.revoke_device(args.device_id, actor_id="console")
    if success:
        print(f"Device '{args.device_id}' revoked and sessions terminated.")
        return 0
    else:
        print(f"Device '{args.device_id}' not found.", file=sys.stderr)
        return 1


def handle_revoke_session(args: argparse.Namespace) -> int:
    cfg, storage, auth = get_services(args)
    success = auth.revoke_session(args.session_id, actor_id="console")
    if success:
        print(f"Session '{args.session_id}' revoked.")
        return 0
    else:
        print(f"Session '{args.session_id}' not found or already inactive.", file=sys.stderr)
        return 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    if args.command == "bootstrap":
        return handle_bootstrap(args)
    elif args.command == "status":
        return handle_status(args)
    elif args.command == "serve":
        return handle_serve(args)
    elif args.command == "reset-password":
        return handle_reset_password(args)
    elif args.command == "reset-totp":
        return handle_reset_totp(args)
    elif args.command == "revoke-device":
        return handle_revoke_device(args)
    elif args.command == "revoke-session":
        return handle_revoke_session(args)

    return 2


if __name__ == "__main__":
    sys.exit(main())
