#!/usr/bin/env python3
"""
dashboard.py

This Textual‑based dashboard provides a minimal UI to bootstrap SSH connections between machines.
When you select “Bootstrap SSH Connection,” the dashboard will:
  1. Connect to the remote machine (using password authentication)
  2. Remotely run ssh-primer.py (on the remote machine) to prime it
  3. Exchange SSH keys between the local and remote machines
  4. Disable password authentication on both machines (so only key‑based login is allowed)
  5. Record connection information on both machines via setup_ssh.py

Usage (example):
    python3 dashboard.py --local-ssh-port 2223
"""
import argparse
import os
import sys
import subprocess
import getpass
import json

import paramiko
from textual.app import App, ComposeResult
from textual.widgets import Button, Header, Footer, Static, Input, Label
from textual.containers import Vertical

from cross_platform.debug_utils import write_debug
from cross_platform.system_utils import SystemUtils

# Assume the scripts are in the same directory as the dashboard
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Helper functions to disable password authentication.
def disable_local_password_auth(ssh_port):
    if os.name == "nt" or sys.platform == "win32":
        config_path = r"C:\ProgramData\ssh\sshd_config"
        restart_cmd = "powershell.exe -Command \"Restart-Service sshd\""
    else:
        config_path = "/etc/ssh/sshd_config"
        restart_cmd = "sudo systemctl restart sshd || sudo service ssh restart"
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                lines = f.readlines()
            new_lines = []
            for line in lines:
                if line.strip().startswith("PasswordAuthentication"):
                    new_lines.append("PasswordAuthentication no\n")
                elif line.strip().startswith("Port"):
                    new_lines.append(f"Port {ssh_port}\n")
                else:
                    new_lines.append(line)
            with open(config_path, "w") as f:
                f.writelines(new_lines)
            write_debug(f"Modified local SSH config at {config_path} to disable password auth.", channel="Information")
        except Exception as e:
            write_debug(f"Failed to modify local SSH config: {e}", channel="Error")
    else:
        write_debug(f"Local SSH config not found at {config_path}.", channel="Warning")
    subprocess.run(restart_cmd, shell=True)

def disable_remote_password_auth(remote_executor, ssh_port):
    cmd = f"sudo sed -i 's/PasswordAuthentication yes/PasswordAuthentication no/g' /etc/ssh/sshd_config && sudo sed -i 's/^Port .*/Port {ssh_port}/g' /etc/ssh/sshd_config && sudo systemctl restart sshd || sudo service ssh restart"
    output, error = remote_executor.execute_command(cmd)
    if error:
        write_debug(f"Error disabling password auth on remote: {error}", channel="Error")
    else:
        write_debug("Remote SSH config updated to disable password authentication.", channel="Information")

# SSH Executor for remote command execution.
class SSHExecutor:
    def __init__(self, hostname, port, username, password=None, key_filename=None):
        self.hostname = hostname
        self.port = port
        self.username = username
        self.password = password
        self.key_filename = key_filename
        self.client = None

    def connect(self):
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            write_debug(f"Connecting to {self.hostname}:{self.port} as {self.username}", channel="Debug")
            self.client.connect(
                hostname=self.hostname,
                port=self.port,
                username=self.username,
                password=self.password,
                key_filename=self.key_filename,
                allow_agent=True,
                look_for_keys=True
            )
            write_debug("SSH connection established.", channel="Information")
            return True
        except Exception as e:
            write_debug(f"SSH connection failed: {e}", channel="Error")
            return False

    def execute_command(self, command):
        if self.client is None:
            write_debug("SSH client is not connected.", channel="Error")
            return None, None
        try:
            stdin, stdout, stderr = self.client.exec_command(command)
            output = stdout.read().decode()
            error = stderr.read().decode()
            return output, error
        except Exception as e:
            write_debug(f"Failed to execute command: {e}", channel="Error")
            return None, None

    def close(self):
        if self.client:
            self.client.close()

class DashboardApp(App):
    CSS_PATH = None

    def __init__(self, local_info, **kwargs):
        super().__init__(**kwargs)
        self.local_info = local_info
        self.system_utils = SystemUtils()
        self.current_screen = "main"  # screens: main, bootstrap, feedback

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
        if self.current_screen == "main":
            yield Static("Dashboard Main Menu", id="title")
            yield Button("Bootstrap SSH Connection", id="bootstrap")
            yield Button("Exit", id="exit")
        elif self.current_screen == "bootstrap":
            yield Static("Bootstrap SSH Connection", id="title")
            yield Label("Remote IP:")
            yield Input(placeholder="192.168.x.x", id="remote_ip")
            yield Label("Remote SSH Port (temporary):")
            yield Input(placeholder="e.g., 2222", id="remote_port")
            yield Label("Remote Username:")
            yield Input(placeholder="username", id="remote_username")
            yield Label("Remote Password:")
            yield Input(password=True, placeholder="password", id="remote_password")
            yield Button("Submit Bootstrap", id="submit_bootstrap")
            yield Button("Back", id="back_main")
        elif self.current_screen == "feedback":
            yield Static("Feedback", id="title")
            yield Static("", id="feedback")
            yield Button("Back", id="back_main")
    
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "exit":
            self.exit()
        elif btn_id == "bootstrap":
            self.current_screen = "bootstrap"
            self.refresh()
        elif btn_id == "back_main":
            self.current_screen = "main"
            self.refresh()
        elif btn_id == "submit_bootstrap":
            # Retrieve remote details from the form.
            remote_ip = self.query_one("#remote_ip", Input).value.strip()
            remote_port_str = self.query_one("#remote_port", Input).value.strip()
            remote_username = self.query_one("#remote_username", Input).value.strip()
            remote_password = self.query_one("#remote_password", Input).value.strip()
            try:
                remote_port = int(remote_port_str)
            except ValueError:
                self.query_one("#feedback", Static).update("Invalid remote port number.")
                return
            
            feedback_widget = self.query_one("#feedback", Static) if self.query("#feedback", Static) else None

            # Step 1: Connect to remote machine using password auth.
            remote_executor = SSHExecutor(remote_ip, remote_port, remote_username, password=remote_password)
            if not remote_executor.connect():
                self.current_screen = "feedback"
                self.refresh()
                if feedback_widget:
                    feedback_widget.update("Failed to connect to remote machine for priming.")
                return

            # Step 2: Run the remote primer.
            # Assumes that the remote machine has the dashboard repo in its DASHBOARD_REPO environment variable.
            remote_primer_cmd = f"python3 $DASHBOARD_REPO/ssh-primer.py --ssh-port {remote_port} --repo-dir $DASHBOARD_REPO"
            write_debug("Running remote ssh-primer to prime the remote machine.", channel="Information")
            output, error = remote_executor.execute_command(remote_primer_cmd)
            # (For brevity, we assume success if no error is returned.)
            
            # Step 3: Exchange SSH keys.
            # Locally, read our public key.
            local_pub_key_path = os.path.expanduser("~/.ssh/id_ed25519.pub")
            if not os.path.exists(local_pub_key_path):
                self.current_screen = "feedback"
                self.refresh()
                if feedback_widget:
                    feedback_widget.update("Local SSH public key not found. Please generate one first.")
                remote_executor.close()
                return
            with open(local_pub_key_path, "r") as f:
                local_pub_key = f.read().strip()
            # Add our public key to the remote's authorized_keys.
            add_key_cmd = f'echo "{local_pub_key}" >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'
            output, error = remote_executor.execute_command(add_key_cmd)
            if error:
                write_debug(f"Error adding local public key to remote: {error}", channel="Error")
                self.current_screen = "feedback"
                self.refresh()
                if feedback_widget:
                    feedback_widget.update("Failed to add local public key to remote.")
                remote_executor.close()
                return
            write_debug("Local public key added to remote authorized_keys.", channel="Information")
            # Retrieve remote public key.
            output, error = remote_executor.execute_command("cat ~/.ssh/id_ed25519.pub")
            if error or not output.strip():
                write_debug("Failed to retrieve remote SSH public key.", channel="Error")
                self.current_screen = "feedback"
                self.refresh()
                if feedback_widget:
                    feedback_widget.update("Failed to retrieve remote SSH public key.")
                remote_executor.close()
                return
            remote_pub_key = output.strip()
            # Append the remote public key to our authorized_keys.
            local_auth_keys = os.path.expanduser("~/.ssh/authorized_keys")
            with open(local_auth_keys, "a") as f:
                f.write(remote_pub_key + "\n")
            write_debug("Remote public key added to local authorized_keys.", channel="Information")
            
            # Step 4: Disable password authentication on both machines.
            disable_local_password_auth(self.local_info["ssh_port"])
            disable_remote_password_auth(remote_executor, remote_port)
            
            # Step 5: Record connection info on both machines via setup_ssh.py.
            local_ip = self.local_info.get("ip", "unknown")
            local_username = self.local_info.get("username", "unknown")
            record_cmd_remote = f"python3 $DASHBOARD_REPO/setup_ssh.py --action record --ip {local_ip} --username {local_username} --port {self.local_info['ssh_port']}"
            remote_executor.execute_command(record_cmd_remote)
            record_cmd_local = f"python3 {os.path.join(SCRIPT_DIR, 'setup_ssh.py')} --action record --ip {remote_ip} --username {remote_username} --port {remote_port}"
            subprocess.run(record_cmd_local, shell=True)
            remote_executor.close()
            
            self.current_screen = "feedback"
            self.refresh()
            if feedback_widget:
                feedback_widget.update("Bootstrap SSH connection successful. SSH keys exchanged and password auth disabled.")
    
    def on_mount(self) -> None:
        self.current_screen = "main"

def main():
    parser = argparse.ArgumentParser(description="Dashboard for SSH Bootstrap")
    parser.add_argument("--local-ssh-port", type=int, required=True, help="Local SSH port")
    parser.add_argument("--local-ip", type=str, required=False, help="Local machine IP", default="unknown")
    parser.add_argument("--local-username", type=str, required=False, help="Local username", default=os.getlogin())
    args = parser.parse_args()
    local_info = {
        "ip": args.local_ip,
        "ssh_port": args.local_ssh_port,
        "username": args.local_username,
    }
    app = DashboardApp(local_info)
    app.run()

if __name__ == "__main__":
    main()