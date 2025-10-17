
import os
import sys
from typing import Dict, List, Optional

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.reactive import var
from textual.widgets import Footer, Header, ListView, RichLog

from .config import load_config
from .connection import ConnectionManager
from .models import Host, Session
from .tmux_controller import TmuxController
from .screens import ConfirmKillSessionScreen, NewSessionScreen
from .widgets import HostWidget, SessionWidget


class SyncMuxApp(App):
    """A centralized, cross-device tmux session manager."""

    CSS_PATH = "app.css"

    BINDINGS = [
        ("j", "cursor_down", "Cursor Down"),
        ("k", "cursor_up", "Cursor Up"),
        ("tab", "switch_list", "Switch List"),
        ("enter", "select_item", "Select"),
        ("n", "create_session", "New Session"),
        ("d", "kill_session", "Kill Session"),
        ("r", "refresh_host", "Refresh Host"),
        ("ctrl+r", "refresh_all_hosts", "Refresh All"),
        ("q", "quit", "Quit"),
    ]

    hosts: var[List[Host]] = var([])
    sessions: var[Dict[str, List[Session]]] = var({})
    selected_host_alias: var[Optional[str]] = var(None)
    host_widgets: Dict[str, HostWidget] = {}

    def compose(self) -> ComposeResult:
        """Compose the application."""
        yield Header()
        with Container():
            yield ListView(id="host-list")
            yield ListView(id="session-list")
        yield RichLog(id="log-view")
        yield Footer()

    async def on_mount(self) -> None:
        """Called when the app is mounted."""
        self.conn_manager = ConnectionManager()
        self.tmux_controller = TmuxController()
        try:
            self.hosts = load_config()
            host_list = self.query_one("#host-list", ListView)
            for host in self.hosts:
                widget = HostWidget(host)
                self.host_widgets[host.alias] = widget
                host_list.append(widget)
            # Set initial focus on host list
            host_list.focus()
            await self.action_refresh_all_hosts()
        except (FileNotFoundError, ValueError) as e:
            self.query_one("#log-view", RichLog).write(str(e))

    def action_cursor_down(self) -> None:
        """Move the cursor down in the focused list view."""
        focused = self.focused
        if focused and isinstance(focused, ListView):
            focused.action_cursor_down()

    def action_cursor_up(self) -> None:
        """Move the cursor up in the focused list view."""
        focused = self.focused
        if focused and isinstance(focused, ListView):
            focused.action_cursor_up()

    def action_switch_list(self) -> None:
        """Switch focus between host and session lists."""
        host_list = self.query_one("#host-list", ListView)
        session_list = self.query_one("#session-list", ListView)

        if self.focused == host_list:
            session_list.focus()
        else:
            host_list.focus()

    async def action_select_item(self) -> None:
        """Select an item in the focused list view."""
        # Get the focused widget
        focused = self.focused
        if focused is None:
            return

        # If host list is focused, select the host
        if focused.id == "host-list":
            host_list = self.query_one("#host-list", ListView)
            if host_list.highlighted is not None:
                self.selected_host_alias = host_list.highlighted.host.alias

        # If session list is focused, attach to the session
        elif focused.id == "session-list":
            await self.action_attach_session()

    async def watch_selected_host_alias(self, old_alias: Optional[str], new_alias: Optional[str]) -> None:
        """Called when the selected host alias changes."""
        if new_alias:
            await self.action_refresh_host()

    def watch_sessions(self) -> None:
        """Called when the sessions dictionary changes."""
        if self.selected_host_alias:
            session_list = self.query_one("#session-list", ListView)
            session_list.clear()
            for session in self.sessions.get(self.selected_host_alias, []):
                session_list.append(SessionWidget(session))

    async def action_refresh_host(self) -> None:
        """Refreshes the sessions for the selected host."""
        if self.selected_host_alias:
            log = self.query_one("#log-view", RichLog)
            host = next((h for h in self.hosts if h.alias == self.selected_host_alias), None)
            if host:
                log.write(f"Refreshing sessions for {host.alias}...")
                # Update status to connecting
                if self.selected_host_alias in self.host_widgets:
                    self.host_widgets[self.selected_host_alias].set_status_connecting()
                try:
                    conn = await self.conn_manager.get_connection(host)
                    sessions = await self.tmux_controller.list_sessions(conn)
                    self.sessions = {**self.sessions, self.selected_host_alias: sessions}
                    log.write(f"Found {len(sessions)} sessions for {host.alias}.")
                    # Update status to connected and session count
                    if self.selected_host_alias in self.host_widgets:
                        self.host_widgets[self.selected_host_alias].set_status_connected()
                        self.host_widgets[self.selected_host_alias].update_session_count(len(sessions))
                except ConnectionError as e:
                    log.write(str(e))
                    # Update status to error and reset session count
                    if self.selected_host_alias in self.host_widgets:
                        self.host_widgets[self.selected_host_alias].set_status_error()
                        self.host_widgets[self.selected_host_alias].update_session_count(0)

    async def _refresh_single_host(self, host: Host) -> tuple[str, List[Session] | None]:
        """Refresh sessions for a single host. Returns (alias, sessions or None)."""
        log = self.query_one("#log-view", RichLog)

        # Update status to connecting
        if host.alias in self.host_widgets:
            self.host_widgets[host.alias].set_status_connecting()

        try:
            conn = await self.conn_manager.get_connection(host)
            sessions = await self.tmux_controller.list_sessions(conn)
            log.write(f"Found {len(sessions)} sessions for {host.alias}.")

            # Update status to connected and session count
            if host.alias in self.host_widgets:
                self.host_widgets[host.alias].set_status_connected()
                self.host_widgets[host.alias].update_session_count(len(sessions))

            return (host.alias, sessions)
        except ConnectionError as e:
            log.write(str(e))
            # Update status to error and reset session count
            if host.alias in self.host_widgets:
                self.host_widgets[host.alias].set_status_error()
                self.host_widgets[host.alias].update_session_count(0)
            return (host.alias, None)

    async def action_refresh_all_hosts(self) -> None:
        """Refreshes the sessions for all hosts concurrently."""
        import asyncio

        log = self.query_one("#log-view", RichLog)
        log.write("Refreshing all hosts...")

        # Refresh all hosts concurrently
        results = await asyncio.gather(
            *[self._refresh_single_host(host) for host in self.hosts],
            return_exceptions=False
        )

        # Update sessions dict with results
        new_sessions = {}
        for alias, sessions in results:
            if sessions is not None:
                new_sessions[alias] = sessions

        self.sessions = {**self.sessions, **new_sessions}

    
    async def action_create_session(self) -> None:
        """Creates a new session on the selected host."""
        if self.selected_host_alias:
            host = next((h for h in self.hosts if h.alias == self.selected_host_alias), None)
            if host:
                async def create_session_callback(name: Optional[str]) -> None:
                    if name:
                        async def _create_session() -> None:
                            log = self.query_one("#log-view", RichLog)
                            log.write(f"Creating session '{name}' on {host.alias}...")
                            try:
                                conn = await self.conn_manager.get_connection(host)
                                success = await self.tmux_controller.create_session(conn, name)
                                if success:
                                    log.write(f"Session '{name}' created successfully.")
                                    await self.action_refresh_host()
                                else:
                                    log.write(f"Failed to create session '{name}'.")
                            except ConnectionError as e:
                                log.write(str(e))
                        self.call_later(_create_session)

                self.push_screen(NewSessionScreen(), create_session_callback)


    
    async def action_kill_session(self) -> None:
        """Kills the selected session."""
        if self.selected_host_alias:
            host = next((h for h in self.hosts if h.alias == self.selected_host_alias), None)
            session_list = self.query_one("#session-list", ListView)
            if host and session_list.highlighted is not None:
                session = session_list.highlighted.session

                def kill_session_callback(confirm: bool) -> None:
                    if confirm:
                        async def _kill_session() -> None:
                            log = self.query_one("#log-view", RichLog)
                            log.write(f"Killing session '{session.name}' on {host.alias}...")
                            try:
                                conn = await self.conn_manager.get_connection(host)
                                success = await self.tmux_controller.kill_session(conn, session.name)
                                if success:
                                    log.write(f"Session '{session.name}' killed successfully.")
                                    await self.action_refresh_host()
                                else:
                                    log.write(f"Failed to kill session '{session.name}'.")
                            except ConnectionError as e:
                                log.write(str(e))
                        self.call_later(_kill_session)

                self.push_screen(
                    ConfirmKillSessionScreen(session.name), kill_session_callback
                )


    def _get_ssh_command(self, host: Host, session_name: str) -> list[str]:
        """Construct platform-specific SSH command for attaching to a session."""
        # Detect platform
        is_windows = sys.platform == "win32"
        is_termux = os.path.exists("/data/data/com.termux")

        # Base SSH arguments
        ssh_args = [
            f"{host.user}@{host.hostname}",
            "-p",
            str(host.port),
            "-t",  # Force pseudo-tty allocation
            "tmux",
            "attach-session",
            "-t",
            session_name,
        ]

        if is_windows:
            # On Windows, use full path to ssh.exe
            # Try common locations
            ssh_path = "ssh"  # Default to PATH
            for candidate in [
                r"C:\Windows\System32\OpenSSH\ssh.exe",
                r"C:\Program Files\Git\usr\bin\ssh.exe",
            ]:
                if os.path.exists(candidate):
                    ssh_path = candidate
                    break
            return [ssh_path] + ssh_args
        else:
            # Unix-like systems (Linux, WSL, Termux)
            return ["ssh"] + ssh_args

    async def action_attach_session(self) -> None:
        """Attaches to the selected session."""
        if self.selected_host_alias:
            host = next((h for h in self.hosts if h.alias == self.selected_host_alias), None)
            session_list = self.query_one("#session-list", ListView)
            if host and session_list.highlighted is not None:
                session = session_list.highlighted.session
                await self.app.exit()

                # Get platform-specific SSH command
                cmd = self._get_ssh_command(host, session.name)

                # Replace current process with SSH
                os.execvp(cmd[0], cmd)

    async def on_unmount(self) -> None:
        """Called when the app is unmounted."""
        await self.conn_manager.close_all()


if __name__ == "__main__":
    app = SyncMuxApp()
    app.run()
