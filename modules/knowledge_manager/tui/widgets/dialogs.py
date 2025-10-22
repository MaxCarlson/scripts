# File: knowledge_manager/tui/widgets/dialogs.py
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListView, ListItem

class InputDialog(ModalScreen):
    """A modal dialog for text input with @mention autocomplete."""

    DEFAULT_CSS = """
    #suggestion_label {
        color: $text-muted;
        text-style: italic;
    }
    """

    def __init__(self, prompt_text: str, initial_value: str = "", enable_autocomplete: bool = False, **kwargs) -> None:
        super().__init__()
        self.prompt_text = prompt_text
        self.initial_value = initial_value
        self.enable_autocomplete = enable_autocomplete
        self.project_names = []
        self.current_suggestions = []
        self.suggestion_index = 0

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(self.prompt_text),
            Label("", id="suggestion_label"),  # For showing suggestions
            Input(value=self.initial_value, placeholder="Enter text...", id="text_input"),
            Button("Submit", variant="primary", id="submit"),
            Button("Cancel", variant="default", id="cancel"),
            id="dialog",
        )

    async def on_mount(self) -> None:
        """Load project names for autocomplete."""
        if self.enable_autocomplete:
            try:
                from ... import project_ops
                projects = project_ops.list_all_projects(base_data_dir=self.app.base_data_dir)
                self.project_names = [p.name for p in projects]
            except Exception:
                self.project_names = []

    def on_input_changed(self, event: Input.Changed) -> None:
        """Update suggestions as user types."""
        if not self.enable_autocomplete:
            return

        text = event.value
        # Find last @ mention
        at_index = text.rfind('@')
        if at_index == -1:
            self.query_one("#suggestion_label", Label).update("")
            return

        # Extract partial project name after @
        partial = text[at_index + 1:]

        # Find matching projects
        matches = [p for p in self.project_names if p.lower().startswith(partial.lower())]

        if matches:
            self.current_suggestions = matches
            self.suggestion_index = 0
            suggestion = matches[0]
            # Show suggestion
            remaining = suggestion[len(partial):]
            self.query_one("#suggestion_label", Label).update(
                f"Suggestion: @{suggestion} (Tab to complete, ↓ for more)"
            )
        else:
            self.current_suggestions = []
            self.query_one("#suggestion_label", Label).update("")

    def on_key(self, event) -> None:
        """Handle Tab and arrow keys for autocomplete."""
        if not self.enable_autocomplete or not self.current_suggestions:
            return

        if event.key == "tab":
            # Accept current suggestion
            event.prevent_default()
            event.stop()
            self._accept_suggestion()
        elif event.key == "down":
            # Cycle to next suggestion
            event.prevent_default()
            event.stop()
            self.suggestion_index = (self.suggestion_index + 1) % len(self.current_suggestions)
            self._update_suggestion_display()
        elif event.key == "up":
            # Cycle to previous suggestion
            event.prevent_default()
            event.stop()
            self.suggestion_index = (self.suggestion_index - 1) % len(self.current_suggestions)
            self._update_suggestion_display()

    def _accept_suggestion(self) -> None:
        """Replace partial text with full suggestion."""
        if not self.current_suggestions:
            return

        input_widget = self.query_one("#text_input", Input)
        text = input_widget.value
        at_index = text.rfind('@')

        if at_index != -1:
            suggestion = self.current_suggestions[self.suggestion_index]
            # Replace from @ to end with full suggestion
            new_text = text[:at_index] + "@" + suggestion
            input_widget.value = new_text
            # Clear suggestions
            self.current_suggestions = []
            self.query_one("#suggestion_label", Label).update("")

    def _update_suggestion_display(self) -> None:
        """Update the suggestion label when cycling."""
        if self.current_suggestions:
            suggestion = self.current_suggestions[self.suggestion_index]
            count_text = f"({self.suggestion_index + 1}/{len(self.current_suggestions)})"
            self.query_one("#suggestion_label", Label).update(
                f"Suggestion: @{suggestion} {count_text} (Tab to complete, ↑↓ to cycle)"
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
