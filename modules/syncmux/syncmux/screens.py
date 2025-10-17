
from textual.app import ComposeResult
from textual.containers import Grid, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from .tmux_controller import TmuxController
from .models import Session


class NewSessionScreen(ModalScreen):
    """A screen to create a new session."""

    def compose(self) -> ComposeResult:
        """Compose the screen."""
        with Grid(id="new-session-grid"):
            yield Static("Create New Session", id="title")
            yield Input(placeholder="Session name", id="session-name-input")
            yield Static("", id="error-message", classes="error")
            yield Button("Create", variant="primary", id="create")
            yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Called when a button is pressed."""
        if event.button.id == "create":
            input_widget = self.query_one("#session-name-input", Input)
            error_widget = self.query_one("#error-message", Static)
            session_name = input_widget.value.strip()

            # Validate the session name
            try:
                sanitized_name = TmuxController.sanitize_session_name(session_name)
                self.dismiss(sanitized_name)
            except ValueError as e:
                # Show error message
                error_widget.update(f"⚠️ {str(e)}")
                input_widget.focus()
        else:
            self.dismiss(None)


class ConfirmKillSessionScreen(ModalScreen):
    """A screen to confirm killing a session."""

    def __init__(self, session_name: str) -> None:
        super().__init__()
        self.session_name = session_name

    def compose(self) -> ComposeResult:
        """Compose the screen."""
        with Grid(id="kill-session-grid"):
            yield Static(f"Are you sure you want to kill session '{self.session_name}'?")
            yield Button("Kill", variant="error", id="kill")
            yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Called when a button is pressed."""
        if event.button.id == "kill":
            self.dismiss(True)
        else:
            self.dismiss(False)


class HelpScreen(ModalScreen):
    """A screen showing keyboard shortcuts and help."""

    BINDINGS = [("escape", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        """Compose the help screen."""
        help_text = """
[bold cyan]SyncMux - Keyboard Shortcuts[/bold cyan]

[bold yellow]Navigation:[/bold yellow]
  j, ↓         Move cursor down in active list
  k, ↑         Move cursor up in active list
  Tab          Switch focus between host and session lists
  Enter        Select host / Attach to session

[bold yellow]Session Management:[/bold yellow]
  n            Create new session on selected host
  d            Kill selected session (with confirmation)
  Shift+R      Rename selected session
  i            View detailed session information

[bold yellow]Filter & Sort:[/bold yellow]
  /            Toggle session filter (Esc to close)
  s            Cycle sort mode (name/created/windows/attached)

[bold yellow]Refresh:[/bold yellow]
  r            Refresh current host's sessions
  Ctrl+R       Refresh all hosts concurrently

[bold yellow]Help & Exit:[/bold yellow]
  ?, F1        Show this help screen
  q, Ctrl+C    Quit application
  Escape       Close dialogs/help

[bold cyan]Tips:[/bold cyan]
• Session names: letters, numbers, -, _, spaces (auto-converted to _)
• Connection status shown with colored indicators in host list
• Session count displayed next to each host name
• Timestamped logs at bottom show operation details
"""
        with Vertical(id="help-container"):
            yield Static(help_text, id="help-text")
            yield Button("Close (Esc)", variant="primary", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Called when close button is pressed."""
        self.dismiss()


class ErrorDialog(ModalScreen):
    """A modal dialog for displaying error messages."""

    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, title: str, message: str, details: str = "") -> None:
        super().__init__()
        self.title = title
        self.message = message
        self.details = details

    def compose(self) -> ComposeResult:
        """Compose the error dialog."""
        with Vertical(id="error-dialog-container"):
            yield Static(f"[bold red]{self.title}[/bold red]", id="error-title")
            yield Static(self.message, id="error-message")
            if self.details:
                yield Static(f"\n[dim]{self.details}[/dim]", id="error-details")
            yield Button("OK (Esc)", variant="error", id="ok")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Called when OK button is pressed."""
        self.dismiss()


class RenameSessionScreen(ModalScreen):
    """A screen to rename an existing session."""

    def __init__(self, current_name: str) -> None:
        super().__init__()
        self.current_name = current_name

    def compose(self) -> ComposeResult:
        """Compose the screen."""
        with Grid(id="new-session-grid"):
            yield Static(f"Rename Session: {self.current_name}", id="title")
            yield Input(placeholder="New session name", id="session-name-input", value=self.current_name)
            yield Static("", id="error-message", classes="error")
            yield Button("Rename", variant="primary", id="rename")
            yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Called when a button is pressed."""
        if event.button.id == "rename":
            input_widget = self.query_one("#session-name-input", Input)
            error_widget = self.query_one("#error-message", Static)
            new_name = input_widget.value.strip()

            # Validate the new session name
            try:
                sanitized_name = TmuxController.sanitize_session_name(new_name)
                if sanitized_name == self.current_name.replace(' ', '_'):
                    error_widget.update("⚠️ New name is the same as current name")
                    input_widget.focus()
                else:
                    self.dismiss(sanitized_name)
            except ValueError as e:
                # Show error message
                error_widget.update(f"⚠️ {str(e)}")
                input_widget.focus()
        else:
            self.dismiss(None)


class SessionInfoScreen(ModalScreen):
    """A screen showing detailed session information."""

    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, session: Session, windows: list[str]) -> None:
        super().__init__()
        self.session = session
        self.windows = windows

    def compose(self) -> ComposeResult:
        """Compose the session info screen."""
        # Build window list
        if self.windows:
            window_list = "\n".join(f"  • {w}" for w in self.windows)
        else:
            window_list = "  (No windows)"

        info_text = f"""
[bold cyan]Session Information[/bold cyan]

[bold yellow]Name:[/bold yellow]       {self.session.name}
[bold yellow]ID:[/bold yellow]         {self.session.id}
[bold yellow]Created:[/bold yellow]    {self.session.created_at.strftime("%Y-%m-%d %H:%M:%S")}
[bold yellow]Windows:[/bold yellow]    {self.session.windows}
[bold yellow]Attached:[/bold yellow]   {"Yes" if self.session.attached > 0 else "No"} ({self.session.attached} clients)

[bold yellow]Window Names:[/bold yellow]
{window_list}

[dim]Press Esc or click Close to return[/dim]
"""
        with Vertical(id="help-container"):
            yield Static(info_text, id="help-text")
            yield Button("Close (Esc)", variant="primary", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Called when close button is pressed."""
        self.dismiss()
