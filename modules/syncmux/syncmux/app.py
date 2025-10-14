
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
from .widgets import HostWidget, SessionWidget


class SyncMuxApp(App):
    """A centralized, cross-device tmux session manager."""

    CSS_PATH = "app.css"

    BINDINGS = [
        ("j", "cursor_down", "Cursor Down"),
        ("k", "cursor_up", "Cursor Up"),
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
                host_list.append(HostWidget(host))
            await self.action_refresh_all_hosts()
        except (FileNotFoundError, ValueError) as e:
            self.query_one("#log-view", RichLog).write(str(e))

    @on(ListView.Selected)
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Called when a list view item is selected."""
        if event.list_view.id == "host-list":
            self.selected_host_alias = event.item.host.alias

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
                try:
                    conn = await self.conn_manager.get_connection(host)
                    sessions = await self.tmux_controller.list_sessions(conn)
                    self.sessions = {**self.sessions, self.selected_host_alias: sessions}
                    log.write(f"Found {len(sessions)} sessions for {host.alias}.")
                except ConnectionError as e:
                    log.write(str(e))

    async def action_refresh_all_hosts(self) -> None:
        """Refreshes the sessions for all hosts."""
        log = self.query_one("#log-view", RichLog)
        log.write("Refreshing all hosts...")
        for host in self.hosts:
            try:
                conn = await self.conn_manager.get_connection(host)
                sessions = await self.tmux_controller.list_sessions(conn)
                self.sessions = {**self.sessions, host.alias: sessions}
                log.write(f"Found {len(sessions)} sessions for {host.alias}.")
            except ConnectionError as e:
                log.write(str(e))

    async def action_create_session(self) -> None:
        """Creates a new session on the selected host."""
        # This will be implemented later, as it requires a dialog.
        pass

    async def action_kill_session(self) -> None:
        """Kills the selected session."""
        # This will be implemented later, as it requires a dialog.
        pass

    async def action_attach_session(self) -> None:
        """Attaches to the selected session."""
        if self.selected_host_alias:
            host = next((h for h in self.hosts if h.alias == self.selected_host_alias), None)
            session_list = self.query_one("#session-list", ListView)
            if host and session_list.highlighted is not None:
                session = session_list.highlighted.session
                await self.app.exit()
                cmd = [
                    "ssh",
                    f"{host.user}@{host.hostname}",
                    "-p",
                    str(host.port),
                    "-t",
                    "tmux",
                    "attach-session",
                    "-t",
                    session.name,
                ]
                os.execvp(cmd[0], cmd)

    async def on_unmount(self) -> None:
        """Called when the app is unmounted."""
        await self.conn_manager.close_all()


if __name__ == "__main__":
    app = SyncMuxApp()
    app.run()
