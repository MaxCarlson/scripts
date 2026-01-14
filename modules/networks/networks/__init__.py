"""
Networks Module - Cross-platform networking utilities

Provides unified API for:
- Network information (IPs, interfaces, ports)
- LAN accessibility (WSL2 port forwarding, firewall rules)
- Port checking and management
- Local web access (fetch/screenshot URLs AI tools can't reach)
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
from .local_web import (
    fetch_url,
    screenshot_url,
    check_local_access,
    is_local_url,
    FetchResult,
    ScreenshotResult,
)

__all__ = [
    # Core networking
    'get_lan_ip',
    'get_all_ips',
    'get_network_info',
    'ensure_port_accessible',
    'check_port_open',
    'get_wsl2_host_ip',
    'get_wsl2_network_info',
    'list_port_forwards',
    'remove_port_forward',
    # Local web access
    'fetch_url',
    'screenshot_url',
    'check_local_access',
    'is_local_url',
    'FetchResult',
    'ScreenshotResult',
]

__version__ = '0.2.0'
