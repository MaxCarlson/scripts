
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Label, ListItem, Static

from .models import Host, Session


class HostWidget(ListItem):
    """A widget to display a host."""

    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        self._session_count = 0

    def compose(self) -> ComposeResult:
        """Compose the widget."""
        yield Label(self.host.alias)
        yield Static("", classes="session-count")
        yield Static("", classes="status")

    def set_status_connected(self) -> None:
        """Set the status to connected."""
        self.query_one(".status").update("● Connected")
        self.styles.background = "green"

    def set_status_connecting(self) -> None:
        """Set the status to connecting."""
        self.query_one(".status").update("● Connecting...")
        self.styles.background = "yellow"

    def set_status_error(self) -> None:
        """Set the status to error."""
        self.query_one(".status").update("● Error")
        self.styles.background = "red"

    def update_session_count(self, count: int) -> None:
        """Update the session count display."""
        self._session_count = count
        count_widget = self.query_one(".session-count", Static)
        if count == 0:
            count_widget.update("(no sessions)")
        elif count == 1:
            count_widget.update("(1 session)")
        else:
            count_widget.update(f"({count} sessions)")


class SessionWidget(ListItem):
    """A widget to display a session."""

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.session = session

    def compose(self) -> ComposeResult:
        """Compose the widget."""
        with Horizontal():
            yield Static(self.session.name, classes="session-name")
            yield Static(f"({self.session.windows} windows)", classes="session-windows")
            yield Static(self.session.created_at.strftime("%Y-%m-%d %H:%M"), classes="session-created")
            yield Static("(attached)" if self.session.attached > 0 else "", classes="session-attached")
