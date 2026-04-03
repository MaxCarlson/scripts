import pytest
from system_manager.manager import SystemManager

def test_crypto_rand():
    mgr = SystemManager()
    r1 = mgr.crypto_rand(16)
    r2 = mgr.crypto_rand(16)
    assert len(r1) == 16
    assert r1 != r2
