#!/usr/bin/env python3
"""
Networks CLI - Network utilities from the command line
"""
import argparse
import json
import sys
from networks.core import (
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


def cmd_ip(args):
    """Show LAN IP address"""
    ip = get_lan_ip()
    if ip:
        print(ip)
        return 0
    else:
        print("Could not determine LAN IP", file=sys.stderr)
        return 1


def cmd_info(args):
    """Show comprehensive network information"""
    info = get_network_info()

    if args.json:
        print(json.dumps(info, indent=2, default=str))
    else:
        print(f"LAN IP:     {info['lan_ip']}")
        print(f"Hostname:   {info['hostname']}")
        print(f"Is WSL2:    {info['is_wsl']}")

        if info['is_wsl']:
            print(f"Host IP:    {info['wsl_host_ip']}")

        print(f"\nAll interfaces:")
        for iface in info['all_ips']:
            print(f"  {iface['interface']:15} {iface['ip']}")

    return 0


def cmd_ensure(args):
    """Ensure port is accessible on LAN"""
    success, message = ensure_port_accessible(
        args.port,
        protocol=args.protocol,
        name=args.name
    )

    print(message)

    if success:
        ip = get_lan_ip()
        if ip:
            print(f"\n✓ Access from LAN: http://{ip}:{args.port}")
        return 0
    else:
        return 1


def cmd_check(args):
    """Check if a port is open"""
    is_open = check_port_open(args.host, args.port, timeout=args.timeout)

    if is_open:
        print(f"✓ {args.host}:{args.port} is OPEN")
        return 0
    else:
        print(f"✗ {args.host}:{args.port} is CLOSED")
        return 1


def cmd_wsl_host(args):
    """Get WSL2 Windows host IP"""
    ip = get_wsl2_host_ip()
    if ip:
        print(ip)
        return 0
    else:
        print("Not running in WSL2 or could not determine host IP", file=sys.stderr)
        return 1


def cmd_wsl_info(args):
    """Show detailed WSL2 network information"""
    info = get_wsl2_network_info()
    if not info:
        print("Not running in WSL2", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(info, indent=2, default=str))
    else:
        print("WSL2 Network Information")
        print("=" * 70)
        print(f"WSL2 IP:        {info['wsl2_ip']}")
        print(f"Windows Host:   {info['windows_host_ip']} (WSL2 gateway)")
        print(f"Windows LAN:    {info['windows_lan_ip']} (accessible from network)")
        print()

        if info['port_forwards']:
            print("Port Forwarding Rules:")
            print(f"{'Listen':<20} {'Forward To':<25} {'Port':<10}")
            print("-" * 70)
            for fwd in info['port_forwards']:
                listen = f"{fwd['listen_address']}:{fwd['listen_port']}"
                forward_to = f"{fwd['connect_address']}:{fwd['connect_port']}"
                print(f"{listen:<20} → {forward_to:<23} {fwd['listen_port']:<10}")
        else:
            print("No port forwarding rules configured")

    return 0


def cmd_port_list(args):
    """List port forwarding rules"""
    forwards = list_port_forwards()

    if not forwards:
        print("No port forwarding rules found")
        return 0

    if args.json:
        print(json.dumps(forwards, indent=2))
    else:
        print(f"{'Listen Address':<20} {'Port':<10} {'→':<5} {'WSL2 Address':<20} {'Port':<10}")
        print("=" * 70)
        for fwd in forwards:
            print(f"{fwd['listen_address']:<20} {fwd['listen_port']:<10} {'→':<5} {fwd['connect_address']:<20} {fwd['connect_port']:<10}")

    return 0


def cmd_port_remove(args):
    """Remove a port forwarding rule"""
    success, message = remove_port_forward(args.port)
    print(message)
    return 0 if success else 1


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Network utilities - cross-platform networking tools",
        prog='networks'
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # networks ip - Show LAN IP
    parser_ip = subparsers.add_parser('ip', help='Show LAN IP address')
    parser_ip.set_defaults(func=cmd_ip)

    # networks info - Show all network info
    parser_info = subparsers.add_parser('info', help='Show network information')
    parser_info.add_argument(
        '-j', '--json',
        action='store_true',
        help='Output as JSON'
    )
    parser_info.set_defaults(func=cmd_info)

    # networks ensure - Make port accessible
    parser_ensure = subparsers.add_parser('ensure', help='Ensure port is accessible on LAN')
    parser_ensure.add_argument(
        '-p', '--port',
        type=int,
        required=True,
        help='Port number'
    )
    parser_ensure.add_argument(
        '-t', '--protocol',
        default='tcp',
        choices=['tcp', 'udp'],
        help='Protocol (default: tcp)'
    )
    parser_ensure.add_argument(
        '-n', '--name',
        default=None,
        help='Name for firewall rule'
    )
    parser_ensure.set_defaults(func=cmd_ensure)

    # networks check - Check if port is open
    parser_check = subparsers.add_parser('check', help='Check if a port is open')
    parser_check.add_argument(
        '-H', '--host',
        required=True,
        help='Hostname or IP address'
    )
    parser_check.add_argument(
        '-p', '--port',
        type=int,
        required=True,
        help='Port number'
    )
    parser_check.add_argument(
        '-t', '--timeout',
        type=float,
        default=2.0,
        help='Timeout in seconds (default: 2.0)'
    )
    parser_check.set_defaults(func=cmd_check)

    # networks wsl-host - Get WSL2 host IP
    parser_wsl = subparsers.add_parser('wsl-host', help='Get WSL2 Windows host IP')
    parser_wsl.set_defaults(func=cmd_wsl_host)

    # networks wsl-info - Show detailed WSL2 network info
    parser_wsl_info = subparsers.add_parser('wsl-info', help='Show detailed WSL2 network information')
    parser_wsl_info.add_argument(
        '-j', '--json',
        action='store_true',
        help='Output as JSON'
    )
    parser_wsl_info.set_defaults(func=cmd_wsl_info)

    # networks port-list - List port forwarding rules
    parser_port_list = subparsers.add_parser('port-list', help='List port forwarding rules (WSL2)')
    parser_port_list.add_argument(
        '-j', '--json',
        action='store_true',
        help='Output as JSON'
    )
    parser_port_list.set_defaults(func=cmd_port_list)

    # networks port-remove - Remove port forwarding rule
    parser_port_remove = subparsers.add_parser('port-remove', help='Remove port forwarding rule (WSL2)')
    parser_port_remove.add_argument(
        '-p', '--port',
        type=int,
        required=True,
        help='Port number to remove'
    )
    parser_port_remove.set_defaults(func=cmd_port_remove)

    # Parse args
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Run command
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
