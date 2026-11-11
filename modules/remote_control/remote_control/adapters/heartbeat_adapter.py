"""Read-only adapter for inspecting host heartbeat monitoring and provider health."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from notifications.monitoring.config import load_healthchecks_config, redact_ping_url
from notifications.monitoring.service import get_heartbeat_task_status

logger = logging.getLogger(__name__)


class ReadOnlyMonitoringAdapter:
    """Provides read-only status of host heartbeat and delivery providers."""

    def __init__(self, config_path: Optional[Path] = None) -> None:
        self.config_path = config_path

    def get_heartbeat_status(self) -> Dict[str, Any]:
        """Query host heartbeat configuration and Scheduled Task state with secret redaction."""
        try:
            status = get_heartbeat_task_status(self.config_path)
            # Guarantee ping URL is strictly redacted
            if status.get("ping_url_redacted"):
                status["ping_url_redacted"] = redact_ping_url(status["ping_url_redacted"])
            return status
        except Exception as exc:
            logger.warning("Failed querying heartbeat status: %s", exc)
            return {
                "ok": False,
                "error": str(exc),
                "task_installed": False,
                "configured": False,
            }

    def get_providers_status(self) -> List[Dict[str, Any]]:
        """Inspect operational configuration of delivery providers."""
        providers = []

        # 1. Telegram
        try:
            from notifications.delivery.telegram_credentials import load_telegram_credentials
            creds = load_telegram_credentials()
            providers.append({
                "provider": "telegram",
                "configured": creds is not None,
                "status": "ready" if creds else "unconfigured",
                "chat_id": creds.chat_id if creds else None,
                "details": "Direct cloud delivery to mobile Telegram" if creds else "Run 'scripts-notify telegram enroll' to configure",
            })
        except Exception as exc:
            providers.append({
                "provider": "telegram",
                "configured": False,
                "status": "error",
                "details": f"Inspection error: {exc}",
            })

        # 2. Windows Desktop Toast
        try:
            from notifications.windows_helper.service import get_helper_status
            win_stat = get_helper_status()
            providers.append({
                "provider": "windows",
                "configured": win_stat.get("task_installed", False),
                "status": "ready" if win_stat.get("helper_running") else "offline",
                "details": f"Interactive helper on port {win_stat.get('helper_port', 1238)} (Task: {win_stat.get('task_state', 'not_found')})",
            })
        except Exception as exc:
            providers.append({
                "provider": "windows",
                "configured": False,
                "status": "error",
                "details": f"Inspection error: {exc}",
            })

        return providers
