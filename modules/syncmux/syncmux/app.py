
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.reactive import var
from textual.widgets import Footer, Header, Input, ListView, RichLog, Static

from .config import load_config
from .connection import ConnectionManager
from .models import Host, Session
from .tmux_controller import TmuxController
from .screens import ConfirmKillSessionScreen, ErrorDialog, HelpScreen, NewSessionScreen
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
        ("slash", "toggle_filter", "Filter Sessions"),
        ("s", "cycle_sort", "Cycle Sort"),
        ("question_mark,f1", "show_help", "Help"),
        ("q", "quit", "Quit"),
    ]

    hosts: var[List[Host]] = var([])
    sessions: var[Dict[str, List[Session]]] = var({})
    selected_host_alias: var[Optional[str]] = var(None)
    host_widgets: Dict[str, HostWidget] = {}
    filter_text: var[str] = var("")
    filter_visible: var[bool] = var(False)
    sort_mode: var[str] = var("name")  # name, created, windows, attached

    def compose(self) -> ComposeResult:
        """Compose the application."""
        yield Header()
        with Container(id="main-container"):
            yield ListView(id="host-list")
            with Vertical(id="session-panel"):
                with Container(id="filter-container", classes="hidden"):
                    yield Static("Filter:", id="filter-label")
                    yield Input(placeholder="Type to filter sessions...", id="filter-input")
                yield Static("", id="sort-indicator")
                yield ListView(id="session-list")
        yield RichLog(id="log-view")
        yield Footer()

    def _log(self, message: str, level: str = "info", show_dialog: bool = False) -> None:
        """Log a message with timestamp and optional level indicator.

        Args:
            message: The message to log
            level: The severity level (info, success, warning, error)
            show_dialog: If True and level is error, show a modal error dialog
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        log = self.query_one("#log-view", RichLog)

        # Add level prefix with emoji
        if level == "error":
            prefix = "❌"
        elif level == "success":
            prefix = "✅"
        elif level == "warning":
            prefix = "⚠️"
        else:
            prefix = "ℹ️"

        log.write(f"[{timestamp}] {prefix} {message}")

        # Show modal dialog for critical errors if requested
        if show_dialog and level == "error":
            self.push_screen(ErrorDialog("Error", message))

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
            self._log(f"Loaded {len(self.hosts)} hosts from configuration", "success")
            await self.action_refresh_all_hosts()
        except FileNotFoundError as e:
            self._log(str(e), "error", show_dialog=True)
        except ValueError as e:
            self._log(f"Configuration error: {e}", "error", show_dialog=True)

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
        self._update_session_list()

    def watch_filter_text(self, old_text: str, new_text: str) -> None:
        """Called when the filter text changes."""
        self._update_session_list()

    def watch_sort_mode(self, old_mode: str, new_mode: str) -> None:
        """Called when the sort mode changes."""
        self._update_session_list()
        # Update sort indicator if app is mounted
        if self.is_mounted:
            try:
                sort_indicator = self.query_one("#sort-indicator", Static)
                mode_display = {
                    "name": "Sort: Name (A-Z)",
                    "created": "Sort: Created (Newest First)",
                    "windows": "Sort: Window Count (Most First)",
                    "attached": "Sort: Attached Status"
                }
                sort_indicator.update(f"[dim]{mode_display.get(new_mode, '')}[/dim]")
            except Exception:
                pass  # Widget not available (e.g., during testing)

    def watch_filter_visible(self, old_visible: bool, new_visible: bool) -> None:
        """Called when filter visibility changes."""
        if not self.is_mounted:
            return

        try:
            filter_container = self.query_one("#filter-container", Container)
            filter_input = self.query_one("#filter-input", Input)

            if new_visible:
                filter_container.remove_class("hidden")
                filter_input.focus()
            else:
                filter_container.add_class("hidden")
                self.filter_text = ""  # Clear filter when hiding
                # Return focus to session list
                session_list = self.query_one("#session-list", ListView)
                session_list.focus()
        except Exception:
            pass  # Widgets not available (e.g., during testing)

    def _filter_sessions(self, sessions: List[Session]) -> List[Session]:
        """Filter sessions based on filter_text."""
        if not self.filter_text:
            return sessions

        filter_lower = self.filter_text.lower()
        return [s for s in sessions if filter_lower in s.name.lower()]

    def _sort_sessions(self, sessions: List[Session]) -> List[Session]:
        """Sort sessions based on sort_mode."""
        if self.sort_mode == "name":
            return sorted(sessions, key=lambda s: s.name.lower())
        elif self.sort_mode == "created":
            return sorted(sessions, key=lambda s: s.created_at, reverse=True)
        elif self.sort_mode == "windows":
            return sorted(sessions, key=lambda s: s.windows, reverse=True)
        elif self.sort_mode == "attached":
            return sorted(sessions, key=lambda s: s.attached, reverse=True)
        return sessions

    def _update_session_list(self) -> None:
        """Update the session list with filtered and sorted sessions."""
        if not self.is_mounted or not self.selected_host_alias:
            return

        try:
            session_list = self.query_one("#session-list", ListView)
            session_list.clear()

            sessions = self.sessions.get(self.selected_host_alias, [])
            filtered_sessions = self._filter_sessions(sessions)
            sorted_sessions = self._sort_sessions(filtered_sessions)

            for session in sorted_sessions:
                session_list.append(SessionWidget(session))
        except Exception:
            pass  # Widget not available (e.g., during testing)

    def action_toggle_filter(self) -> None:
        """Toggle the filter input visibility."""
        self.filter_visible = not self.filter_visible

    def action_cycle_sort(self) -> None:
        """Cycle through sort modes."""
        sort_modes = ["name", "created", "windows", "attached"]
        current_index = sort_modes.index(self.sort_mode)
        next_index = (current_index + 1) % len(sort_modes)
        self.sort_mode = sort_modes[next_index]
        self._log(f"Sort mode: {self.sort_mode}", "info")

    @on(Input.Changed, "#filter-input")
    def on_filter_input_changed(self, event: Input.Changed) -> None:
        """Handle changes to the filter input."""
        self.filter_text = event.value

    async def on_key(self, event) -> None:
        """Handle key events for escape key when filter is focused."""
        if event.key == "escape" and self.filter_visible:
            filter_input = self.query_one("#filter-input", Input)
            if self.focused == filter_input:
                self.filter_visible = False
                event.prevent_default()
                event.stop()

    async def action_refresh_host(self) -> None:
        """Refreshes the sessions for the selected host."""
        if self.selected_host_alias:
            host = next((h for h in self.hosts if h.alias == self.selected_host_alias), None)
            if host:
                self._log(f"Refreshing sessions for {host.alias}...", "info")
                # Update status to connecting
                if self.selected_host_alias in self.host_widgets:
                    self.host_widgets[self.selected_host_alias].set_status_connecting()
                try:
                    conn = await self.conn_manager.get_connection(host)
                    sessions = await self.tmux_controller.list_sessions(conn)
                    self.sessions = {**self.sessions, self.selected_host_alias: sessions}
                    self._log(f"Found {len(sessions)} sessions for {host.alias}", "success")
                    # Update status to connected and session count
                    if self.selected_host_alias in self.host_widgets:
                        self.host_widgets[self.selected_host_alias].set_status_connected()
                        self.host_widgets[self.selected_host_alias].update_session_count(len(sessions))
                except ConnectionError as e:
                    self._log(str(e), "error")
                    # Update status to error and reset session count
                    if self.selected_host_alias in self.host_widgets:
                        self.host_widgets[self.selected_host_alias].set_status_error()
                        self.host_widgets[self.selected_host_alias].update_session_count(0)

    async def _refresh_single_host(self, host: Host) -> tuple[str, List[Session] | None]:
        """Refresh sessions for a single host. Returns (alias, sessions or None)."""
        # Update status to connecting
        if host.alias in self.host_widgets:
            self.host_widgets[host.alias].set_status_connecting()

        try:
            conn = await self.conn_manager.get_connection(host)

            # Check if tmux is available before trying to list sessions
            is_available, tmux_message = await self.tmux_controller.check_tmux_available(conn)
            if not is_available:
                self._log(f"{host.alias}: {tmux_message} - Install tmux to manage sessions", "warning")
                if host.alias in self.host_widgets:
                    self.host_widgets[host.alias].set_status_error()
                    self.host_widgets[host.alias].update_session_count(0)
                return (host.alias, [])  # Return empty list, not None (tmux missing, not connection failed)

            sessions = await self.tmux_controller.list_sessions(conn)
            self._log(f"Found {len(sessions)} sessions for {host.alias}", "success")

            # Update status to connected and session count
            if host.alias in self.host_widgets:
                self.host_widgets[host.alias].set_status_connected()
                self.host_widgets[host.alias].update_session_count(len(sessions))

            return (host.alias, sessions)
        except ConnectionError as e:
            self._log(str(e), "error")
            # Update status to error and reset session count
            if host.alias in self.host_widgets:
                self.host_widgets[host.alias].set_status_error()
                self.host_widgets[host.alias].update_session_count(0)
            return (host.alias, None)

    async def action_refresh_all_hosts(self) -> None:
        """Refreshes the sessions for all hosts concurrently."""
        import asyncio

        self._log(f"Refreshing all {len(self.hosts)} hosts...", "info")

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
        self._log("All hosts refreshed", "success")

    
    async def action_create_session(self) -> None:
        """Creates a new session on the selected host."""
        if self.selected_host_alias:
            host = next((h for h in self.hosts if h.alias == self.selected_host_alias), None)
            if host:
                async def create_session_callback(name: Optional[str]) -> None:
                    if name:
                        async def _create_session() -> None:
                            self._log(f"Creating session '{name}' on {host.alias}...", "info")
                            try:
                                conn = await self.conn_manager.get_connection(host)
                                success = await self.tmux_controller.create_session(conn, name)
                                if success:
                                    self._log(f"Session '{name}' created successfully", "success")
                                    await self.action_refresh_host()
                                else:
                                    self._log(f"Failed to create session '{name}'", "error")
                            except ConnectionError as e:
                                self._log(str(e), "error")
                            except ValueError as e:
                                self._log(f"Invalid session name: {e}", "error")
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
                            self._log(f"Killing session '{session.name}' on {host.alias}...", "info")
                            try:
                                conn = await self.conn_manager.get_connection(host)
                                success = await self.tmux_controller.kill_session(conn, session.name)
                                if success:
                                    self._log(f"Session '{session.name}' killed successfully", "success")
                                    await self.action_refresh_host()
                                else:
                                    self._log(f"Failed to kill session '{session.name}'", "error")
                            except ConnectionError as e:
                                self._log(str(e), "error")
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

    def action_show_help(self) -> None:
        """Show the keyboard shortcuts help screen."""
        self.push_screen(HelpScreen())

    async def on_unmount(self) -> None:
        """Called when the app is unmounted."""
        await self.conn_manager.close_all()


if __name__ == "__main__":
    app = SyncMuxApp()
    app.run()
