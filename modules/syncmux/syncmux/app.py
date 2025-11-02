
import os
import pathlib
import sys
from datetime import datetime
from typing import Dict, List, Optional

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.reactive import var
from textual.widgets import Footer, Header, Input, ListView, RichLog, Static

from .config import load_config, save_config
from .connection import ConnectionManager
from .models import Host, Session
from .tmux_controller import TmuxController
from .screens import (
    AddMachineScreen,
    ConfirmKillSessionScreen,
    ErrorDialog,
    FirstRunPrompt,
    HelpScreen,
    NewSessionScreen,
    RenameSessionScreen,
    SessionInfoScreen,
)
from .widgets import HostWidget, SessionWidget


class SyncMuxApp(App):
    """A centralized, cross-device tmux session manager."""

    CSS_PATH = "app.css"

    BINDINGS = [
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("tab", "switch_list", "Switch"),
        ("enter", "select_item", "Select"),
        ("n", "create_session", "New"),
        ("d", "kill_session", "Kill"),
        ("e", "rename_session", "Rename"),
        ("i", "show_session_info", "Info"),
        ("r", "refresh_host", "Refresh"),
        ("a", "refresh_all_hosts", "Refresh All"),
        ("p", "toggle_auto_refresh", "Auto"),
        ("equals", "increase_refresh_interval", "+Time"),
        ("minus", "decrease_refresh_interval", "-Time"),
        ("slash,f", "toggle_filter", "Filter"),
        ("s", "cycle_sort", "Sort"),
        ("h,question_mark", "show_help", "Help"),
        ("q", "quit", "Quit"),
    ]

    hosts: var[List[Host]] = var([])
    sessions: var[Dict[str, List[Session]]] = var({})
    selected_host_alias: var[Optional[str]] = var(None)
    host_widgets: Dict[str, HostWidget] = {}
    filter_text: var[str] = var("")
    filter_visible: var[bool] = var(False)
    sort_mode: var[str] = var("name")  # name, created, windows, attached
    auto_refresh_enabled: var[bool] = var(False)
    auto_refresh_interval: var[int] = var(30)  # seconds
    auto_refresh_countdown: var[int] = var(0)

    def __init__(self, config_path: Optional[pathlib.Path] = None):
        """
        Initialize the SyncMux application.

        Args:
            config_path: Optional path to config file. If None, uses platform default.
        """
        super().__init__()
        self.config_path = config_path

    def compose(self) -> ComposeResult:
        """Compose the application."""
        yield Header()
        with Container(id="main-container"):
            yield ListView(id="host-list")
            with Vertical(id="session-panel"):
                with Container(id="filter-container", classes="hidden"):
                    yield Static("Filter:", id="filter-label")
                    yield Input(placeholder="Type to filter sessions...", id="filter-input")
                with Container(id="refresh-indicator-container"):
                    yield Static("", id="sort-indicator")
                    yield Static("", id="auto-refresh-indicator")
                yield ListView(id="session-list")
        yield RichLog(id="log-view")
        yield Footer()

    def _log(self, message: str, level: str = "info", show_dialog: bool = False) -> None:
        """Log a message with timestamp and optional level indicator.

        Args:
            message: The message to log
            level: The severity level (info, success, warning, error)
            show_dialog: If True and level is error, show_dialog a modal error dialog
        """
        # Try to get log view, but silently fail if widgets aren't ready yet
        try:
            log = self.query_one("#log-view", RichLog)
        except Exception:
            # Widgets not available yet (during initialization)
            return

        timestamp = datetime.now().strftime("%H:%M:%S")

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
            self.hosts = load_config(self.config_path)
            host_list = self.query_one("#host-list", ListView)
            for host in self.hosts:
                widget = HostWidget(host)
                self.host_widgets[host.alias] = widget
                host_list.append(widget)
            # Set initial focus on host list and select first host
            self.set_focus(host_list)
            if len(self.hosts) > 0:
                host_list.index = 0
                self.selected_host_alias = self.hosts[0].alias
            self._log(f"✅ {len(self.hosts)} hosts loaded. Press J/K to navigate, ENTER to select", "success")
            self.notify("🎯 HOST LIST ACTIVE - Press J/K to navigate", title="Ready!", timeout=5)
            await self.action_refresh_all_hosts()

            # First-run: Check if only localhost exists
            if len(self.hosts) == 1 and self.hosts[0].alias == "localhost":
                self._show_first_run_prompt()
        except FileNotFoundError as e:
            self._log(str(e), "error", show_dialog=True)
        except ValueError as e:
            self._log(f"Configuration error: {e}", "error", show_dialog=True)

        # Start the auto-refresh timer (runs every second to update countdown)
        self.set_interval(1.0, self._auto_refresh_tick)

    def action_cursor_down(self) -> None:
        """Move the cursor down in the focused list view."""
        focused = self.focused
        if focused and isinstance(focused, ListView):
            focused.action_cursor_down()
            self._log("↓", "info")
            self.notify("↓ Down", timeout=1)
        else:
            self._log("❌ No list focused - press TAB", "warning")
            self.notify("❌ No list focused - press TAB", timeout=2)

    def action_cursor_up(self) -> None:
        """Move the cursor up in the focused list view."""
        focused = self.focused
        if focused and isinstance(focused, ListView):
            focused.action_cursor_up()
            self._log("↑", "info")
            self.notify("↑ Up", timeout=1)
        else:
            self._log("❌ No list focused - press TAB", "warning")
            self.notify("❌ No list focused - press TAB", timeout=2)

    def action_switch_list(self) -> None:
        """Switch focus between host and session lists."""
        host_list = self.query_one("#host-list", ListView)
        session_list = self.query_one("#session-list", ListView)

        if self.focused == host_list:
            session_list.focus()
            self._log("🎯 Switched to SESSIONS list", "info")
            self.notify("🎯 SESSIONS list active", timeout=2)
        else:
            host_list.focus()
            self._log("🎯 Switched to HOSTS list", "info")
            self.notify("🎯 HOSTS list active", timeout=2)

    async def action_select_item(self) -> None:
        """Select an item in the focused list view."""
        # Get the focused widget
        focused = self.focused
        if focused is None:
            msg = "❌ Nothing selected. Press TAB to switch lists"
            self._log(msg, "warning")
            self.notify(msg, severity="warning", timeout=3)
            return

        # If host list is focused, select the host
        if focused.id == "host-list":
            host_list = self.query_one("#host-list", ListView)
            if host_list.index is not None and host_list.index >= 0:
                widget = host_list.children[host_list.index]
                self.selected_host_alias = widget.host.alias
                msg = f"✅ Selected: {widget.host.alias}"
                self._log(msg, "success")
                self.notify(msg, severity="information", timeout=2)
            else:
                msg = "❌ No host to select"
                self._log(msg, "warning")
                self.notify(msg, severity="warning", timeout=2)

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
                    "name": "Sort: Name",
                    "created": "Sort: Newest",
                    "windows": "Sort: Windows",
                    "attached": "Sort: Attached"
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

    def watch_auto_refresh_enabled(self, old_enabled: bool, new_enabled: bool) -> None:
        """Called when auto-refresh is toggled."""
        if new_enabled:
            self.auto_refresh_countdown = self.auto_refresh_interval
            self._log(f"Auto-refresh enabled ({self.auto_refresh_interval}s interval)", "success")
        else:
            self.auto_refresh_countdown = 0
            self._log("Auto-refresh paused", "info")
        self._update_refresh_indicator()

    def watch_auto_refresh_countdown(self, old_countdown: int, new_countdown: int) -> None:
        """Called when auto-refresh countdown changes."""
        self._update_refresh_indicator()

    def watch_auto_refresh_interval(self, old_interval: int, new_interval: int) -> None:
        """Called when auto-refresh interval changes."""
        if self.auto_refresh_enabled:
            self.auto_refresh_countdown = new_interval
        self._update_refresh_indicator()

    def _update_refresh_indicator(self) -> None:
        """Update the auto-refresh indicator widget."""
        if not self.is_mounted:
            return

        try:
            indicator = self.query_one("#auto-refresh-indicator", Static)
            if self.auto_refresh_enabled:
                indicator.update(f"[dim]Refresh: {self.auto_refresh_countdown}s[/dim]")
            else:
                indicator.update("[dim]Refresh: OFF (P)[/dim]")
        except Exception:
            pass  # Widget not available

    async def _auto_refresh_tick(self) -> None:
        """Called every second to handle auto-refresh countdown."""
        if not self.auto_refresh_enabled:
            return

        self.auto_refresh_countdown -= 1

        if self.auto_refresh_countdown <= 0:
            # Time to refresh
            await self.action_refresh_all_hosts()
            self.auto_refresh_countdown = self.auto_refresh_interval

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
        if self.filter_visible:
            self._log("Filter ON (press F/SLASH again to close)", "info")
        else:
            self._log("Filter OFF", "info")

    def action_cycle_sort(self) -> None:
        """Cycle through sort modes."""
        sort_modes = ["name", "created", "windows", "attached"]
        current_index = sort_modes.index(self.sort_mode)
        next_index = (current_index + 1) % len(sort_modes)
        self.sort_mode = sort_modes[next_index]
        self._log(f"Sort: {self.sort_mode}", "info")

    def action_toggle_auto_refresh(self) -> None:
        """Toggle auto-refresh on/off."""
        self.auto_refresh_enabled = not self.auto_refresh_enabled
        state = "ON" if self.auto_refresh_enabled else "OFF"
        self._log(f"Auto-refresh: {state}", "info")

    def action_increase_refresh_interval(self) -> None:
        """Increase auto-refresh interval by 10 seconds."""
        new_interval = min(self.auto_refresh_interval + 10, 300)  # Max 5 minutes
        if new_interval != self.auto_refresh_interval:
            self.auto_refresh_interval = new_interval
            self._log(f"Auto-refresh interval: {self.auto_refresh_interval}s", "info")

    def action_decrease_refresh_interval(self) -> None:
        """Decrease auto-refresh interval by 10 seconds."""
        new_interval = max(self.auto_refresh_interval - 10, 10)  # Min 10 seconds
        if new_interval != self.auto_refresh_interval:
            self.auto_refresh_interval = new_interval
            self._log(f"Auto-refresh interval: {self.auto_refresh_interval}s", "info")

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
                self._log(f"Opening new session dialog for {host.alias}", "info")
                async def create_session_callback(name: Optional[str]) -> None:
                    if name:
                        async def _create_session() -> None:
                            self._log(f"Creating session '{name}' on {host.alias}...", "info")
                            try:
                                conn = await self.conn_manager.get_connection(host)
                                success = await self.tmux_controller.create_session(conn, name)
                                if success:
                                    self._log(f"✅ Session '{name}' created", "success")
                                    await self.action_refresh_host()
                                else:
                                    self._log(f"❌ Failed to create '{name}'", "error")
                            except ConnectionError as e:
                                self._log(f"❌ {e}", "error")
                            except ValueError as e:
                                self._log(f"❌ Invalid name: {e}", "error")
                        self.call_later(_create_session)
                    else:
                        self._log("Cancelled", "info")

                self.push_screen(NewSessionScreen(), create_session_callback)
        else:
            self._log("❌ No host selected. Press TAB to switch to host list", "warning")


    
    async def action_kill_session(self) -> None:
        """Kills the selected session."""
        if self.selected_host_alias:
            host = next((h for h in self.hosts if h.alias == self.selected_host_alias), None)
            session_list = self.query_one("#session-list", ListView)
            if host and session_list.index is not None and session_list.index >= 0 and len(session_list.children) > 0:
                widget = session_list.children[session_list.index]
                session = widget.session
                self._log(f"Confirm kill '{session.name}'?", "info")

                def kill_session_callback(confirm: bool) -> None:
                    if confirm:
                        async def _kill_session() -> None:
                            self._log(f"Killing '{session.name}' on {host.alias}...", "info")
                            try:
                                conn = await self.conn_manager.get_connection(host)
                                success = await self.tmux_controller.kill_session(conn, session.name)
                                if success:
                                    self._log(f"✅ Killed '{session.name}'", "success")
                                    await self.action_refresh_host()
                                else:
                                    self._log(f"❌ Failed to kill '{session.name}'", "error")
                            except ConnectionError as e:
                                self._log(f"❌ {e}", "error")
                        self.call_later(_kill_session)
                    else:
                        self._log("Cancelled", "info")

                self.push_screen(
                    ConfirmKillSessionScreen(session.name), kill_session_callback
                )
            else:
                self._log("❌ No session selected", "warning")
        else:
            self._log("❌ No host selected. Press TAB to switch lists", "warning")

    async def action_rename_session(self) -> None:
        """Renames the selected session."""
        if self.selected_host_alias:
            host = next((h for h in self.hosts if h.alias == self.selected_host_alias), None)
            session_list = self.query_one("#session-list", ListView)
            if host and session_list.index is not None and session_list.index >= 0 and len(session_list.children) > 0:
                widget = session_list.children[session_list.index]
                session = widget.session

                async def rename_session_callback(new_name: Optional[str]) -> None:
                    if new_name:
                        async def _rename_session() -> None:
                            self._log(f"Renaming session '{session.name}' to '{new_name}' on {host.alias}...", "info")
                            try:
                                conn = await self.conn_manager.get_connection(host)
                                success = await self.tmux_controller.rename_session(conn, session.name, new_name)
                                if success:
                                    self._log(f"Session renamed successfully", "success")
                                    await self.action_refresh_host()
                                else:
                                    self._log(f"Failed to rename session", "error")
                            except ConnectionError as e:
                                self._log(str(e), "error")
                            except ValueError as e:
                                self._log(f"Invalid session name: {e}", "error")
                        self.call_later(_rename_session)

                self.push_screen(RenameSessionScreen(session.name), rename_session_callback)

    async def action_show_session_info(self) -> None:
        """Shows detailed information about the selected session."""
        if self.selected_host_alias:
            host = next((h for h in self.hosts if h.alias == self.selected_host_alias), None)
            session_list = self.query_one("#session-list", ListView)
            if host and session_list.index is not None and session_list.index >= 0 and len(session_list.children) > 0:
                widget = session_list.children[session_list.index]
                session = widget.session
                self._log(f"Loading session info for '{session.name}'...", "info")
                try:
                    conn = await self.conn_manager.get_connection(host)
                    windows = await self.tmux_controller.list_windows(conn, session.name)
                    self.push_screen(SessionInfoScreen(session, windows))
                except ConnectionError as e:
                    self._log(str(e), "error")


    def _get_ssh_command(self, host: Host, session_name: str) -> Optional[list[str]]:
        """
        Construct platform-specific SSH command for attaching to a session.

        Returns:
            Optional[list[str]]: SSH command as list, or None if SSH not found

        Raises:
            FileNotFoundError: If SSH is not found with helpful install instructions
        """
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
            # On Windows, check common SSH locations in order
            ssh_candidates = [
                r"C:\Windows\System32\OpenSSH\ssh.exe",  # Windows OpenSSH
                r"C:\Program Files\Git\usr\bin\ssh.exe",  # Git for Windows
            ]

            # Try to find SSH in common locations
            for candidate in ssh_candidates:
                if os.path.exists(candidate):
                    return [candidate] + ssh_args

            # Fallback to PATH
            import shutil
            if shutil.which("ssh"):
                return ["ssh"] + ssh_args

            # SSH not found - provide helpful error
            error_msg = """❌ SSH client not found on Windows.

To fix this, install SSH using one of these methods:

1. Windows OpenSSH (recommended):
   - Open Settings → Apps → Optional Features
   - Click "Add a feature"
   - Search for "OpenSSH Client" and install it

2. Git for Windows:
   - Download from: https://git-scm.com/download/win
   - During installation, ensure "Git Bash" is selected

After installing, restart your terminal and try again."""
            raise FileNotFoundError(error_msg)

        elif is_termux:
            # Termux: Check if openssh is installed
            import shutil
            if not shutil.which("ssh"):
                error_msg = """❌ SSH client not found on Termux.

To fix this, install OpenSSH:
   pkg install openssh

Then restart SyncMux and try again."""
                raise FileNotFoundError(error_msg)
            return ["ssh"] + ssh_args

        else:
            # Linux/WSL: Check if SSH is available
            import shutil
            if not shutil.which("ssh"):
                error_msg = """❌ SSH client not found.

To fix this, install OpenSSH client:

Ubuntu/Debian/WSL:
   sudo apt update && sudo apt install openssh-client

Fedora/RHEL:
   sudo dnf install openssh-clients

Arch Linux:
   sudo pacman -S openssh

After installing, try again."""
                raise FileNotFoundError(error_msg)
            return ["ssh"] + ssh_args

    async def action_attach_session(self) -> None:
        """Attaches to the selected session."""
        if self.selected_host_alias:
            host = next((h for h in self.hosts if h.alias == self.selected_host_alias), None)
            session_list = self.query_one("#session-list", ListView)
            if host and session_list.index is not None and session_list.index >= 0 and len(session_list.children) > 0:
                widget = session_list.children[session_list.index]
                session = widget.session

                try:
                    # Get platform-specific SSH command
                    cmd = self._get_ssh_command(host, session.name)

                    # Exit TUI cleanly before process replacement
                    await self.app.exit()

                    # Replace current process with SSH (never returns)
                    os.execvp(cmd[0], cmd)

                except FileNotFoundError as e:
                    # SSH not found - show error with install instructions
                    self._log(str(e), "error", show_dialog=True)
                except Exception as e:
                    # Other errors during attach
                    self._log(f"❌ Failed to attach to session: {e}", "error", show_dialog=True)

    def _show_first_run_prompt(self) -> None:
        """Show first-run prompt to add machines."""
        def handle_first_run_response(add_machines: bool) -> None:
            if add_machines:
                self._show_add_machine_screen()

        self.push_screen(FirstRunPrompt(), handle_first_run_response)

    def _show_add_machine_screen(self) -> None:
        """Show the add machine screen."""
        async def handle_machine_info(machine_info: dict | None) -> None:
            if machine_info:
                self._log(f"Adding machine: {machine_info['alias']}", "info")

                # Create new Host object
                new_host = Host(**machine_info)

                # Add to current hosts list
                self.hosts.append(new_host)

                # Save to config file
                try:
                    save_config(self.hosts, self.config_path)
                    self._log(f"✅ Saved {machine_info['alias']} to config", "success")
                except Exception as e:
                    self._log(f"❌ Failed to save config: {e}", "error")
                    return

                # Add widget to UI
                host_list = self.query_one("#host-list", ListView)
                widget = HostWidget(new_host)
                self.host_widgets[new_host.alias] = widget
                host_list.append(widget)

                # Select the new host
                self.selected_host_alias = new_host.alias
                host_list.index = len(self.hosts) - 1

                self.notify(f"✅ Machine '{machine_info['alias']}' added!", severity="information", timeout=3)

                # Refresh the new host
                await self.action_refresh_host()

        self.push_screen(AddMachineScreen(), handle_machine_info)

    def action_show_help(self) -> None:
        """Show the keyboard shortcuts help screen."""
        self.push_screen(HelpScreen())

    async def on_unmount(self) -> None:
        """Called when the app is unmounted."""
        if hasattr(self, 'conn_manager'):
            await self.conn_manager.close_all()


if __name__ == "__main__":
    app = SyncMuxApp()
    app.run()
