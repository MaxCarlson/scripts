
from textual.app import ComposeResult
from textual.containers import Grid
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static


class NewSessionScreen(ModalScreen):
    """A screen to create a new session."""

    def compose(self) -> ComposeResult:
        """Compose the screen."""
        with Grid(id="new-session-grid"):
            yield Input(placeholder="Session name")
            yield Button("Create", variant="primary", id="create")
            yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Called when a button is pressed."""
        if event.button.id == "create":
            self.dismiss(self.query_one(Input).value)
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
