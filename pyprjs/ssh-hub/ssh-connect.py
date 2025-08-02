#!/usr/bin/env python3
import argparse
import platform
import socket
import subprocess
import sys

# Configuration
DEVICES = {
    "desktop": {
        "hostname": "slice",
        "lan": {"user": "mcarls", "ip": "192.168.50.100", "port": 22},
        "wg": {"user": "mcarls", "ip": None, "port": 22},  # No WG IP on desktop
    },
    "laptop": {
        "hostname": "Client",
        "lan": {"user": "Client", "ip": "192.168.50.101", "port": 22},
        "wg": {"user": "Client", "ip": "10.6.0.3", "port": 22},
    },
    "phone": {
        "hostname": None,
        "lan": {"user": "u0_a142", "ip": "192.168.50.102", "port": 8022},
        "wg": {"user": "u0_a142", "ip": "10.6.0.2", "port": 8022},
    },
}

# Try connecting to a host:port to see if reachable
def can_connect(ip, port, timeout=1.5):
    try:
        with socket.create_connection((ip, port), timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False

# Try LAN then WG connection
def connect_to_device(from_device, to_device):
    if from_device == to_device:
        print("You're already on the target device.")
        sys.exit(0)

    device_info = DEVICES[to_device]
    # 1. Try LAN
    lan = device_info["lan"]
    if can_connect(lan["ip"], lan["port"]):
        cmd = ["ssh", "-p", str(lan["port"]), f'{lan["user"]}@{lan["ip"]}']
        print(f"Connecting via LAN: {' '.join(cmd)}")
        subprocess.run(cmd)
        return

    # 2. Try WireGuard
    wg = device_info["wg"]
    if wg["ip"] and can_connect(wg["ip"], wg["port"]):
        cmd = ["ssh", "-p", str(wg["port"]), f'{wg["user"]}@{wg["ip"]}']
        print(f"Connecting via WireGuard: {' '.join(cmd)}")
        subprocess.run(cmd)
        return

    print(f"❌ Unable to reach {to_device} via LAN or WireGuard.")
    sys.exit(1)

# Determine current device
def get_current_device():
    hostname = platform.node().lower()
    for name, info in DEVICES.items():
        if info["hostname"] and info["hostname"].lower() == hostname:
            return name
    if "termux" in sys.executable.lower():
        return "phone"
    return None

def main():
    parser = argparse.ArgumentParser(description="SSH connect to a known device.")
    parser.add_argument("--phone", action="store_true", help="Connect to phone")
    parser.add_argument("--laptop", action="store_true", help="Connect to laptop")
    parser.add_argument("--desktop", action="store_true", help="Connect to desktop")
    args = parser.parse_args()

    target = None
    if args.phone:
        target = "phone"
    elif args.laptop:
        target = "laptop"
    elif args.desktop:
        target = "desktop"
    else:
        print("❌ Must specify one of: --phone, --laptop, --desktop")
        sys.exit(1)

    current = get_current_device()
    if not current:
        print("❌ Could not determine current device from hostname.")
        sys.exit(1)

    connect_to_device(current, target)

if __name__ == "__main__":
    main()
