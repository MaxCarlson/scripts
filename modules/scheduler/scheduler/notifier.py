"""
Cross-platform system notification hook.
Dispatches desktop/system notifications on schedule runs, task completions, and failures.
Supports integration with the durable Notifications broker and safe platform fallbacks.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import sys
from typing import Any, Dict, Optional

from .config import SchedulerConfig
from .models import ExecutionResult

logger = logging.getLogger(__name__)


class Notifier:
    """Dispatches system notifications across Linux, Windows, macOS, and Termux."""

    def __init__(self, config: Optional[SchedulerConfig] = None) -> None:
        self.config = config or SchedulerConfig()
        self._broker_publisher: Any = None

    def update_config(self, config: SchedulerConfig) -> None:
        self.config = config

    def _get_broker_publisher(self) -> Optional[Any]:
        """Lazy-load in-process Notifications Publisher when available."""
        if self._broker_publisher is None:
            try:
                from notifications.publisher import Publisher
                from notifications.storage import StorageEngine

                storage = StorageEngine()
                storage.migrate()
                self._broker_publisher = Publisher(storage=storage)
            except Exception as exc:
                logger.debug("Notifications broker unavailable for in-process publishing: %s", exc)
                self._broker_publisher = False

        return self._broker_publisher if self._broker_publisher else None

    def _publish_to_broker(
        self,
        source: str,
        kind: str,
        incident_key: str,
        severity: str,
        summary: str,
        lifecycle: str = "open",
        resource: Optional[str] = None,
        labels: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Publish a typed event envelope to the Notifications broker."""
        pub = self._get_broker_publisher()
        if not pub:
            return False

        bounded_summary = summary[:512].replace("\r", " ").replace("\n", " ").strip()
        res = pub.create_and_publish(
            source=source,
            kind=kind,
            incident_key=incident_key,
            severity=severity,
            summary=bounded_summary,
            lifecycle=lifecycle,
            resource=resource,
            labels=labels or {},
        )
        return bool(res.accepted)

    def _notify_platform(self, title: str, message: str, urgency: str = "normal") -> bool:
        """Direct desktop/terminal notification using platform tools with bounded timeouts and returncode checks."""
        # 1. Termux
        if shutil.which("termux-notification"):
            try:
                proc = subprocess.run(
                    ["termux-notification", "--title", title, "--content", message],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
                if proc.returncode == 0:
                    return True
            except Exception as exc:
                logger.debug("Termux notification failed: %s", exc)

        # 2. Linux / BSD / X11 desktop via notify-send
        if shutil.which("notify-send") and os.environ.get("DISPLAY"):
            u_flag = "critical" if urgency == "critical" else "normal"
            try:
                proc = subprocess.run(
                    ["notify-send", "-u", u_flag, title, message],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
                if proc.returncode == 0:
                    return True
            except Exception as exc:
                logger.debug("notify-send failed: %s", exc)

        # 3. Windows PowerShell Toast / Balloon with safe parameter passing (no string interpolation)
        if os.name == "nt" or (sys.platform == "linux" and shutil.which("powershell.exe")):
            ps_exe = "powershell.exe" if sys.platform == "linux" else "powershell"
            script = """
            param([string]$Title, [string]$Message)
            [void] [System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms")
            $obj = New-Object System.Windows.Forms.NotifyIcon
            $obj.Icon = [System.Drawing.SystemIcons]::Information
            $obj.BalloonTipIcon = "Info"
            $obj.BalloonTipTitle = $Title
            $obj.BalloonTipText = $Message
            $obj.Visible = $True
            $obj.ShowBalloonTip(5000)
            """
            try:
                proc = subprocess.run(
                    [ps_exe, "-NoProfile", "-NonInteractive", "-Command", script, title, message],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=6,
                )
                if proc.returncode == 0:
                    return True
            except Exception as exc:
                logger.debug("Windows PowerShell toast notification failed: %s", exc)

        # 4. macOS via AppleScript
        if sys.platform == "darwin" and shutil.which("osascript"):
            try:
                proc = subprocess.run(
                    ["osascript", "-e", 'on run argv\ndisplay notification (item 2 of argv) with title (item 1 of argv)\nend run', title, message],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
                if proc.returncode == 0:
                    return True
            except Exception as exc:
                logger.debug("macOS notification failed: %s", exc)

        return False

    def notify(
        self,
        title: str,
        message: str,
        urgency: str = "normal",
        try_broker: bool = True,
    ) -> bool:
        """Send a notification via broker (preferred) or platform fallback with stable incident identity."""
        if not self.config.notifications_enabled:
            return False

        if try_broker and getattr(self.config, "use_notifications_broker", True):
            severity = "critical" if urgency == "critical" else ("warning" if urgency == "warning" else "info")
            digest = hashlib.sha256(f"{title}\x00{message}".encode("utf-8")).hexdigest()[:16]
            incident_key = f"scheduler:notify:{digest}"
            try:
                if self._publish_to_broker(
                    source="scheduler",
                    kind="generic_notify",
                    incident_key=incident_key,
                    severity=severity,
                    summary=f"{title}: {message}",
                    lifecycle="open",
                ):
                    return True
            except Exception as exc:
                logger.debug("Broker publication failed, falling back to platform notification: %s", exc)

        return self._notify_platform(title, message, urgency)

    def notify_schedule_trigger(self, schedule_name: str, task_count: int, is_catchup: bool = False) -> bool:
        """Notify on scheduled run triggers with deduplication."""
        if not self.config.notify_on_run:
            return False
        kind = "Catch-Up Run" if is_catchup else "Scheduled Run"
        title = f"Scheduler: {schedule_name}"
        message = f"{kind} triggered with {task_count} task(s)."

        if getattr(self.config, "use_notifications_broker", True):
            try:
                if self._publish_to_broker(
                    source="scheduler",
                    kind="schedule_trigger",
                    incident_key=f"scheduler:schedule:{schedule_name}",
                    severity="info",
                    summary=f"{title}: {message}",
                    lifecycle="open",
                    resource=schedule_name,
                    labels={"tasks": str(task_count), "catchup": str(is_catchup).lower()},
                ):
                    return True
            except Exception as exc:
                logger.debug("Broker publish for schedule trigger failed: %s", exc)

        # Fall back to platform notification without re-attempting broker (B2)
        return self.notify(title, message, urgency="normal", try_broker=False)

    def notify_task_result(self, result: ExecutionResult) -> bool:
        """Notify on task completion with automatic incident resolution on success."""
        if not self.config.notifications_enabled:
            return False

        if result.success:
            resolved_in_broker = False
            title = f"Task Succeeded: {result.task_name}"
            msg = f"Completed in {result.duration_sec:.2f}s with exit code 0."

            # B4: When broker tracking is enabled, successful recovery should resolve
            # existing failure incidents even when optional success alerts are disabled.
            if getattr(self.config, "use_notifications_broker", True):
                try:
                    resolved_in_broker = self._publish_to_broker(
                        source="scheduler",
                        kind="task_result",
                        incident_key=f"scheduler:task:{result.task_name}",
                        severity="info",
                        summary=f"{title}: {msg}",
                        lifecycle="resolve",
                        resource=result.task_name,
                        labels={
                            "schedule": result.schedule_name or "",
                            "exit_code": str(result.exit_code),
                            "duration_sec": f"{result.duration_sec:.2f}",
                        },
                    )
                except Exception as exc:
                    logger.debug("Broker publish for task success resolution failed: %s", exc)

            # If success notifications are disabled, suppress user alert without failing resolution
            if not self.config.notify_on_success:
                return resolved_in_broker

            if resolved_in_broker:
                return True

            # Direct fallback without re-attempting broker (B2)
            return self.notify(title, msg, urgency="normal", try_broker=False)
        else:
            if not self.config.notify_on_failure:
                return False
            title = f"Task Failed: {result.task_name}"
            raw_err = result.error_message or "check logs"
            sanitized_err = raw_err[:256].replace("\r", " ").replace("\n", " ").strip()
            msg = f"Failed with exit code {result.exit_code}: {sanitized_err}"

            if getattr(self.config, "use_notifications_broker", True):
                try:
                    if self._publish_to_broker(
                        source="scheduler",
                        kind="task_result",
                        incident_key=f"scheduler:task:{result.task_name}",
                        severity="critical",
                        summary=f"{title}: {msg}",
                        lifecycle="open",
                        resource=result.task_name,
                        labels={
                            "schedule": result.schedule_name or "",
                            "exit_code": str(result.exit_code),
                            "duration_sec": f"{result.duration_sec:.2f}",
                        },
                    ):
                        return True
                except Exception as exc:
                    logger.debug("Broker publish for task failure failed: %s", exc)

            # Direct fallback without re-attempting broker (B2)
            return self.notify(title, msg, urgency="critical", try_broker=False)
