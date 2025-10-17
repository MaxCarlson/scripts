
from textual.app import ComposeResult
from textual.containers import Grid
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from .tmux_controller import TmuxController


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
