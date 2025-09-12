#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import List, Dict, Any

try:
    import tiktoken  # type: ignore
except Exception:  # pragma: no cover
    tiktoken = None


def _rough_tokens(s: str) -> int:
    return max(1, int(len(s) / 4))


def count_text_tokens(text: str, model: str | None) -> int:
    if not text:
        return 0
    if tiktoken and model:
        try:
            enc = tiktoken.encoding_for_model(model)
        except Exception:
            enc = tiktoken.get_encoding("cl100k_base")  # type: ignore
        return len(enc.encode(text))  # type: ignore
    return _rough_tokens(text)


def count_messages_tokens(messages: List[Dict[str, str]], model: str | None) -> int:
    total = 0
    for m in messages:
        total += count_text_tokens(m.get("content", ""), model)
    return total

