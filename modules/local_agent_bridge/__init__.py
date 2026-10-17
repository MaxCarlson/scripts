"""Repository-path compatibility when scripts adds modules/ to sys.path."""
from pathlib import Path

__path__.insert(0, str(Path(__file__).parent / 'local_agent_bridge'))
from .local_agent_bridge import __version__
