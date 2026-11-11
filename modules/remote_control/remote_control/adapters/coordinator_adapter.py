"""Read-only adapter for inspecting Resource Coordinator status and observations."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ReadOnlyCoordinatorAdapter:
    """Provides sanitized, read-only query access to Resource Coordinator observations."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path.resolve()

    def _get_ro_connection(self) -> sqlite3.Connection:
        if not self.db_path.is_file():
            raise FileNotFoundError(f"Notifications database not found at {self.db_path}")

        uri = f"file:{self.db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=3.0)
        conn.row_factory = sqlite3.Row
        return conn

    def get_coordinator_status(self) -> Dict[str, Any]:
        """Aggregate sanitized operational status of Resource Coordinator."""
        if not self.db_path.is_file():
            return {
                "ok": True,
                "status": "unmonitored",
                "available": False,
                "message": "Notifications database not initialized or monitoring inactive.",
                "last_observation_time": None,
                "observation_age_seconds": None,
                "is_stale": True,
                "contract_capabilities": {
                    "version": "unknown",
                    "has_recovery_contract": False,
                },
                "recovery_required": "unknown",
                "inhibition_active": "unknown",
                "inhibition_reason": None,
                "journal_status": "unknown",
                "miner_state": "unknown",
                "active_incidents": [],
            }

        try:
            with self._get_ro_connection() as conn:
                # 1. Fetch latest observation
                obs_row = conn.execute(
                    "SELECT * FROM rc_observations ORDER BY id DESC LIMIT 1"
                ).fetchone()

                # 2. Fetch active RC incidents
                inc_rows = conn.execute(
                    """
                    SELECT incident_id, incident_key, status, severity, summary, first_seen, last_seen
                    FROM incidents
                    WHERE source = 'resource_coordinator' AND status IN ('open', 'reopened', 'acknowledged')
                    ORDER BY last_seen DESC
                    """
                ).fetchall()
                active_incidents = [dict(r) for r in inc_rows]

                if not obs_row:
                    return {
                        "ok": True,
                        "status": "unmonitored",
                        "available": False,
                        "message": "No Resource Coordinator observations recorded yet.",
                        "last_observation_time": None,
                        "observation_age_seconds": None,
                        "is_stale": True,
                        "contract_capabilities": {
                            "version": "unknown",
                            "has_recovery_contract": False,
                        },
                        "recovery_required": "unknown",
                        "inhibition_active": "unknown",
                        "inhibition_reason": None,
                        "journal_status": "unknown",
                        "miner_state": "unknown",
                        "active_incidents": active_incidents,
                    }

                obs = dict(obs_row)
                observed_iso = obs["observed_at"]
                age_seconds: Optional[float] = None
                is_stale = True

                try:
                    obs_dt = datetime.fromisoformat(observed_iso.replace("Z", "+00:00"))
                    age_seconds = max(0.0, (datetime.now(timezone.utc) - obs_dt).total_seconds())
                    is_stale = age_seconds > 120.0  # Stale if older than 2 minutes
                except Exception:
                    pass

                has_recovery = bool(obs.get("has_recovery_contract"))
                raw_rec_req = obs.get("recovery_required")
                raw_inh_act = obs.get("inhibition_active")

                if obs["status"] == "available":
                    rec_req = bool(raw_rec_req) if raw_rec_req is not None else "unknown"
                    inh_act = bool(raw_inh_act) if raw_inh_act is not None else "unknown"
                    return {
                        "ok": True,
                        "status": "available",
                        "available": True,
                        "message": "Resource Coordinator is reachable and monitored.",
                        "last_observation_time": observed_iso,
                        "observation_age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
                        "is_stale": is_stale,
                        "contract_capabilities": {
                            "version": obs.get("contract_version", "unknown"),
                            "has_recovery_contract": has_recovery,
                        },
                        "recovery_required": rec_req,
                        "inhibition_active": inh_act,
                        "inhibition_reason": obs.get("inhibition_reason"),
                        "journal_status": obs.get("journal_status") or "unknown",
                        "miner_state": obs.get("miner_state") or "unknown",
                        "active_incidents": active_incidents,
                    }
                else:
                    # Coordinator unavailable or degraded
                    # MANDATORY RULE B4/B6: Never report inhibition_active=False when unavailable!
                    return {
                        "ok": True,
                        "status": "unavailable",
                        "available": False,
                        "message": f"Resource Coordinator is unavailable: {obs.get('error_message') or 'Connection failed'}",
                        "last_observation_time": observed_iso,
                        "observation_age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
                        "is_stale": is_stale,
                        "contract_capabilities": {
                            "version": obs.get("contract_version", "unknown"),
                            "has_recovery_contract": has_recovery,
                        },
                        "recovery_required": "unknown",
                        "inhibition_active": "unknown",
                        "inhibition_reason": None,
                        "journal_status": "unknown",
                        "miner_state": "unknown",
                        "active_incidents": active_incidents,
                    }

        except Exception as exc:
            logger.warning("Failed querying Resource Coordinator observations: %s", exc)
            return {
                "ok": True,
                "status": "degraded",
                "available": False,
                "message": f"Database query error: {exc}",
                "last_observation_time": None,
                "observation_age_seconds": None,
                "is_stale": True,
                "contract_capabilities": {
                    "version": "unknown",
                    "has_recovery_contract": False,
                },
                "recovery_required": "unknown",
                "inhibition_active": "unknown",
                "inhibition_reason": None,
                "journal_status": "unknown",
                "miner_state": "unknown",
                "active_incidents": [],
            }
