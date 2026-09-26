"""
Cross-platform system notification hook.
Dispatches desktop/system notifications on schedule runs, task completions, and failures.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Optional

from .config import SchedulerConfig
from .models import ExecutionResult


class Notifier:
    """Dispatches system notifications across Linux, Windows, macOS, and Termux."""

    def __init__(self, config: Optional[SchedulerConfig] = None) -> None:
        self.config = config or SchedulerConfig()

    def update_config(self, config: SchedulerConfig) -> None:
        self.config = config

    def notify(self, title: str, message: str, urgency: str = "normal") -> bool:
        """Send a system notification if enabled."""
        if not self.config.notifications_enabled:
            return False

        # 1. Termux
        if shutil.which("termux-notification"):
            try:
                subprocess.run(
                    ["termux-notification", "--title", title, "--content", message],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
                return True
            except Exception:
                pass

        # 2. Linux / BSD / X11 desktop via notify-send
        if shutil.which("notify-send") and os.environ.get("DISPLAY"):
            u_flag = "critical" if urgency == "critical" else "normal"
            try:
                subprocess.run(
                    ["notify-send", "-u", u_flag, title, message],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
                return True
            except Exception:
                pass

        # 3. Windows PowerShell Toast / Balloon
        if os.name == "nt" or (sys.platform == "linux" and shutil.which("powershell.exe")):
            ps_exe = "powershell.exe" if sys.platform == "linux" else "powershell"
            script = f'''
            [void] [System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms");
            $obj = New-Object System.Windows.Forms.NotifyIcon;
            $obj.Icon = [System.Drawing.SystemIcons]::Information;
            $obj.BalloonTipIcon = "Info";
            $obj.BalloonTipTitle = "{title}";
            $obj.BalloonTipText = "{message}";
            $obj.Visible = $True;
            $obj.ShowBalloonTip(5000);
            '''
            try:
                subprocess.run(
                    [ps_exe, "-NoProfile", "-NonInteractive", "-Command", script],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=6,
                )
                return True
            except Exception:
                pass

        # 4. macOS via AppleScript
        if sys.platform == "darwin" and shutil.which("osascript"):
            script = f'display notification "{message}" with title "{title}"'
            try:
                subprocess.run(
                    ["osascript", "-e", script],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
                return True
            except Exception:
                pass

        return False

    def notify_schedule_trigger(self, schedule_name: str, task_count: int, is_catchup: bool = False) -> bool:
        if not self.config.notify_on_run:
            return False
        kind = "Catch-Up Run" if is_catchup else "Scheduled Run"
        title = f"Scheduler: {schedule_name}"
        message = f"{kind} triggered with {task_count} task(s)."
        return self.notify(title, message, urgency="normal")

    def notify_task_result(self, result: ExecutionResult) -> bool:
        if result.success:
            if not self.config.notify_on_success:
                return False
            title = f"Task Succeeded: {result.task_name}"
            msg = f"Completed in {result.duration_sec:.2f}s with exit code 0."
            return self.notify(title, msg, urgency="normal")
        else:
            if not self.config.notify_on_failure:
                return False
            title = f"Task Failed: {result.task_name}"
            msg = f"Failed with exit code {result.exit_code}: {result.error_message or 'check logs'}"
            return self.notify(title, msg, urgency="critical")
