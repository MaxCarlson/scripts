from __future__ import annotations

from agt.tokens import count_text_tokens, count_messages_tokens


def test_rough_token_counts():
    assert count_text_tokens("hello", None) >= 1
    msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "ok"}]
    assert count_messages_tokens(msgs, None) >= 2
