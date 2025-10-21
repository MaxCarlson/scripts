# File: knowledge_manager/tui/widgets/dialogs.py
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListView, ListItem

class InputDialog(ModalScreen):
    """A modal dialog for text input."""

    def __init__(self, prompt_text: str, initial_value: str = "", **kwargs) -> None:
        super().__init__()
        self.prompt_text = prompt_text
        self.initial_value = initial_value

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(self.prompt_text),
            Input(value=self.initial_value, placeholder="Enter text..."),
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


class ProjectAutocompleteDialog(ModalScreen):
    """Autocomplete dialog for @project mentions."""

    DEFAULT_CSS = """
    ProjectAutocompleteDialog {
        align: center middle;
    }

    #autocomplete_container {
        width: 60;
        height: auto;
        background: $panel;
        border: solid $primary;
    }

    #autocomplete_list {
        height: 10;
    }
    """

    def __init__(self, projects: list, filter_text: str = "", **kwargs) -> None:
        super().__init__()
        self.all_projects = projects  # List of project names
        self.filter_text = filter_text
        self.filtered_projects = self._filter_projects(filter_text)

    def _filter_projects(self, text: str) -> list:
        """Filter projects by prefix match (case-insensitive)."""
        if not text:
            return self.all_projects[:10]  # Show first 10 if no filter

        text_lower = text.lower()
        matches = [p for p in self.all_projects if p.lower().startswith(text_lower)]
        return matches[:10]  # Limit to 10 items

    def compose(self) -> ComposeResult:
        items = [ListItem(Label(proj)) for proj in self.filtered_projects] if self.filtered_projects else [ListItem(Label("No matches"))]

        yield Vertical(
            Label(f"Select project (filtering: '@{self.filter_text}')"),
            ListView(*items, id="autocomplete_list"),
            Label("↑↓ Navigate | Enter Select | Esc Cancel", classes="help-text"),
            id="autocomplete_container",
        )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """User pressed Enter on a project."""
        if self.filtered_projects:
            # Get selected project name
            selected_text = str(event.item.children[0].renderable)
            if selected_text != "No matches":
                self.dismiss(selected_text)

    def on_key(self, event) -> None:
        """Handle Escape to cancel."""
        if event.key == "escape":
            event.stop()
            self.dismiss(None)
