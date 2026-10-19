#!/usr/bin/env python3
"""
lmst.py - LM Studio OpenAI-compatible client + CLI with streaming support.

Consolidated entry point routing to lmstui.cli and lmstui.api.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from lmstui.api import LMStudioAPI
from lmstui.cli import build_parser_lmst, main_lmst


@dataclass(frozen=True)
class ClientConfig:
    base_url: str
    timeout_seconds: float = 60.0
    api_key: Optional[str] = None
    verbose: bool = False


class LMStudioClient(LMStudioAPI):
    def __init__(self, config: ClientConfig) -> None:
        super().__init__(
            target=config.base_url,
            timeout_seconds=config.timeout_seconds,
            api_key=config.api_key,
            verbose=config.verbose,
        )


build_parser = build_parser_lmst


def main(argv: Optional[List[str]] = None) -> int:
    return main_lmst(argv)


if __name__ == "__main__":
    raise SystemExit(main())
