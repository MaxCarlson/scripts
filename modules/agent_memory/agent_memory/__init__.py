"""agent_memory — persistent markdown-file memory for AI agents."""

__version__ = "0.3.0"

from agent_memory.note import Note
from agent_memory.store import NoteStore

__all__ = ["Note", "NoteStore"]
