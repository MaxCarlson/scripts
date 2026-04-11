def main(*args, **kwargs):
    """Run the system_manager CLI."""
    from .cli import main as cli_main

    return cli_main(*args, **kwargs)

__all__ = ["main"]
