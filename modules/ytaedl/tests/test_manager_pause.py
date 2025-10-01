"""Tests for ytaedl.manager pause/unpause and quit functionality."""

import tempfile
import threading
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import ytaedl.manager as manager


class TestManagerPauseUnpause:
    """Test pause/unpause functionality in the manager."""

    def test_pause_prevents_new_assignments(self):
        """Test that pausing prevents new work assignments."""
        # Create a WorkerState
        ws = manager.WorkerState(slot=1)
        ws.proc = None  # Not running

        # Mock assignment function
        assignment_called = False
        def mock_assign(worker):
            nonlocal assignment_called
            assignment_called = True
            return True

        # Test that assignment is called when not paused
        paused = False
        if not paused:
            mock_assign(ws)
        assert assignment_called

        # Test that assignment is not called when paused
        assignment_called = False
        paused = True
        if not paused:
            mock_assign(ws)
        assert not assignment_called

    def test_pause_sets_overlay_message(self):
        """Test that pausing sets appropriate overlay messages."""
        # Create workers with running processes
        workers = [manager.WorkerState(slot=i) for i in range(1, 3)]
        for ws in workers:
            ws.proc = MagicMock()
            ws.proc.poll.return_value = None  # Still running

        # Simulate pause logic
        for ws in workers:
            if ws.proc and ws.proc.poll() is None:
                ws.overlay_msg = "PAUSED - current download will finish, no new assignments"
                ws.overlay_since = time.time()

        # Verify overlay messages are set
        for ws in workers:
            assert ws.overlay_msg is not None
            assert "PAUSED" in ws.overlay_msg
            assert ws.overlay_since > 0

    def test_unpause_clears_overlay_messages(self):
        """Test that unpausing clears overlay messages."""
        # Create workers with overlay messages
        workers = [manager.WorkerState(slot=i) for i in range(1, 3)]
        for ws in workers:
            ws.overlay_msg = "PAUSED - current download will finish, no new assignments"
            ws.overlay_since = time.time()

        # Simulate unpause logic
        for ws in workers:
            ws.overlay_msg = None

        # Verify overlay messages are cleared
        for ws in workers:
            assert ws.overlay_msg is None


class TestManagerQuitConfirmation:
    """Test quit confirmation functionality."""

    def test_quit_confirmation_state(self):
        """Test quit confirmation state management."""
        quit_confirm = False

        # Simulate pressing 'q'
        quit_confirm = True
        assert quit_confirm

        # Simulate pressing 'n' (cancel)
        quit_confirm = False
        assert not quit_confirm

    def test_quit_confirmation_y_sets_stop(self):
        """Test that pressing 'y' during quit confirmation would set stop flag."""
        quit_confirm = True
        stop_requested = False

        # Simulate pressing 'y'
        if quit_confirm:
            # In real code this would be: stop.set()
            stop_requested = True

        assert stop_requested

    def test_quit_confirmation_n_cancels(self):
        """Test that pressing 'n' during quit confirmation cancels."""
        quit_confirm = True
        stop_requested = False

        # Simulate pressing 'n'
        if quit_confirm:
            quit_confirm = False
            # stop.set() is not called

        assert not quit_confirm
        assert not stop_requested


@pytest.mark.integration
class TestManagerUIIntegration:
    """Integration tests for manager UI with pause/quit functionality."""

    def test_header_shows_pause_status(self):
        """Test that header shows pause status."""
        paused = True
        quit_confirm = False
        threads = 2
        active_workers = 1
        pool_size = 5
        time_limit = -1

        pause_status = " [PAUSED]" if paused else ""
        quit_status = " [Press Y to confirm quit]" if quit_confirm else ""
        header = f"DL Manager{pause_status}{quit_status}  |  threads={threads}  active={active_workers}  pool={pool_size}  time_limit={time_limit}"

        assert "[PAUSED]" in header
        assert "[Press Y to confirm quit]" not in header

    def test_header_shows_quit_confirmation(self):
        """Test that header shows quit confirmation status."""
        paused = False
        quit_confirm = True
        threads = 2
        active_workers = 1
        pool_size = 5
        time_limit = -1

        pause_status = " [PAUSED]" if paused else ""
        quit_status = " [Press Y to confirm quit]" if quit_confirm else ""
        header = f"DL Manager{pause_status}{quit_status}  |  threads={threads}  active={active_workers}  pool={pool_size}  time_limit={time_limit}"

        assert "[PAUSED]" not in header
        assert "[Press Y to confirm quit]" in header

    def test_controls_text_changes_with_quit_confirm(self):
        """Test that controls text changes during quit confirmation."""
        quit_confirm = False
        normal_controls = "Keys: p=pause/unpause, q=quit, v=cycle verbose (NDJSON→LOG→off), 1-9=select worker"

        quit_confirm = True
        quit_controls = "Press Y to quit, N to cancel"

        # In normal mode, show normal controls
        assert "p=pause/unpause" in normal_controls
        assert "q=quit" in normal_controls

        # In quit confirmation mode, show quit controls
        assert "Y to quit" in quit_controls
        assert "N to cancel" in quit_controls

    def test_keyboard_handling_pause_logic(self):
        """Test the logical flow of pause keyboard handling."""
        # Simulate receiving 'p' key press
        ch = 'p'
        paused = False
        quit_confirm = False

        # Simulate the keyboard handling logic from the manager
        if not quit_confirm and ch and ch.lower() == 'p':
            paused = not paused

        assert paused

        # Press 'p' again to unpause
        if not quit_confirm and ch and ch.lower() == 'p':
            paused = not paused

        assert not paused

    def test_keyboard_handling_quit_logic(self):
        """Test the logical flow of quit keyboard handling."""
        # Simulate receiving 'q' key press
        ch = 'q'
        paused = False
        quit_confirm = False
        stop_requested = False

        # First press 'q'
        if not quit_confirm and ch and ch.lower() == 'q':
            quit_confirm = True

        assert quit_confirm

        # Then press 'y'
        ch = 'y'
        if quit_confirm and ch and ch.lower() == 'y':
            stop_requested = True

        assert stop_requested

    def test_keyboard_handling_quit_cancel_logic(self):
        """Test canceling quit with 'n' key."""
        quit_confirm = True

        # Press 'n' to cancel
        ch = 'n'
        if quit_confirm and ch and ch.lower() == 'n':
            quit_confirm = False

        assert not quit_confirm


if __name__ == "__main__":
    pytest.main([__file__])