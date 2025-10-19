# File: knowledge_manager/tui/widgets/dialogs.py
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListView, ListItem

class InputDialog(ModalScreen):
    """A modal dialog for text input."""

    def __init__(self, prompt_text: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.prompt_text = prompt_text

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(self.prompt_text),
            Input(placeholder="Enter text..."),
            Button("Submit", variant="primary", id="submit"),
            Button("Cancel", variant="default", id="cancel"),
            id="dialog",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            self.dismiss(self.query_one(Input).value)
        else:
            self.dismiss(None)

class LinkSelectionDialog(ModalScreen):
    """A modal dialog to select a link to follow."""

    def __init__(self, links: list, **kwargs) -> None:
        super().__init__(**kwargs)
        self.links = links

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Multiple links found. Select one to follow:"),
            ListView(*[ListItem(Label(link)) for link in self.links]),
            Button("Cancel", variant="default", id="cancel"),
            id="dialog",
        )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.dismiss(str(event.item.children[0].renderable))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
