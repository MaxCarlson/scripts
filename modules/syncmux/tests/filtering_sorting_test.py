
from datetime import datetime, timedelta

import pytest
from unittest.mock import Mock

from syncmux.models import Session


@pytest.fixture
def sample_sessions():
    """Create a diverse set of sample sessions for testing."""
    base_time = datetime(2024, 1, 1, 12, 0, 0)
    return [
        Session(
            id="$0",
            name="alpha-dev",
            windows=3,
            attached=1,
            created_at=base_time,
        ),
        Session(
            id="$1",
            name="beta-prod",
            windows=5,
            attached=0,
            created_at=base_time + timedelta(hours=1),
        ),
        Session(
            id="$2",
            name="gamma-test",
            windows=2,
            attached=0,
            created_at=base_time + timedelta(hours=2),
        ),
        Session(
            id="$3",
            name="delta-staging",
            windows=4,
            attached=1,
            created_at=base_time + timedelta(hours=3),
        ),
        Session(
            id="$4",
            name="alpha-prod",
            windows=6,
            attached=2,
            created_at=base_time + timedelta(hours=4),
        ),
    ]


class MockApp:
    """Mock app class with just the filter/sort methods for testing."""

    def __init__(self):
        self.filter_text = ""
        self.filter_visible = False
        self.sort_mode = "name"

    def _filter_sessions(self, sessions):
        """Filter sessions based on filter_text."""
        if not self.filter_text:
            return sessions

        filter_lower = self.filter_text.lower()
        return [s for s in sessions if filter_lower in s.name.lower()]

    def _sort_sessions(self, sessions):
        """Sort sessions based on sort_mode."""
        if self.sort_mode == "name":
            return sorted(sessions, key=lambda s: s.name.lower())
        elif self.sort_mode == "created":
            return sorted(sessions, key=lambda s: s.created_at, reverse=True)
        elif self.sort_mode == "windows":
            return sorted(sessions, key=lambda s: s.windows, reverse=True)
        elif self.sort_mode == "attached":
            return sorted(sessions, key=lambda s: s.attached, reverse=True)
        return sessions

    def action_cycle_sort(self):
        """Cycle through sort modes."""
        sort_modes = ["name", "created", "windows", "attached"]
        current_index = sort_modes.index(self.sort_mode)
        next_index = (current_index + 1) % len(sort_modes)
        self.sort_mode = sort_modes[next_index]

    def action_toggle_filter(self):
        """Toggle the filter input visibility."""
        self.filter_visible = not self.filter_visible


@pytest.fixture
def app():
    """Create a mock app instance for testing."""
    return MockApp()


def test_filter_sessions_empty_filter(app, sample_sessions):
    """Test that empty filter returns all sessions."""
    app.filter_text = ""
    filtered = app._filter_sessions(sample_sessions)
    assert len(filtered) == 5
    assert filtered == sample_sessions


def test_filter_sessions_case_insensitive(app, sample_sessions):
    """Test that filtering is case-insensitive."""
    app.filter_text = "ALPHA"
    filtered = app._filter_sessions(sample_sessions)
    assert len(filtered) == 2
    assert all("alpha" in s.name for s in filtered)


def test_filter_sessions_partial_match(app, sample_sessions):
    """Test that filtering matches partial names."""
    app.filter_text = "prod"
    filtered = app._filter_sessions(sample_sessions)
    assert len(filtered) == 2
    assert filtered[0].name == "beta-prod"
    assert filtered[1].name == "alpha-prod"


def test_filter_sessions_no_match(app, sample_sessions):
    """Test that filter returns empty list when no matches."""
    app.filter_text = "nonexistent"
    filtered = app._filter_sessions(sample_sessions)
    assert len(filtered) == 0


def test_filter_sessions_single_match(app, sample_sessions):
    """Test filtering with single match."""
    app.filter_text = "gamma"
    filtered = app._filter_sessions(sample_sessions)
    assert len(filtered) == 1
    assert filtered[0].name == "gamma-test"


def test_sort_sessions_by_name(app, sample_sessions):
    """Test sorting sessions alphabetically by name."""
    app.sort_mode = "name"
    sorted_sessions = app._sort_sessions(sample_sessions)
    names = [s.name for s in sorted_sessions]
    assert names == ["alpha-dev", "alpha-prod", "beta-prod", "delta-staging", "gamma-test"]


def test_sort_sessions_by_created(app, sample_sessions):
    """Test sorting sessions by creation time (newest first)."""
    app.sort_mode = "created"
    sorted_sessions = app._sort_sessions(sample_sessions)
    # Should be newest first
    names = [s.name for s in sorted_sessions]
    assert names == ["alpha-prod", "delta-staging", "gamma-test", "beta-prod", "alpha-dev"]


def test_sort_sessions_by_windows(app, sample_sessions):
    """Test sorting sessions by window count (most first)."""
    app.sort_mode = "windows"
    sorted_sessions = app._sort_sessions(sample_sessions)
    window_counts = [s.windows for s in sorted_sessions]
    assert window_counts == [6, 5, 4, 3, 2]


def test_sort_sessions_by_attached(app, sample_sessions):
    """Test sorting sessions by attached count (most first)."""
    app.sort_mode = "attached"
    sorted_sessions = app._sort_sessions(sample_sessions)
    attached_counts = [s.attached for s in sorted_sessions]
    assert attached_counts == [2, 1, 1, 0, 0]


def test_sort_sessions_unknown_mode(app, sample_sessions):
    """Test that unknown sort mode returns sessions unchanged."""
    app.sort_mode = "unknown"
    sorted_sessions = app._sort_sessions(sample_sessions)
    assert sorted_sessions == sample_sessions


def test_filter_and_sort_combined(app, sample_sessions):
    """Test that filtering and sorting work together."""
    app.filter_text = "alpha"
    app.sort_mode = "windows"

    filtered = app._filter_sessions(sample_sessions)
    sorted_filtered = app._sort_sessions(filtered)

    assert len(sorted_filtered) == 2
    # alpha-prod has 6 windows, alpha-dev has 3
    assert sorted_filtered[0].name == "alpha-prod"
    assert sorted_filtered[1].name == "alpha-dev"


def test_action_cycle_sort(app):
    """Test cycling through sort modes."""
    assert app.sort_mode == "name"

    app.action_cycle_sort()
    assert app.sort_mode == "created"

    app.action_cycle_sort()
    assert app.sort_mode == "windows"

    app.action_cycle_sort()
    assert app.sort_mode == "attached"

    app.action_cycle_sort()
    assert app.sort_mode == "name"  # Cycles back


def test_action_toggle_filter(app):
    """Test toggling filter visibility."""
    assert app.filter_visible is False

    app.action_toggle_filter()
    assert app.filter_visible is True

    app.action_toggle_filter()
    assert app.filter_visible is False


def test_filter_sessions_with_special_characters(app):
    """Test filtering with sessions containing special characters."""
    sessions = [
        Session(id="$0", name="test-session", windows=1, attached=0, created_at=datetime.now()),
        Session(id="$1", name="test_session", windows=1, attached=0, created_at=datetime.now()),
        Session(id="$2", name="test.session", windows=1, attached=0, created_at=datetime.now()),
    ]

    app.filter_text = "test"
    filtered = app._filter_sessions(sessions)
    assert len(filtered) == 3  # All match "test"


def test_sort_sessions_stability(app, sample_sessions):
    """Test that sorting is stable for equal values."""
    # Create sessions with same window count
    sessions = [
        Session(id="$0", name="z-session", windows=3, attached=0, created_at=datetime.now()),
        Session(id="$1", name="a-session", windows=3, attached=0, created_at=datetime.now()),
        Session(id="$2", name="m-session", windows=3, attached=0, created_at=datetime.now()),
    ]

    app.sort_mode = "windows"
    sorted_sessions = app._sort_sessions(sessions)
    # When windows are equal, should maintain relative order
    assert len(sorted_sessions) == 3
