# File: knowledge_manager/tui/widgets/dialogs.py
from textual.app import ComposeResult
from textual.containers import Vertical, Container
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label

class InputDialog(ModalScreen[str]):
    """A simple modal dialog to get text input."""
    DEFAULT_CSS = """
    InputDialog { align: center middle; }
    InputDialog > Vertical { width: 80%; max-width: 60; height: auto; border: thick $primary-background-darken-2; background: $surface; padding: 1 2;}
    InputDialog Input { margin-bottom: 1; border: tall $primary;}
    InputDialog .buttons { width: 100%; align-horizontal: right; padding-top: 1;}
    InputDialog Button { margin-left: 1;}
    """
    def __init__(self, prompt_text: str, initial_value: str = ""): 
        super().__init__()
        self.prompt_text=prompt_text
        self.initial_value=initial_value
    def compose(self) -> ComposeResult:
        with Vertical(): 
            yield Label(self.prompt_text)
            yield Input(value=self.initial_value, id="text_input_field")
            with Container(classes="buttons"): 
                yield Button("OK", variant="primary", id="ok_button")
                yield Button("Cancel", id="cancel_button")
    def on_mount(self) -> None: self.query_one(Input).focus()
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok_button": self.dismiss(self.query_one(Input).value)
        else: self.dismiss("")
