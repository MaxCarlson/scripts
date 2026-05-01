"""
web_docs_processor

Utilities for building retrieval-friendly source packs from documentation websites.
"""

from __future__ import annotations

__all__ = [
    "__version__",
    "main",
]

__version__ = "0.3.3"


def main() -> int:
    """
    Run the web docs processor command-line interface.

    Importing lazily keeps package import side effects minimal and avoids loading
    crawler dependencies unless the CLI is actually invoked.
    """
    from web_docs_processor.docs_source_builder import main as cli_main  # noqa: PLC0415

    return cli_main()
