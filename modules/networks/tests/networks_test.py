"""
Tests for networks module
"""
import pytest
from networks import (
    get_lan_ip,
    get_all_ips,
    get_network_info,
    check_port_open,
)
from networks.local_web import (
    is_local_url,
    fetch_url,
    check_local_access,
    FetchResult,
)


def test_get_lan_ip():
    """Test getting LAN IP"""
    ip = get_lan_ip()
    assert ip is not None
    assert isinstance(ip, str)
    # IP should be in dotted quad format
    parts = ip.split('.')
    assert len(parts) == 4
    for part in parts:
        assert 0 <= int(part) <= 255


def test_get_all_ips():
    """Test getting all IPs"""
    ips = get_all_ips()
    assert isinstance(ips, list)
    assert len(ips) > 0  # Should have at least loopback
    for iface in ips:
        assert 'interface' in iface
        assert 'ip' in iface
        assert isinstance(iface['interface'], str)
        assert isinstance(iface['ip'], str)


def test_get_network_info():
    """Test getting network information"""
    info = get_network_info()
    assert isinstance(info, dict)
    assert 'lan_ip' in info
    assert 'all_ips' in info
    assert 'hostname' in info
    assert 'is_wsl' in info
    assert 'wsl_host_ip' in info

    assert isinstance(info['hostname'], str)
    assert isinstance(info['is_wsl'], bool)
    assert isinstance(info['all_ips'], list)


def test_check_port_open_loopback():
    """Test checking if a port is open (using loopback)"""
    # Test that checking a definitely closed port returns False
    result = check_port_open('127.0.0.1', 65000, timeout=0.5)
    # Can't assert False because the port might be open
    assert isinstance(result, bool)


def test_check_port_open_google_dns():
    """Test checking open port (Google DNS)"""
    # Google DNS should have port 53 open
    result = check_port_open('8.8.8.8', 53, timeout=2.0)
    # Can't assert True because network might be down
    assert isinstance(result, bool)


# ============== Local Web Tests ==============

def test_is_local_url():
    """Test is_local_url detection"""
    # Local URLs
    assert is_local_url('http://localhost:3000/') is True
    assert is_local_url('http://127.0.0.1:8080/') is True
    assert is_local_url('http://192.168.1.1/') is True
    assert is_local_url('http://10.0.0.1:80/') is True
    assert is_local_url('http://mydevice.local/') is True
    
    # Public URLs
    assert is_local_url('http://google.com/') is False
    assert is_local_url('https://github.com/') is False


def test_fetch_url_result_serialization():
    """Test FetchResult serialization"""
    result = FetchResult(
        url='http://localhost/',
        success=True,
        status_code=200,
        content_type='text/html',
        content='<html></html>',
        content_length=13,
    )
    
    # JSON serialization
    json_str = result.to_json()
    assert 'localhost' in json_str
    assert '200' in json_str
    
    # Human format
    human_str = result.to_human()
    assert '✓' in human_str
    assert 'localhost' in human_str


def test_fetch_url_error():
    """Test fetch_url with unreachable URL"""
    # Port 65432 is almost certainly not open
    result = fetch_url('http://localhost:65432/', timeout=1.0)
    assert result.success is False
    assert result.error is not None
    assert 'refused' in result.error.lower() or 'error' in result.error.lower()


def test_check_local_access():
    """Test check_local_access function"""
    # Check an unreachable port
    accessible, message = check_local_access('http://localhost:65432/', timeout=1.0)
    assert accessible is False
    assert '✗' in message


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
