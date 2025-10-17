
import asyncio

import asyncssh

from .models import Host


class ConnectionManager:
    """Manages SSH connections."""

    def __init__(self):
        self._connections = {}
        self._lock = asyncio.Lock()

    async def get_connection(self, host: Host) -> asyncssh.SSHClientConnection:
        """Gets a cached SSH connection or creates a new one."""
        async with self._lock:
            if host.alias in self._connections and not self._connections[host.alias].is_closed():
                return self._connections[host.alias]

            try:
                conn = await asyncssh.connect(
                    host.hostname,
                    port=host.port,
                    username=host.user,
                    password=host.password if host.auth_method == "password" else None,
                    client_keys=[host.key_path] if host.auth_method == "key" else None,
                    agent_forwarding=True if host.auth_method == "agent" else False,
                )
                self._connections[host.alias] = conn
                return conn
            except (asyncssh.Error, OSError) as e:
                raise ConnectionError(f"Failed to connect to {host.alias}: {e}")

    async def close_all(self):
        """Closes all cached connections."""
        async with self._lock:
            for conn in self._connections.values():
                conn.close()
            self._connections.clear()
