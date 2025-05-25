#!/usr/bin/env python3
"""
cross_platform/tmux_utils.py

Cross-platform tmux manager utilities for session handling.
Requires tmux to be installed and in PATH.
Requires fzf for fuzzy finding capabilities.
"""

import subprocess
import argparse
import sys
import os
import platform # For OS-specific default commands

# Attempt to import SystemUtils for potential future use or consistency
# If not directly needed by TmuxManager, this can be omitted.
# from .system_utils import SystemUtils # Assuming it's in the same package
from .debug_utils import write_debug # Assuming debug_utils.py is in the same package

class TmuxManager: # Inherit from SystemUtils if common methods are needed
    def __init__(self):
        # self.os_name = platform.system().lower() # If not inheriting SystemUtils
        pass

    def _is_tmux_installed(self):
        try:
            subprocess.run(['tmux', '-V'], capture_output=True, text=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            write_debug("tmux is not installed or not in PATH.", channel="Error")
            return False

    def _is_fzf_installed(self):
        try:
            subprocess.run(['fzf', '--version'], capture_output=True, text=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            write_debug("fzf is not installed or not in PATH. Fuzzy finding will not work.", channel="Warning")
            return False

    def _run_tmux_command(self, cmd_args):
        """Run a tmux command and return (returncode, stdout, stderr)."""
        if not self._is_tmux_installed():
            return 1, "", "tmux not found."
        try:
            proc = subprocess.run(['tmux'] + cmd_args, capture_output=True, text=True, check=False)
            write_debug(f"tmux command: {' '.join(['tmux'] + cmd_args)} -> RC: {proc.returncode}", channel="Debug")
            write_debug(f"tmux stdout: {proc.stdout.strip()}", channel="Verbose")
            if proc.stderr.strip():
                 write_debug(f"tmux stderr: {proc.stderr.strip()}", channel="Verbose")
            return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
        except Exception as e:
            write_debug(f"Exception running tmux command {' '.join(cmd_args)}: {e}", channel="Error")
            return -1, "", str(e)

    def list_sessions_raw(self, format_string="'#{session_name}'"):
        """Returns a list of session names or other formatted info."""
        rc, out, _ = self._run_tmux_command(['list-sessions', '-F', format_string])
        if rc == 0 and out:
            return out.splitlines()
        return []

    def list_sessions_pretty(self):
        rc, out, err = self._run_tmux_command(['list-sessions'])
        if rc != 0:
            # Tmux list-sessions returns non-zero with "no server running on /tmp/tmux-1000/default"
            # or similar if no sessions, which is not an error for "ls" itself.
            if "no server" in err.lower() or "no sessions" in err.lower(): # Check common messages
                 print("No tmux sessions.")
            elif err:
                 print(f"Error listing sessions: {err}")
            else: # Fallback if no specific error message but non-zero RC
                 print("No tmux sessions or server not running.")

        else:
            print(out)


    def session_exists(self, session_name):
        rc, _, _ = self._run_tmux_command(['has-session', '-t', session_name])
        return rc == 0

    def attach_or_create_session(self, session_name, default_command=None):
        if not self._is_tmux_installed(): return

        is_inside_tmux = bool(os.environ.get("TMUX"))
        
        if self.session_exists(session_name):
            write_debug(f"Session '{session_name}' exists.", channel="Debug")
            if is_inside_tmux:
                write_debug("Inside tmux. Switching client.", channel="Information")
                self._run_tmux_command(['switch-client', '-t', session_name])
            else:
                write_debug("Outside tmux. Attaching session.", channel="Information")
                # For attaching, we typically want the tmux command to take over the terminal
                # So, we might not use _run_tmux_command if it captures output in a way that
                # prevents interactive attachment. Using os.execvp or subprocess.call might be better.
                try:
                    # Using call to make it blocking and allow tmux to take over
                    subprocess.call(['tmux', 'attach-session', '-t', session_name])
                except Exception as e:
                    print(f"Failed to attach to session {session_name}: {e}")
        else:
            write_debug(f"Session '{session_name}' does not exist. Creating.", channel="Information")
            cmd = ['new-session', '-s', session_name, '-n', 'shell'] # Default window name 'shell'
            if default_command:
                cmd.append(default_command)
            elif platform.system().lower() == "windows":
                # Try to find pwsh or powershell for Windows default
                # This is a basic check; a more robust path check might be needed
                if subprocess.run(['where', 'pwsh'], capture_output=True, check=False).returncode == 0:
                     cmd.append('pwsh')
                elif subprocess.run(['where', 'powershell'], capture_output=True, check=False).returncode == 0:
                     cmd.append('powershell')
            
            try:
                subprocess.call(['tmux'] + cmd) # Use call for interactive session creation
            except Exception as e:
                print(f"Failed to create session {session_name}: {e}")

    def next_available_session(self):
        if not self._is_tmux_installed(): return
        existing = self.list_sessions_raw()
        idx = 1
        while True:
            next_name = f"ts{idx}"
            if next_name not in existing:
                self.attach_or_create_session(next_name)
                break
            idx += 1
            if idx > 1000: # Safety break
                print("Error: Could not find an available 'tsN' session name.")
                break
    
    def reattach_last_detached(self):
        if not self._is_tmux_installed(): return
        detached_sessions = []
        # Format: session_name session_attached (0 for detached)
        sessions_info = self.list_sessions_raw(format_string="'#{session_name} #{session_attached}'")
        for line in sessions_info:
            parts = line.split()
            if len(parts) == 2 and parts[1] == '0':
                detached_sessions.append(parts[0])
        
        if detached_sessions:
            # Tmux list-sessions usually lists sessions by creation time or activity.
            # The "last" detached might mean the last one in this list.
            session_to_attach = detached_sessions[-1] 
            write_debug(f"Reattaching to last detached session: {session_to_attach}", channel="Information")
            self.attach_or_create_session(session_to_attach)
        else:
            print("No detached sessions.")

    def fuzzy_find_session(self, detached_only=False):
        if not self._is_tmux_installed() or not self._is_fzf_installed(): return

        if detached_only:
            sessions_info = self.list_sessions_raw(format_string="'#{session_name} #{session_attached}'")
            items_to_fzf = [s.split()[0] for s in sessions_info if s.endswith(' 0')]
            if not items_to_fzf:
                print("No detached sessions.")
                return
        else:
            items_to_fzf = self.list_sessions_raw()
            if not items_to_fzf:
                print("No sessions.")
                return
        
        sessions_str = "\n".join(items_to_fzf)
        try:
            fzf_proc = subprocess.run(['fzf'], input=sessions_str, text=True, capture_output=True, check=True)
            selected_session = fzf_proc.stdout.strip()
            if selected_session:
                self.attach_or_create_session(selected_session)
        except subprocess.CalledProcessError:
            write_debug("fzf selection cancelled or failed.", channel="Information")
        except FileNotFoundError:
            print("Error: fzf command not found.")
        except Exception as e:
            print(f"Error during fuzzy find: {e}")

    def rename_current_session(self, new_name):
        if not self._is_tmux_installed(): return
        if not os.environ.get("TMUX"):
            print("Not inside a tmux session. Cannot rename.")
            # Or, you could allow renaming a target session: rename_session(target_session, new_name)
            return
        rc, _, err = self._run_tmux_command(['rename-session', new_name])
        if rc == 0:
            print(f"Session renamed to: {new_name}")
        else:
            print(f"Error renaming session: {err}")

    def detach_client(self):
        if not self._is_tmux_installed(): return
        if not os.environ.get("TMUX"):
            print("Not inside a tmux session. Nothing to detach.")
            return
        rc, _, err = self._run_tmux_command(['detach-client'])
        if rc != 0:
            print(f"Error detaching client: {err}")
        # No output on success is standard for detach

def main():
    # Initialize debug_utils if you have global settings for it
    # from .debug_utils import set_console_verbosity, enable_file_logging
    # set_console_verbosity("Information") # Example
    # enable_file_logging() # Example

    manager = TmuxManager()

    parser = argparse.ArgumentParser(description="Cross-platform tmux manager script.")
    subparsers = parser.add_subparsers(dest='command', title='commands', required=True)

    # ts: attach/create session
    parser_ts = subparsers.add_parser('ts', help="Attach to or create a session. Args: [session_name (default: '1')]")
    parser_ts.add_argument('session_name', nargs='?', default='1', help="Name of the session.")
    
    # tsl: list sessions
    subparsers.add_parser('ls', help="List all tmux sessions.") # Renamed to 'ls' for consistency with tmux ls

    # tsnxt: next available session
    subparsers.add_parser('tsnxt', help="Create and attach to the next available 'tsN' session.")

    # tsr: reattach last detached session
    subparsers.add_parser('tsr', help="Re-attach to the last detached session.")

    # tsf: fuzzy find session
    subparsers.add_parser('tsf', help="Fuzzy find and attach to any session.")

    # tsd: fuzzy find detached session
    subparsers.add_parser('tsd', help="Fuzzy find and attach to a detached session.")
    
    # tsrename: rename current session
    parser_rename = subparsers.add_parser('tsrename', help="Rename the current tmux session. Args: <new_name>")
    parser_rename.add_argument('new_name', help="The new name for the session.")

    # tmd: detach client
    subparsers.add_parser('tmd', help="Detach the current tmux client.")

    args = parser.parse_args()

    if not manager._is_tmux_installed():
        sys.exit(1)

    if args.command == 'ts':
        manager.attach_or_create_session(args.session_name)
    elif args.command == 'ls':
        manager.list_sessions_pretty()
    elif args.command == 'tsnxt':
        manager.next_available_session()
    elif args.command == 'tsr':
        manager.reattach_last_detached()
    elif args.command == 'tsf':
        manager.fuzzy_find_session(detached_only=False)
    elif args.command == 'tsd':
        manager.fuzzy_find_session(detached_only=True)
    elif args.command == 'tsrename':
        manager.rename_current_session(args.new_name)
    elif args.command == 'tmd':
        manager.detach_client()

if __name__ == '__main__':
    main()
