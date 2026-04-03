import pytest
from system_manager.manager import SystemManager

def test_base64_encode_decode():
    mgr = SystemManager()
    original = "Hello World"
    encoded = mgr.text_base64_encode(original)
    decoded = mgr.text_base64_decode(encoded)
    assert decoded == original

def test_sha256():
    mgr = SystemManager()
    text = "Hello World"
    h = mgr.text_sha256(text)
    assert len(h) == 64
    assert h == "a591a6d40bf420404a011733cfb7b190d62c65bf0bcda32b57b277d9ad9f146e".lower()
