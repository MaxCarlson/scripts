import pytest
import socket
from system_manager.manager import SystemManager

def test_local_ip():
    mgr = SystemManager()
    results = mgr.local_ip()
    assert len(results) > 0
    assert any(r['address'] == "127.0.0.1" or r['address'] == "::1" for r in results)

def test_net_resolve():
    mgr = SystemManager()
    results = mgr.net_resolve("localhost")
    assert len(results) > 0
    assert any(r['address'] == "127.0.0.1" or r['address'] == "::1" for r in results)

def test_net_interfaces():
    mgr = SystemManager()
    results = mgr.net_interfaces()
    assert len(results) > 0
    assert "name" in results[0]
    assert "status" in results[0]

def test_net_ports():
    mgr = SystemManager()
    results = mgr.net_ports()
    # At least one listening port should exist usually
    # But we can't guarantee it in CI
    assert isinstance(results, list)

@pytest.mark.skipif(not socket.gethostbyname("google.com"), reason="Internet not available")
def test_public_ip():
    mgr = SystemManager()
    ip = mgr.public_ip()
    assert isinstance(ip, str)
    assert "." in ip or ":" in ip
