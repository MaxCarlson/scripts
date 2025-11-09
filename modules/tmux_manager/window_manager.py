#!/usr/bin/env python3
"""
Tmux Window Manager
Advanced window management operations for tmux.
"""

import subprocess
import os
import sys


class TmuxWindowManager:
    """Manager for tmux window operations."""

    def __init__(self):
        pass

    def _is_tmux_installed(self):
        """Check if tmux is installed."""
        try:
            subprocess.run(['tmux', '-V'], capture_output=True, text=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def _is_fzf_installed(self):
        """Check if fzf is installed."""
        try:
            subprocess.run(['fzf', '--version'], capture_output=True, text=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def _run_tmux_command(self, cmd_args):
        """Run a tmux command and return (returncode, stdout, stderr)."""
        if not self._is_tmux_installed():
            return 1, "", "tmux not found."
        try:
            proc = subprocess.run(['tmux'] + cmd_args, capture_output=True, text=True, check=False)
            return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
        except Exception as e:
            return -1, "", str(e)

    def _get_current_session(self):
        """Get the current session name if inside tmux."""
        if not os.environ.get("TMUX"):
            return None
        rc, out, _ = self._run_tmux_command(['display-message', '-p', '#{session_name}'])
        return out if rc == 0 else None

    def _get_current_window_index(self):
        """Get the current window index if inside tmux."""
        if not os.environ.get("TMUX"):
            return None
        rc, out, _ = self._run_tmux_command(['display-message', '-p', '#{window_index}'])
        return int(out) if rc == 0 and out.isdigit() else None

    def session_exists(self, session_name):
        """Check if a session exists."""
        rc, _, _ = self._run_tmux_command(['has-session', '-t', session_name])
        return rc == 0

    def list_sessions(self):
        """Get list of session names."""
        rc, out, _ = self._run_tmux_command(['list-sessions', '-F', '#{session_name}'])
        if rc == 0 and out:
            return out.splitlines()
        return []

    def list_windows(self, session_name=None, format_string='#{window_index} #{window_name}'):
        """List windows for a session."""
        if session_name is None:
            session_name = self._get_current_session()
            if session_name is None:
                return []

        rc, out, _ = self._run_tmux_command(['list-windows', '-t', session_name, '-F', format_string])
        if rc == 0 and out:
            return out.splitlines()
        return []

    def get_window_indices(self, session_name=None):
        """Get list of window indices for a session."""
        windows = self.list_windows(session_name, format_string='#{window_index}')
        return [int(w) for w in windows if w.isdigit()]

    def window_exists(self, window_index, session_name=None):
        """Check if a window exists in a session."""
        indices = self.get_window_indices(session_name)
        return window_index in indices

    def _parse_window_spec(self, spec):
        """
        Parse window specification into a list of window indices.
        Supports:
        - Single index: "5" -> [5]
        - Range: "4..10" or "4:10" -> [4,5,6,7,8,9,10]
        - Comma-separated: "1,7,8,11" -> [1,7,8,11]
        - Negative indices: -1 for last, -2 for second-to-last, etc.
        Returns (indices_list, needs_resolution) where needs_resolution indicates negative indices need session context
        """
        if spec is None:
            return [], False

        spec = str(spec).strip()
        indices = []
        needs_resolution = False

        # Check for comma-separated list
        if ',' in spec:
            for part in spec.split(','):
                part = part.strip()
                if part.startswith('-'):
                    needs_resolution = True
                    indices.append(int(part))
                elif part.lstrip('-').isdigit():
                    indices.append(int(part))
        # Check for range
        elif '..' in spec or ':' in spec:
            separator = '..' if '..' in spec else ':'
            parts = spec.split(separator)
            if len(parts) == 2:
                start = parts[0].strip()
                end = parts[1].strip()

                # Handle negative indices in ranges
                if start.startswith('-') or end.startswith('-'):
                    needs_resolution = True
                    start_val = int(start) if start else 0
                    end_val = int(end) if end else -1
                    return (start_val, end_val), True

                start_idx = int(start) if start.lstrip('-').isdigit() else 0
                end_idx = int(end) if end.lstrip('-').isdigit() else 0
                indices = list(range(start_idx, end_idx + 1))
        # Single index
        elif spec.lstrip('-').isdigit():
            if spec.startswith('-'):
                needs_resolution = True
            indices.append(int(spec))

        return indices, needs_resolution

    def _resolve_negative_indices(self, indices, session_name=None):
        """Resolve negative indices to actual window indices."""
        all_indices = sorted(self.get_window_indices(session_name))
        if not all_indices:
            return []

        resolved = []
        for idx in indices:
            if isinstance(idx, tuple):  # Range with negative indices
                start, end = idx
                if start < 0:
                    start = all_indices[start] if abs(start) <= len(all_indices) else all_indices[0]
                if end < 0:
                    end = all_indices[end] if abs(end) <= len(all_indices) else all_indices[-1]
                resolved.extend(range(start, end + 1))
            elif idx < 0:
                if abs(idx) <= len(all_indices):
                    resolved.append(all_indices[idx])
            else:
                resolved.append(idx)

        return resolved

    def _fuzzy_select_window(self, session_name=None, prompt="Select window: "):
        """Use fzf to select a window interactively."""
        if not self._is_fzf_installed():
            print("Error: fzf is not installed")
            return None

        windows = self.list_windows(session_name)
        if not windows:
            print("No windows available.")
            return None

        windows_str = "\n".join(windows)
        try:
            fzf_proc = subprocess.run(['fzf', '--prompt', prompt],
                                     input=windows_str, text=True,
                                     capture_output=True, check=True)
            selected = fzf_proc.stdout.strip()
            if selected:
                # Extract just the index (first part)
                return int(selected.split()[0])
            return None
        except subprocess.CalledProcessError:
            return None
        except Exception as e:
            print(f"Error during fuzzy select: {e}")
            return None

    def _fuzzy_select_session(self, prompt="Select session: "):
        """Use fzf to select a session interactively."""
        if not self._is_fzf_installed():
            print("Error: fzf is not installed")
            return None

        sessions = self.list_sessions()
        if not sessions:
            print("No sessions available.")
            return None

        sessions_str = "\n".join(sessions)
        try:
            fzf_proc = subprocess.run(['fzf', '--prompt', prompt],
                                     input=sessions_str, text=True,
                                     capture_output=True, check=True)
            selected = fzf_proc.stdout.strip()
            return selected if selected else None
        except subprocess.CalledProcessError:
            return None
        except Exception as e:
            print(f"Error during fuzzy select: {e}")
            return None

    def close_windows(self, window_spec, session_name=None):
        """
        Close windows based on specification.
        Examples:
            close_windows("5") - close window 5
            close_windows("4..10") - close windows 4 through 10
            close_windows("1,7,8,11") - close windows 1, 7, 8, and 11
            close_windows("-1") - close last window
            close_windows("4..-1") - close from window 4 to last window
        """
        if session_name is None:
            session_name = self._get_current_session()
            if session_name is None:
                print("Error: Not in tmux and no session specified")
                return False

        indices, needs_resolution = self._parse_window_spec(window_spec)

        if needs_resolution:
            indices = self._resolve_negative_indices(indices, session_name)

        if not indices:
            print(f"Error: Invalid window specification '{window_spec}'")
            return False

        # Validate all indices exist
        valid_indices = self.get_window_indices(session_name)
        invalid = [i for i in indices if i not in valid_indices]
        if invalid:
            print(f"Error: Invalid window indices: {invalid}")
            return False

        # Close windows
        success_count = 0
        for idx in sorted(indices, reverse=True):  # Close in reverse to avoid index shifting
            rc, _, err = self._run_tmux_command(['kill-window', '-t', f'{session_name}:{idx}'])
            if rc == 0:
                success_count += 1
                print(f"Closed window {idx} in session '{session_name}'")
            else:
                print(f"Error closing window {idx}: {err}")

        return success_count == len(indices)

    def move_window_same_session(self, target_index=None, source_index=None, session_name=None):
        """
        Move a window to a different index in the same session.
        If target_index is None, use fzf to select.
        If source_index is None, use current window.
        """
        if session_name is None:
            session_name = self._get_current_session()
            if session_name is None:
                print("Error: Not in tmux and no session specified")
                return False

        # Determine source window
        if source_index is None:
            source_index = self._get_current_window_index()
            if source_index is None:
                print("Error: Could not determine current window")
                return False

        # Validate source exists
        if not self.window_exists(source_index, session_name):
            print(f"Error: Source window {source_index} does not exist")
            return False

        # Determine target index
        if target_index is None:
            target_index = self._fuzzy_select_window(session_name, "Move to window index: ")
            if target_index is None:
                print("No target window selected")
                return False

        # Resolve negative index
        if target_index < 0:
            indices = sorted(self.get_window_indices(session_name))
            if abs(target_index) <= len(indices):
                target_index = indices[target_index]
            else:
                print(f"Error: Invalid target index {target_index}")
                return False

        # Move window
        rc, _, err = self._run_tmux_command(['move-window', '-s', f'{session_name}:{source_index}',
                                            '-t', f'{session_name}:{target_index}'])
        if rc == 0:
            print(f"Moved window {source_index} to index {target_index} in session '{session_name}'")
            return True
        else:
            print(f"Error moving window: {err}")
            return False

    def swap_window_same_session(self, target_index=None, source_index=None, session_name=None):
        """
        Swap a window with another in the same session.
        If target_index is None, use fzf to select.
        If source_index is None, use current window.
        """
        if session_name is None:
            session_name = self._get_current_session()
            if session_name is None:
                print("Error: Not in tmux and no session specified")
                return False

        # Determine source window
        if source_index is None:
            source_index = self._get_current_window_index()
            if source_index is None:
                print("Error: Could not determine current window")
                return False

        # Validate source exists
        if not self.window_exists(source_index, session_name):
            print(f"Error: Source window {source_index} does not exist")
            return False

        # Determine target index
        if target_index is None:
            target_index = self._fuzzy_select_window(session_name, "Swap with window index: ")
            if target_index is None:
                print("No target window selected")
                return False

        # Resolve negative index
        if target_index < 0:
            indices = sorted(self.get_window_indices(session_name))
            if abs(target_index) <= len(indices):
                target_index = indices[target_index]
            else:
                print(f"Error: Invalid target index {target_index}")
                return False

        # Validate target exists
        if not self.window_exists(target_index, session_name):
            print(f"Error: Target window {target_index} does not exist")
            return False

        # Swap window
        rc, _, err = self._run_tmux_command(['swap-window', '-s', f'{session_name}:{source_index}',
                                            '-t', f'{session_name}:{target_index}'])
        if rc == 0:
            print(f"Swapped window {source_index} with {target_index} in session '{session_name}'")
            return True
        else:
            print(f"Error swapping window: {err}")
            return False

    def move_window_to_session(self, target_session=None, target_index=None,
                               source_index=None, source_session=None):
        """
        Move a window to a different session.
        If target_session is None, use fzf to select.
        If target_index is None, append to end of target session.
        If source_index is None, use current window.
        If source_session is None, use current session.
        """
        # Determine source session
        if source_session is None:
            source_session = self._get_current_session()
            if source_session is None:
                print("Error: Not in tmux and no source session specified")
                return False

        # Determine source window
        if source_index is None:
            source_index = self._get_current_window_index()
            if source_index is None:
                print("Error: Could not determine current window")
                return False

        # Validate source
        if not self.window_exists(source_index, source_session):
            print(f"Error: Source window {source_index} does not exist in session '{source_session}'")
            return False

        # Determine target session
        if target_session is None:
            target_session = self._fuzzy_select_session("Move to session: ")
            if target_session is None:
                print("No target session selected")
                return False

        # Validate target session exists
        if not self.session_exists(target_session):
            print(f"Error: Target session '{target_session}' does not exist")
            return False

        # Determine target index
        if target_index is not None:
            # Resolve negative index
            if target_index < 0:
                indices = sorted(self.get_window_indices(target_session))
                if not indices:
                    target_index = 0
                elif abs(target_index) <= len(indices):
                    target_index = indices[target_index]
                else:
                    print(f"Warning: Invalid target index {target_index}, appending to end")
                    target_index = None

        # Move window
        if target_index is None:
            # Append to end
            rc, _, err = self._run_tmux_command(['move-window', '-s', f'{source_session}:{source_index}',
                                                '-t', target_session])
        else:
            rc, _, err = self._run_tmux_command(['move-window', '-s', f'{source_session}:{source_index}',
                                                '-t', f'{target_session}:{target_index}'])

        if rc == 0:
            if target_index is None:
                print(f"Moved window {source_index} from '{source_session}' to end of '{target_session}'")
            else:
                print(f"Moved window {source_index} from '{source_session}' to '{target_session}:{target_index}'")
            return True
        else:
            if "invalid index" in err.lower():
                print(f"Warning: Invalid target index, moving to end of session")
                # Retry without target index
                rc, _, err = self._run_tmux_command(['move-window', '-s', f'{source_session}:{source_index}',
                                                    '-t', target_session])
                if rc == 0:
                    print(f"Moved window {source_index} from '{source_session}' to end of '{target_session}'")
                    return True
            print(f"Error moving window: {err}")
            return False

    def swap_window_between_sessions(self, target_session=None, target_index=None,
                                     source_index=None, source_session=None):
        """
        Swap a window with a window in a different session.
        If target_session is None, use fzf to select.
        If target_index is None, use fzf to select window in target session.
        If source_index is None, use current window.
        If source_session is None, use current session.
        """
        # Determine source session
        if source_session is None:
            source_session = self._get_current_session()
            if source_session is None:
                print("Error: Not in tmux and no source session specified")
                return False

        # Determine source window
        if source_index is None:
            source_index = self._get_current_window_index()
            if source_index is None:
                print("Error: Could not determine current window")
                return False

        # Validate source
        if not self.window_exists(source_index, source_session):
            print(f"Error: Source window {source_index} does not exist in session '{source_session}'")
            return False

        # Determine target session
        if target_session is None:
            target_session = self._fuzzy_select_session("Swap with session: ")
            if target_session is None:
                print("No target session selected")
                return False

        # Validate target session exists
        if not self.session_exists(target_session):
            print(f"Error: Target session '{target_session}' does not exist")
            return False

        # Determine target window
        if target_index is None:
            target_index = self._fuzzy_select_window(target_session, "Swap with window: ")
            if target_index is None:
                print("No target window selected")
                return False

        # Resolve negative index
        if target_index < 0:
            indices = sorted(self.get_window_indices(target_session))
            if abs(target_index) <= len(indices):
                target_index = indices[target_index]
            else:
                print(f"Error: Invalid target index {target_index}")
                return False

        # Validate target window exists
        if not self.window_exists(target_index, target_session):
            print(f"Error: Target window {target_index} does not exist in session '{target_session}'")
            return False

        # Swap windows
        rc, _, err = self._run_tmux_command(['swap-window', '-s', f'{source_session}:{source_index}',
                                            '-t', f'{target_session}:{target_index}'])
        if rc == 0:
            print(f"Swapped window {source_session}:{source_index} with {target_session}:{target_index}")
            return True
        else:
            print(f"Error swapping windows: {err}")
            return False
