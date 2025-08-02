#!/usr/bin/env python3
"""
ssh-primer.py

This script primes the local machine’s SSH server for initial password‐based authentication.
It does the following:
  - Modifies the SSH server configuration (sshd_config) to:
      • Allow password authentication (PasswordAuthentication yes)
      • Set the SSH port to the provided value
  - Restarts the SSH server so the changes take effect.
  - Sets an environment variable (DASHBOARD_REPO) in the user’s shell configuration (for Linux)
    so that the dashboard repository’s location is known.

Usage:
    python3 ssh-primer.py --ssh-port <port> --repo-dir <dashboard_repo_directory>
"""

import argparse
import os
import platform
import subprocess
from cross_platform.debug_utils import write_debug

def modify_ssh_config(ssh_port, password_auth=True):
    # Determine the sshd_config file location based on OS.
    if platform.system() == "Windows":
        config_path = r"C:\ProgramData\ssh\sshd_config"
        restart_cmd = "powershell.exe -Command \"Restart-Service sshd\""
    else:
        config_path = "/etc/ssh/sshd_config"
        restart_cmd = "sudo systemctl restart sshd || sudo service ssh restart"
    
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                lines = f.readlines()
        except Exception as e:
            write_debug(f"Failed to read {config_path}: {e}", channel="Error")
            return False
        
        new_lines = []
        port_set = False
        password_auth_set = False
        for line in lines:
            if line.strip().startswith("Port"):
                new_lines.append(f"Port {ssh_port}\n")
                port_set = True
            elif line.strip().startswith("PasswordAuthentication"):
                new_lines.append(f"PasswordAuthentication {'yes' if password_auth else 'no'}\n")
                password_auth_set = True
            else:
                new_lines.append(line)
        if not port_set:
            new_lines.append(f"Port {ssh_port}\n")
        if not password_auth_set:
            new_lines.append(f"PasswordAuthentication {'yes' if password_auth else 'no'}\n")
        
        try:
            with open(config_path, "w") as f:
                f.writelines(new_lines)
            write_debug(f"Modified SSH config at {config_path} to set port {ssh_port} and PasswordAuthentication {'yes' if password_auth else 'no'}.", channel="Information")
        except Exception as e:
            write_debug(f"Failed to write SSH config: {e}", channel="Error")
            return False
    else:
        write_debug(f"SSH config not found at {config_path}.", channel="Warning")
        print("SSH server config not found. Please ensure an SSH server is installed.")
        return False

    # Restart the SSH server
    write_debug(f"Restarting SSH server with command: {restart_cmd}", channel="Debug")
    result = subprocess.run(restart_cmd, shell=True)
    if result.returncode == 0:
        write_debug("SSH server restarted successfully.", channel="Information")
        return True
    else:
        write_debug("SSH server restart failed.", channel="Error")
        return False

def set_dashboard_repo_env(repo_dir):
    # For Linux: modify ~/.bashrc to export DASHBOARD_REPO.
    if platform.system() == "Windows":
        write_debug("Setting DASHBOARD_REPO env variable on Windows is not automated in this script.", channel="Warning")
        return
    bashrc = os.path.expanduser("~/.bashrc")
    env_line = f"export DASHBOARD_REPO={repo_dir}\n"
    try:
        if os.path.exists(bashrc):
            with open(bashrc, "r") as f:
                content = f.read()
            if "DASHBOARD_REPO=" not in content:
                with open(bashrc, "a") as f:
                    f.write("\n# Dashboard repo environment variable\n" + env_line)
                write_debug("Added DASHBOARD_REPO to ~/.bashrc", channel="Information")
            else:
                write_debug("DASHBOARD_REPO already set in ~/.bashrc", channel="Debug")
        else:
            write_debug("~/.bashrc not found. Skipping environment variable setup.", channel="Warning")
    except Exception as e:
        write_debug(f"Failed to set DASHBOARD_REPO in ~/.bashrc: {e}", channel="Error")

def main():
    parser = argparse.ArgumentParser(description="SSH Primer Script")
    parser.add_argument("--ssh-port", type=int, required=True, help="The SSH port the machine will use")
    parser.add_argument("--repo-dir", type=str, required=True, help="Dashboard repository directory path")
    args = parser.parse_args()

    # Modify SSH config to accept password authentication and set the provided port.
    if not modify_ssh_config(args.ssh_port, password_auth=True):
        print("Failed to modify SSH configuration.")
        return

    # Set the DASHBOARD_REPO environment variable for future sessions.
    set_dashboard_repo_env(args.repo_dir)

    print(f"Machine primed: SSH server now accepts password authentication on port {args.ssh_port}.")
    print("Please ensure that this script (ssh-primer.py) is available in your dashboard repository.")

if __name__ == "__main__":
    main()