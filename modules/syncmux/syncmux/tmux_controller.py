
import asyncio
import re
from datetime import datetime
from typing import List

import asyncssh

from .models import Session


class TmuxController:
    """Interacts with remote tmux servers."""

    FORMAT = "#{session_id}|#{session_name}|#{session_windows}|#{session_attached}|#{session_created}"

    async def check_tmux_available(self, conn: asyncssh.SSHClientConnection) -> tuple[bool, str]:
        """Check if tmux is installed and accessible on the remote host.

        Returns:
            tuple: (is_available: bool, message: str)
        """
        try:
            # Try to get tmux version
            result = await conn.run("tmux -V", check=False)

            if result.exit_status == 0:
                version = result.stdout.strip()
                return (True, f"tmux is available: {version}")
            else:
                return (False, "tmux command found but returned an error")

        except asyncssh.ProcessError:
            return (False, "tmux is not installed on this host")
        except Exception as e:
            return (False, f"Error checking tmux availability: {e}")

    @staticmethod
    def sanitize_session_name(name: str) -> str:
        """Sanitize and validate a session name.

        Session names must:
        - Not be empty
        - Not contain colons, dots, or special characters that could cause issues
        - Be reasonable length (max 100 chars)

        Returns the sanitized name.
        Raises ValueError if the name is invalid.
        """
        if not name or not name.strip():
            raise ValueError("Session name cannot be empty")

        name = name.strip()

        if len(name) > 100:
            raise ValueError("Session name too long (max 100 characters)")

        # Check for problematic characters
        if re.search(r'[:\.]', name):
            raise ValueError("Session name cannot contain colons or dots")

        # Allow alphanumeric, underscore, hyphen, and spaces
        if not re.match(r'^[a-zA-Z0-9_\-\s]+$', name):
            raise ValueError("Session name contains invalid characters (only letters, numbers, -, _, and spaces allowed)")

        # Replace spaces with underscores for better shell compatibility
        name = name.replace(' ', '_')

        return name

    async def list_sessions(self, conn: asyncssh.SSHClientConnection) -> List[Session]:
        """Lists all tmux sessions on a host."""
        command = f'tmux list-sessions -F "{self.FORMAT}"'
        try:
            result = await conn.run(command)
        except asyncssh.ProcessError as e:
            # Tmux not running or other error
            return []

        if result.exit_status != 0:
            return []

        sessions = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                session_id, name, windows, attached, created = line.split("|")
                sessions.append(
                    Session(
                        id=session_id,
                        name=name,
                        windows=int(windows),
                        attached=int(attached),
                        created_at=datetime.fromtimestamp(int(created)),
                    )
                )
            except (ValueError, TypeError):
                # Ignore malformed lines
                continue
        return sessions

    async def create_session(self, conn: asyncssh.SSHClientConnection, name: str) -> bool:
        """Creates a new tmux session."""
        # Sanitize the session name
        sanitized_name = self.sanitize_session_name(name)
        command = f"tmux new-session -d -s {sanitized_name}"
        try:
            result = await conn.run(command)
            return result.exit_status == 0
        except asyncssh.ProcessError:
            return False

    async def kill_session(self, conn: asyncssh.SSHClientConnection, target: str) -> bool:
        """Kills a tmux session."""
        command = f"tmux kill-session -t {target}"
        try:
            result = await conn.run(command)
            return result.exit_status == 0
        except asyncssh.ProcessError:
            return False

    async def session_exists(self, conn: asyncssh.SSHClientConnection, name: str) -> bool:
        """Checks if a tmux session exists."""
        command = f"tmux has-session -t {name}"
        try:
            result = await conn.run(command)
            return result.exit_status == 0
        except asyncssh.ProcessError:
            return False

    async def rename_session(self, conn: asyncssh.SSHClientConnection, old_name: str, new_name: str) -> bool:
        """Renames a tmux session.

        Args:
            conn: SSH connection
            old_name: Current session name
            new_name: New session name

        Returns:
            True if rename was successful, False otherwise
        """
        # Sanitize the new session name
        sanitized_name = self.sanitize_session_name(new_name)
        command = f"tmux rename-session -t {old_name} {sanitized_name}"
        try:
            result = await conn.run(command)
            return result.exit_status == 0
        except asyncssh.ProcessError:
            return False

    async def list_windows(self, conn: asyncssh.SSHClientConnection, session_name: str) -> List[str]:
        """Lists window names for a given session.

        Args:
            conn: SSH connection
            session_name: Name of the session

        Returns:
            List of window names (e.g., ["vim", "shell", "logs"])
        """
        command = f'tmux list-windows -t {session_name} -F "#{window_name}"'
        try:
            result = await conn.run(command)
            if result.exit_status == 0:
                windows = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
                return windows
            return []
        except asyncssh.ProcessError:
            return []
