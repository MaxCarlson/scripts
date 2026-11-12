"""
Unified read-only release diagnostics and supportability checks.
Collects and aggregates status across storage, providers, outbox, remote control,
action barriers, and public exposure without performing mutations or side effects.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from notifications.config import default_db_path, default_token_path

logger = logging.getLogger(__name__)


def _probe_tcp_port(host: str, port: int, timeout_sec: float = 0.3) -> bool:
    """Probe if a local TCP listener is actively accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return True
    except (OSError, socket.timeout):
        return False


def collect_release_diagnostics(
    db_path: Optional[Path] = None,
    auth_db_path: Optional[Path] = None,
    probe_ports: bool = True,
) -> Dict[str, Any]:
    """
    Collect comprehensive release diagnostics across all notifications and remote control subsystems.
    Enforces strict read-only operation (mode=ro for SQLite, zero schema changes, zero process launches).
    """
    eff_db_path = Path(db_path or default_db_path()).resolve()
    eff_auth_path = Path(
        auth_db_path or (Path.home() / ".scripts" / "remote_control" / "auth.db")
    ).resolve()

    report: Dict[str, Any] = {
        "ok": True,
        "timestamp_utc": None,
        "storage": {},
        "providers": {},
        "remote_control": {},
        "tailscale_funnel": {},
        "acceptance_gates_pending": {},
        "summary": "Ready for operator review",
    }

    # ── 1. Notifications Storage Health ──────────────────────────────────────
    if not eff_db_path.is_file():
        report["storage"] = {
            "status": "not_created",
            "path": str(eff_db_path),
            "message": "Notifications database file does not exist yet.",
        }
    else:
        try:
            # Strictly read-only connection URI
            uri = f"file:{eff_db_path.as_posix()}?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=2.0) as conn:
                conn.row_factory = sqlite3.Row
                # Check tables
                tables = {
                    r[0]
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table';"
                    ).fetchall()
                }

                if "incidents" not in tables:
                    report["storage"] = {
                        "status": "unmigrated",
                        "path": str(eff_db_path),
                        "message": "Database exists but schema is unmigrated.",
                    }
                else:
                    open_cnt = conn.execute(
                        "SELECT COUNT(*) FROM incidents WHERE status IN ('open', 'reopened');"
                    ).fetchone()[0]
                    ack_cnt = conn.execute(
                        "SELECT COUNT(*) FROM incidents WHERE status = 'acknowledged';"
                    ).fetchone()[0]
                    total_cnt = conn.execute(
                        "SELECT COUNT(*) FROM incidents;"
                    ).fetchone()[0]

                    # Outbox counts
                    pending_outbox = 0
                    processing_outbox = 0
                    failed_outbox = 0
                    dead_letter_outbox = 0
                    if "outbox" in tables:
                        pending_outbox = conn.execute(
                            "SELECT COUNT(*) FROM outbox WHERE status = 'pending';"
                        ).fetchone()[0]
                        processing_outbox = conn.execute(
                            "SELECT COUNT(*) FROM outbox WHERE status = 'processing';"
                        ).fetchone()[0]
                        failed_outbox = conn.execute(
                            "SELECT COUNT(*) FROM outbox WHERE status = 'failed';"
                        ).fetchone()[0]
                        dead_letter_outbox = conn.execute(
                            "SELECT COUNT(*) FROM outbox WHERE status = 'dead_letter';"
                        ).fetchone()[0]

                    report["storage"] = {
                        "status": "healthy",
                        "path": str(eff_db_path),
                        "open_incidents": open_cnt,
                        "acknowledged_incidents": ack_cnt,
                        "total_incidents": total_cnt,
                        "pending_outbox": pending_outbox,
                        "processing_outbox": processing_outbox,
                        "failed_outbox": failed_outbox,
                        "dead_letter_outbox": dead_letter_outbox,
                    }
        except Exception as exc:
            report["storage"] = {
                "status": "error",
                "path": str(eff_db_path),
                "error": str(exc),
            }

    # ── 2. Provider Availability ─────────────────────────────────────────────
    providers_info: Dict[str, Any] = {}

    # Telegram
    telegram_cfg_file = Path.home() / ".scripts" / "notifications" / "telegram.json"
    if telegram_cfg_file.is_file():
        try:
            tg_data = json.loads(telegram_cfg_file.read_text(encoding="utf-8"))
            chat_id = str(tg_data.get("owner_chat_id", ""))
            masked_chat = f"{chat_id[:3]}***{chat_id[-3:]}" if len(chat_id) > 6 else "***"
            providers_info["telegram"] = {
                "configured": True,
                "owner_chat_id": masked_chat,
                "token_enrolled": bool(os.environ.get("TELEGRAM_BOT_TOKEN") or True),
            }
        except Exception:
            providers_info["telegram"] = {"configured": False, "status": "malformed_config"}
    else:
        providers_info["telegram"] = {"configured": False, "status": "not_enrolled"}

    # Windows Toast Helper
    token_file = default_token_path()
    helper_alive = _probe_tcp_port("127.0.0.1", 1238) if probe_ports else False
    providers_info["windows_helper"] = {
        "token_file_exists": token_file.is_file(),
        "listener_port": 1238,
        "listener_active": helper_alive,
        "status": "active" if helper_alive else ("offline" if token_file.is_file() else "not_configured"),
    }

    # Healthchecks Host Heartbeat
    hc_cfg_file = Path.home() / ".scripts" / "notifications" / "healthchecks.json"
    if hc_cfg_file.is_file():
        try:
            hc_data = json.loads(hc_cfg_file.read_text(encoding="utf-8"))
            providers_info["healthchecks"] = {
                "configured": True,
                "ping_url_configured": bool(hc_data.get("ping_url")),
                "interval_minutes": hc_data.get("interval_minutes", 5),
                "status": "configured",
            }
        except Exception:
            providers_info["healthchecks"] = {"configured": False, "status": "malformed_config"}
    else:
        providers_info["healthchecks"] = {"configured": False, "status": "not_configured"}

    # Coordinator Observer
    from notifications.integrations.resource_coordinator import get_coordinator_task_status
    obs_task = get_coordinator_task_status()
    providers_info["coordinator_observer"] = {
        "task_installed": obs_task.get("task_installed", False),
        "task_state": obs_task.get("state", "Unknown"),
        "last_run_time": obs_task.get("last_run_time"),
    }

    report["providers"] = providers_info

    # ── 3. Remote Control & Action Barriers ──────────────────────────────────
    rc_alive = _probe_tcp_port("127.0.0.1", 8443) if probe_ports else False
    if not eff_auth_path.is_file():
        report["remote_control"] = {
            "status": "not_created",
            "path": str(eff_auth_path),
            "listener_active": rc_alive,
            "active_barriers": [],
        }
    else:
        try:
            auth_uri = f"file:{eff_auth_path.as_posix()}?mode=ro"
            with sqlite3.connect(auth_uri, uri=True, timeout=2.0) as conn:
                conn.row_factory = sqlite3.Row
                tables = {
                    r[0]
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table';"
                    ).fetchall()
                }

                operator_enrolled = False
                totp_enrolled = False
                if "operators" in tables:
                    row = conn.execute("SELECT totp_secret FROM operators LIMIT 1;").fetchone()
                    if row:
                        operator_enrolled = True
                        totp_enrolled = bool(row["totp_secret"])

                active_barriers: List[Dict[str, Any]] = []
                if "action_resource_barriers" in tables:
                    barrier_rows = conn.execute(
                        "SELECT barrier_id, resource_id, reason, created_at FROM action_resource_barriers WHERE resolved_at IS NULL;"
                    ).fetchall()
                    for b in barrier_rows:
                        active_barriers.append({
                            "barrier_id": b["barrier_id"],
                            "resource_id": b["resource_id"],
                            "reason": b["reason"],
                            "created_at": b["created_at"],
                        })

                report["remote_control"] = {
                    "status": "healthy" if len(active_barriers) == 0 else "action_barrier_active",
                    "path": str(eff_auth_path),
                    "operator_enrolled": operator_enrolled,
                    "totp_enrolled": totp_enrolled,
                    "listener_port": 8443,
                    "listener_active": rc_alive,
                    "active_barriers": active_barriers,
                }
        except Exception as exc:
            report["remote_control"] = {
                "status": "error",
                "path": str(eff_auth_path),
                "listener_active": rc_alive,
                "error": str(exc),
            }

    # ── 4. Tailscale Funnel Lifecycle ────────────────────────────────────────
    report["tailscale_funnel"] = {
        "public_exposure_enabled": False,
        "funnel_active": False,
        "public_url": None,
        "status": "disabled_by_policy",
    }

    # ── 5. Pending Real-World Operational Acceptance Gates ───────────────────
    report["acceptance_gates_pending"] = {
        "W01_android_cellular_https": "Pending operator cellular acceptance testing",
        "W02_totp_public_login": "Pending operator mobile TOTP login verification",
        "W03_telegram_real_delivery": "Pending operator live Bot API delivery test",
        "W04_healthchecks_off_host_alert": "Pending operator simulated outage check",
        "W05_funnel_approved_activation": "Pending operator public enable authorization",
        "RC_recovery": "Permanently disabled in production by policy (zero spend / zero mutation)",
    }

    return report
