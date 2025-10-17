
import asyncio
from datetime import datetime
from typing import List

import asyncssh

from .models import Session


class TmuxController:
    """Interacts with remote tmux servers."""

    FORMAT = "#{session_id}|#{session_name}|#{session_windows}|#{session_attached}|#{session_created}"

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
        command = f"tmux new-session -d -s {name}"
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
