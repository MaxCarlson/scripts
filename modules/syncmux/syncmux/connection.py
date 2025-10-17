
import asyncio
import errno

import asyncssh

from .models import Host


class ConnectionManager:
    """Manages SSH connections."""

    def __init__(self):
        self._connections = {}
        self._lock = asyncio.Lock()

    def _get_error_message(self, host: Host, error: Exception) -> str:
        """Generate a user-friendly error message based on the error type."""
        error_str = str(error).lower()

        # Authentication failures
        if isinstance(error, asyncssh.PermissionDenied) or "permission denied" in error_str:
            if host.auth_method == "key":
                return f"❌ Authentication failed for {host.alias}: Check your SSH key at {host.key_path}"
            elif host.auth_method == "password":
                return f"❌ Authentication failed for {host.alias}: Invalid password"
            else:
                return f"❌ Authentication failed for {host.alias}: SSH agent not available or no valid keys"

        # Connection refused
        if isinstance(error, ConnectionRefusedError) or "connection refused" in error_str:
            return f"❌ Connection refused by {host.alias} ({host.hostname}:{host.port}): SSH server may be down"

        # Host unreachable/timeout
        if isinstance(error, asyncio.TimeoutError) or "timeout" in error_str:
            return f"❌ Connection to {host.alias} timed out: Host may be unreachable or network is slow"

        # Host not found
        if isinstance(error, OSError) and error.errno == errno.ENOENT:
            return f"❌ Host {host.alias} not found: Check hostname '{host.hostname}'"

        # Network unreachable
        if "network is unreachable" in error_str or "no route to host" in error_str:
            return f"❌ Network unreachable for {host.alias}: Check your network connection"

        # Key file not found
        if "no such file" in error_str and host.auth_method == "key":
            return f"❌ SSH key not found for {host.alias}: {host.key_path} does not exist"

        # Generic error with the original message
        return f"❌ Failed to connect to {host.alias}: {error}"

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
                    connect_timeout=10.0,  # 10 second timeout
                )
                self._connections[host.alias] = conn
                return conn
            except (asyncssh.Error, OSError, asyncio.TimeoutError) as e:
                error_msg = self._get_error_message(host, e)
                raise ConnectionError(error_msg)

    async def close_all(self):
        """Closes all cached connections."""
        async with self._lock:
            for conn in self._connections.values():
                conn.close()
            self._connections.clear()
