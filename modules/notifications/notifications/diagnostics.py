"""
Unified read-only release diagnostics and supportability checks.
Collects and aggregates status across storage, providers, outbox, remote control,
action barriers, and public exposure without performing mutations or side effects.
"""
from __future__ import annotations

from datetime import datetime, timezone
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
    inspect_tailscale: bool = False,
) -> Dict[str, Any]:
    """
    Collect comprehensive release diagnostics across all notifications and remote control subsystems.
    Enforces strict read-only operation (mode=ro for SQLite, zero schema changes, zero mutations, zero file writes).
    """
    eff_db_path = Path(db_path or default_db_path()).resolve()
    eff_auth_path = Path(
        auth_db_path or (Path.home() / ".scripts" / "remote_control" / "auth.db")
    ).resolve()

    report: Dict[str, Any] = {
        "ok": True,
        "ready_for_release": False,
        "blockers": [],
        "warnings": [],
        "unknowns": [],
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "storage": {},
        "providers": {},
        "remote_control": {},
        "tailscale_funnel": {},
        "acceptance_gates_pending": {
            "W01_android_cellular_https": "Pending operator cellular acceptance testing",
            "W02_totp_public_login": "Pending operator mobile TOTP login verification",
            "W03_telegram_real_delivery": "Pending operator live Bot API delivery test",
            "W04_healthchecks_off_host_alert": "Pending operator simulated outage check",
            "W05_funnel_approved_activation": "Pending operator public enable authorization",
            "RC_recovery": "Permanently disabled in production by policy (zero spend / zero mutation)",
        },
        "summary": "Ready for operator review",
    }

    # ── 1. Notifications Storage Health ──────────────────────────────────────
    if not eff_db_path.is_file():
        report["storage"] = {
            "status": "not_created",
            "path": str(eff_db_path),
            "configured": False,
            "message": "Notifications database file does not exist yet.",
        }
        report["warnings"].append(f"Notifications database file does not exist: {eff_db_path}")
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
                        "configured": True,
                        "message": "Database exists but schema is unmigrated.",
                    }
                    report["blockers"].append(f"Notifications database schema is unmigrated: {eff_db_path}")
                else:
                    open_cnt = conn.execute(
                        "SELECT COUNT(*) FROM incidents WHERE status IN ('open', 'reopened');"
                    ).fetchone()[0]
                    ack_cnt = conn.execute(
                        "SELECT COUNT(*) FROM incidents WHERE status = 'acknowledged';"
                    ).fetchone()[0]
                    res_cnt = conn.execute(
                        "SELECT COUNT(*) FROM incidents WHERE status = 'resolved';"
                    ).fetchone()[0]
                    total_cnt = conn.execute(
                        "SELECT COUNT(*) FROM incidents;"
                    ).fetchone()[0]

                    # Outbox status counts per actual state machine (A2)
                    pending_outbox = 0
                    attempting_outbox = 0
                    accepted_outbox = 0
                    retryable_outbox = 0
                    terminal_outbox = 0

                    if "outbox" in tables:
                        status_rows = conn.execute(
                            "SELECT status, COUNT(*) FROM outbox GROUP BY status;"
                        ).fetchall()
                        status_map = {r[0]: r[1] for r in status_rows}
                        pending_outbox = status_map.get("pending", 0)
                        attempting_outbox = status_map.get("attempting", 0)
                        accepted_outbox = status_map.get("provider_accepted", 0)
                        retryable_outbox = status_map.get("retryable_error", 0)
                        terminal_outbox = status_map.get("terminal_error", 0)

                    report["storage"] = {
                        "status": "healthy",
                        "path": str(eff_db_path),
                        "configured": True,
                        "open_incidents": open_cnt,
                        "acknowledged_incidents": ack_cnt,
                        "resolved_incidents": res_cnt,
                        "total_incidents": total_cnt,
                        "pending_outbox": pending_outbox,
                        "attempting_outbox": attempting_outbox,
                        "accepted_outbox": accepted_outbox,
                        "retryable_outbox": retryable_outbox,
                        "terminal_outbox": terminal_outbox,
                    }
                    if terminal_outbox > 0:
                        report["warnings"].append(f"Outbox has {terminal_outbox} message(s) in terminal error state.")
                    if retryable_outbox > 0:
                        report["warnings"].append(f"Outbox has {retryable_outbox} message(s) awaiting retry.")
        except Exception as exc:
            report["ok"] = False
            report["storage"] = {
                "status": "error",
                "path": str(eff_db_path),
                "configured": True,
                "error": str(exc),
            }
            report["blockers"].append(f"Notifications database read error: {exc}")

    # ── 2. Provider Availability ─────────────────────────────────────────────
    providers_info: Dict[str, Any] = {}

    # Telegram (A3)
    from notifications.delivery.telegram_credentials import default_telegram_credentials_path

    env_token = os.environ.get("NOTIFY_TELEGRAM_BOT_TOKEN")
    env_chat = os.environ.get("NOTIFY_TELEGRAM_CHAT_ID")
    tg_cfg_file = default_telegram_credentials_path()

    if env_token and env_chat:
        masked_chat = f"{env_chat[:3]}***{env_chat[-3:]}" if len(env_chat) > 6 else "***"
        providers_info["telegram"] = {
            "configured": True,
            "source": "environment",
            "owner_chat_id": masked_chat,
            "token_enrolled": True,
            "status": "configured",
        }
    elif tg_cfg_file.is_file():
        try:
            tg_data = json.loads(tg_cfg_file.read_text(encoding="utf-8"))
            chat_id = str(tg_data.get("chat_id", ""))
            has_token = bool(tg_data.get("bot_token"))
            if chat_id and has_token:
                masked_chat = f"{chat_id[:3]}***{chat_id[-3:]}" if len(chat_id) > 6 else "***"
                providers_info["telegram"] = {
                    "configured": True,
                    "source": "secrets_file",
                    "owner_chat_id": masked_chat,
                    "token_enrolled": True,
                    "status": "configured",
                }
            else:
                providers_info["telegram"] = {
                    "configured": False,
                    "source": "secrets_file",
                    "status": "incomplete_enrollment",
                }
                report["warnings"].append("Telegram credentials file exists but lacks bot_token or chat_id.")
        except Exception:
            providers_info["telegram"] = {"configured": False, "status": "malformed_config"}
            report["warnings"].append(f"Telegram credentials file at {tg_cfg_file} is malformed.")
    else:
        providers_info["telegram"] = {"configured": False, "status": "not_enrolled"}

    # Windows Toast Helper
    token_file = default_token_path()
    helper_alive = _probe_tcp_port("127.0.0.1", 1238) if probe_ports else False
    win_status = "active" if helper_alive else ("offline" if token_file.is_file() else "not_configured")
    providers_info["windows_helper"] = {
        "token_file_exists": token_file.is_file(),
        "listener_port": 1238,
        "listener_active": helper_alive,
        "status": win_status,
    }
    if not token_file.is_file():
        report["warnings"].append("Windows notification helper token file is not configured.")
    elif not helper_alive and probe_ports:
        report["warnings"].append("Windows notification helper listener on port 1238 is offline.")

    # Healthchecks Host Heartbeat (A3)
    from notifications.monitoring.config import default_healthchecks_config_path

    env_hc_url = os.environ.get("NOTIFY_HEALTHCHECKS_PING_URL")
    hc_cfg_file = default_healthchecks_config_path()

    if env_hc_url:
        providers_info["healthchecks"] = {
            "configured": True,
            "source": "environment",
            "ping_url_configured": True,
            "interval_minutes": 5,
            "status": "configured",
        }
    elif hc_cfg_file.is_file():
        try:
            hc_data = json.loads(hc_cfg_file.read_text(encoding="utf-8"))
            has_url = bool(hc_data.get("ping_url"))
            if has_url:
                providers_info["healthchecks"] = {
                    "configured": True,
                    "source": "secrets_file",
                    "ping_url_configured": True,
                    "interval_minutes": hc_data.get("interval_minutes", 5),
                    "status": "configured",
                }
            else:
                providers_info["healthchecks"] = {"configured": False, "status": "incomplete_config"}
                report["warnings"].append("Healthchecks config file exists but ping_url is missing.")
        except Exception:
            providers_info["healthchecks"] = {"configured": False, "status": "malformed_config"}
            report["warnings"].append(f"Healthchecks config file at {hc_cfg_file} is malformed.")
    else:
        providers_info["healthchecks"] = {"configured": False, "status": "not_configured"}

    # Coordinator Observer
    try:
        from notifications.integrations.resource_coordinator import get_coordinator_task_status
        obs_task = get_coordinator_task_status()
        providers_info["coordinator_observer"] = {
            "task_installed": obs_task.get("task_installed", False),
            "task_state": obs_task.get("state", "Unknown"),
            "last_run_time": obs_task.get("last_run_time"),
        }
    except Exception as exc:
        providers_info["coordinator_observer"] = {
            "task_installed": False,
            "task_state": "Error",
            "error": str(exc),
        }

    report["providers"] = providers_info

    # ── 3. Remote Control & Action Barriers (A1) ─────────────────────────────
    rc_alive = _probe_tcp_port("127.0.0.1", 8443) if probe_ports else False
    if not eff_auth_path.is_file():
        report["remote_control"] = {
            "status": "not_created",
            "path": str(eff_auth_path),
            "configured": False,
            "listener_active": rc_alive,
            "active_barriers": [],
        }
        report["warnings"].append(f"Remote Control auth database does not exist: {eff_auth_path}")
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
                        "SELECT resource_key, execution_id, barrier_status, reason, created_at "
                        "FROM action_resource_barriers WHERE cleared_at IS NULL;"
                    ).fetchall()
                    for b in barrier_rows:
                        active_barriers.append({
                            "resource_key": b["resource_key"],
                            "execution_id": b["execution_id"],
                            "barrier_status": b["barrier_status"],
                            "reason": b["reason"],
                            "created_at": b["created_at"],
                        })
                        report["blockers"].append(
                            f"Active action resource barrier on '{b['resource_key']}': {b['reason']}"
                        )

                rc_status = "action_barrier_active" if len(active_barriers) > 0 else "healthy"
                report["remote_control"] = {
                    "status": rc_status,
                    "path": str(eff_auth_path),
                    "configured": True,
                    "operator_enrolled": operator_enrolled,
                    "totp_enrolled": totp_enrolled,
                    "listener_port": 8443,
                    "listener_active": rc_alive,
                    "active_barriers": active_barriers,
                }
        except Exception as exc:
            report["ok"] = False
            report["remote_control"] = {
                "status": "error",
                "path": str(eff_auth_path),
                "configured": True,
                "listener_active": rc_alive,
                "error": str(exc),
            }
            report["blockers"].append(f"Remote Control database read error: {exc}")

    # ── 4. Tailscale Funnel Lifecycle (A4) ────────────────────────────────────
    rc_cfg_file = Path.home() / ".scripts" / "remote_control" / "config.json"
    configured_exposure = False
    public_origin = None
    if rc_cfg_file.is_file():
        try:
            rc_data = json.loads(rc_cfg_file.read_text(encoding="utf-8"))
            configured_exposure = bool(rc_data.get("external_exposure_enabled", False))
            public_origin = rc_data.get("public_origin")
        except Exception:
            pass
    if os.environ.get("REMOTE_CONTROL_EXTERNAL_EXPOSURE") == "1":
        configured_exposure = True

    if not inspect_tailscale:
        report["tailscale_funnel"] = {
            "configured_exposure_enabled": configured_exposure,
            "public_origin": public_origin,
            "inspection": "skipped_no_subprocess",
            "observed_funnel_active": None,
            "status": "uninspected",
            "message": "Funnel live route inspection was skipped (strict read-only mode without subprocess). Run with --inspect-tailscale to inspect.",
        }
        report["unknowns"].append("Tailscale Funnel live state uninspected (pass --inspect-tailscale to inspect)")
    else:
        try:
            from remote_control.external.client import get_tailscale_client
            client = get_tailscale_client(read_only=True)
            st = client.get_status()
            report["tailscale_funnel"] = {
                "configured_exposure_enabled": configured_exposure,
                "public_origin": public_origin,
                "inspection": "executed",
                "tailscale_installed": st.installed,
                "logged_in": st.logged_in,
                "node_name": st.node_name,
                "tailnet_name": st.tailnet_name,
                "funnel_available": st.funnel_available,
                "observed_funnel_active": st.funnel_active,
                "public_url": st.public_url,
                "status": "active" if st.funnel_active else "inactive",
            }
            if st.funnel_active and not configured_exposure:
                report["warnings"].append("Tailscale Funnel is active but application configured_exposure is False.")
        except Exception as exc:
            report["tailscale_funnel"] = {
                "configured_exposure_enabled": configured_exposure,
                "public_origin": public_origin,
                "inspection": "failed",
                "observed_funnel_active": None,
                "status": "error",
                "error": str(exc),
            }
            report["warnings"].append(f"Tailscale inspection error: {exc}")

    # ── 5. Overall Evaluation (A5) ───────────────────────────────────────────
    is_storage_healthy = report["storage"].get("status") == "healthy"
    report["ready_for_release"] = bool(
        report["ok"]
        and len(report["blockers"]) == 0
        and is_storage_healthy
    )
    if report["ready_for_release"]:
        report["summary"] = "Ready for release (all prerequisites satisfied; operational acceptance gates pending)"
    elif len(report["blockers"]) > 0:
        report["summary"] = f"Release blocked: {len(report['blockers'])} blocker(s) detected"
    else:
        report["summary"] = "Prerequisites incomplete or unconfigured"

    return report

