#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from textual.widgets import Static
from textual.binding import Binding

class CustomFooter(Static):
    """A custom footer that displays key bindings and wraps them.
    Now merges screen bindings with app-level bindings so global shortcuts
    like Ctrl+P (Print), Ctrl+Q (Quit) are visible on every screen.
    """

    def on_mount(self) -> None:
        self.watch(self.app, "screen", self._update_bindings, init=False)
        self._update_bindings()

    def _update_bindings(self, old_screen=None, new_screen=None) -> None:
        if not hasattr(self.app, "screen") or not self.app.screen:
            return

        # Prefer screen bindings + app bindings, de-duplicated by key
        bindings = []
        try:
            bindings.extend(getattr(self.app.screen, "BINDINGS", []) or [])
        except Exception:
            pass
        try:
            bindings.extend(getattr(self.app, "BINDINGS", []) or [])
        except Exception:
            pass

        seen = set()
        shown_bindings = []
        for b in bindings:
            key = getattr(b, "key", None)
            if not key or key in seen:
                continue
            seen.add(key)
            if getattr(b, "show", False):
                shown_bindings.append(b)

        # Sort for stable display
        shown_bindings.sort(key=lambda b: (b.key or ""))

        key_texts = []
        for binding in shown_bindings:
            key_display = binding.key_display or binding.key
            key_texts.append(f"[b u]{key_display}[/b u] {binding.description}")

        footer_text = "  ".join(key_texts)
        self.update(footer_text)
