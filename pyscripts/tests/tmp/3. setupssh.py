#!/usr/bin/env python3
"""
setup_ssh.py

This script records SSH connection information between machines.
It accepts connection details as command-line arguments and appends them
to a file (connections.txt) in the dashboard repository directory.
Each new connection is recorded without overwriting existing entries.

Usage:
    python3 setup_ssh.py --action record --ip <ip_address> --username <username> --port <ssh_port>
"""
import argparse
import os
import json

def main():
    parser = argparse.ArgumentParser(description="Record SSH connection information")
    parser.add_argument("--action", type=str, required=True, help="Action to perform (record)")
    parser.add_argument("--ip", type=str, required=True, help="IP address of the connecting machine")
    parser.add_argument("--username", type=str, required=True, help="Username for SSH connection")
    parser.add_argument("--port", type=int, required=True, help="SSH port")
    args = parser.parse_args()

    if args.action != "record":
        print("Unsupported action.")
        return

    # Determine the repository directory from the DASHBOARD_REPO environment variable,
    # or fallback to the current working directory.
    repo_dir = os.environ.get("DASHBOARD_REPO", os.getcwd())
    connections_file = os.path.join(repo_dir, "connections.txt")

    connections = []
    if os.path.exists(connections_file):
        try:
            with open(connections_file, "r") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        connections.append(entry)
                    except:
                        continue
        except Exception as e:
            print(f"Error reading connections file: {e}")
    new_entry = {"ip": args.ip, "username": args.username, "port": args.port}
    if new_entry not in connections:
        try:
            with open(connections_file, "a") as f:
                f.write(json.dumps(new_entry) + "\n")
            print("Connection info recorded.")
        except Exception as e:
            print(f"Error writing connection info: {e}")
    else:
        print("Connection info already exists.")

if __name__ == "__main__":
    main()