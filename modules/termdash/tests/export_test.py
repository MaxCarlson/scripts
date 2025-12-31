#!/usr/bin/env python3
"""Tests for termdash export functionality."""

import pytest
import json
from termdash import TermDash, Stat, Line
from termdash.export import export_dashboard_state, export_dashboard_json


def test_export_empty_dashboard():
    """Test exporting an empty dashboard."""
    dashboard = TermDash(refresh_rate=1.0)
    state = export_dashboard_state(dashboard)
    
    assert "lines" in state
    assert "line_order" in state
    assert "config" in state
    assert isinstance(state["lines"], list)
    assert len(state["lines"]) == 0


def test_export_dashboard_with_stats():
    """Test exporting a dashboard with stat lines."""
    dashboard = TermDash(refresh_rate=1.0)
    
    # Add a line with stats
    line = Line("test_line", stats=[
        Stat("count", 42, prefix="Count: "),
        Stat("rate", 3.14, prefix="Rate: ", format_string="{:.2f}", unit="/s"),
    ])
    dashboard.add_line("test_line", line)
    
    state = export_dashboard_state(dashboard)
    
    assert len(state["lines"]) == 1
    line_data = state["lines"][0]
    assert line_data["name"] == "test_line"
    assert line_data["type"] == "stats"
    assert len(line_data["stats"]) == 2
    
    # Check first stat
    stat1 = line_data["stats"][0]
    assert stat1["name"] == "count"
    assert stat1["value"] == 42
    assert stat1["prefix"] == "Count: "
    
    # Check second stat
    stat2 = line_data["stats"][1]
    assert stat2["name"] == "rate"
    assert stat2["value"] == 3.14
    assert stat2["unit"] == "/s"


def test_export_dashboard_with_separator():
    """Test exporting a dashboard with separator lines."""
    dashboard = TermDash(refresh_rate=1.0, enable_separators=True)
    
    line1 = Line("line1", stats=[Stat("test", 1)])
    dashboard.add_line("line1", line1)
    dashboard.add_separator()
    line2 = Line("line2", stats=[Stat("test", 2)])
    dashboard.add_line("line2", line2)
    
    state = export_dashboard_state(dashboard)
    
    assert len(state["lines"]) == 3
    assert state["lines"][0]["type"] == "stats"
    assert state["lines"][1]["type"] == "separator"
    assert state["lines"][2]["type"] == "stats"


def test_export_json_format():
    """Test that export_dashboard_json produces valid JSON."""
    dashboard = TermDash(refresh_rate=1.0)
    line = Line("test", stats=[Stat("value", 100)])
    dashboard.add_line("test", line)
    
    json_str = export_dashboard_json(dashboard)
    
    # Should be valid JSON
    parsed = json.loads(json_str)
    assert "lines" in parsed
    assert "config" in parsed


def test_update_stat_reflected_in_export():
    """Test that updating stats is reflected in export."""
    dashboard = TermDash(refresh_rate=1.0)
    line = Line("counter", stats=[Stat("count", 0)])
    dashboard.add_line("counter", line)
    
    # Export initial state
    state1 = export_dashboard_state(dashboard)
    assert state1["lines"][0]["stats"][0]["value"] == 0
    
    # Update stat
    dashboard.update_stat("counter", "count", 99)
    
    # Export updated state
    state2 = export_dashboard_state(dashboard)
    assert state2["lines"][0]["stats"][0]["value"] == 99


def test_export_config():
    """Test that dashboard config is exported correctly."""
    dashboard = TermDash(
        refresh_rate=0.5,
        align_columns=False,
        column_sep=":",
        enable_separators=True,
        status_line=False,
    )
    
    state = export_dashboard_state(dashboard)
    config = state["config"]
    
    assert config["align_columns"] == False
    assert config["column_sep"] == ":"
    assert config["enable_separators"] == True
    assert config["has_status_line"] == False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
