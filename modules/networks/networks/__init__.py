"""
Networks Module - Cross-platform networking utilities

Provides unified API for:
- Network information (IPs, interfaces, ports)
- LAN accessibility (WSL2 port forwarding, firewall rules)
- Port checking and management
"""
from .core import (
    get_lan_ip,
    get_all_ips,
    get_network_info,
    ensure_port_accessible,
    check_port_open,
    get_wsl2_host_ip,
    get_wsl2_network_info,
    list_port_forwards,
    remove_port_forward,
)

__all__ = [
    'get_lan_ip',
    'get_all_ips',
    'get_network_info',
    'ensure_port_accessible',
    'check_port_open',
    'get_wsl2_host_ip',
    'get_wsl2_network_info',
    'list_port_forwards',
    'remove_port_forward',
]

__version__ = '0.1.0'
