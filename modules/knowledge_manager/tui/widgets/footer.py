# File: knowledge_manager/tui/widgets/footer.py
from textual.widgets import Static
from textual.binding import Binding

class CustomFooter(Static):
    """A custom footer that displays key bindings and wraps them."""

    def on_mount(self) -> None:
        """Set up a reactive watch on the bindings of the current screen."""
        self.watch(self.app, "screen", self._update_bindings, init=False)
        self._update_bindings()

    def _update_bindings(self, old_screen=None, new_screen=None) -> None:
        """Update the footer with the bindings of the current screen."""
        if not hasattr(self.app, "screen") or not self.app.screen:
            return

        bindings = self.app.screen.BINDINGS
        shown_bindings = sorted([b for b in bindings if b.show], key=lambda b: b.key)
        
        key_texts = []
        for binding in shown_bindings:
            key_display = binding.key_display or binding.key
            key_texts.append(f"[b u]{key_display}[/b u] {binding.description}")
        
        footer_text = "  ".join(key_texts)
        self.update(footer_text)
