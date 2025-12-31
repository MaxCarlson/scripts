#!/usr/bin/env python3
"""
TermDash state export for web viewer integration.
Allows external viewers to mirror the terminal dashboard state.
"""

import json
from typing import Dict, Any, List, Optional
from .dashboard import TermDash, _strip_ansi
from .components import Line, Stat


def export_dashboard_state(dashboard: TermDash) -> Dict[str, Any]:
    """
    Export the current state of a TermDash dashboard as a JSON-serializable dict.
    
    Args:
        dashboard: TermDash instance to export
        
    Returns:
        Dictionary containing:
        - lines: list of line states (name, rendered content, stats)
        - line_order: order of lines
        - config: dashboard configuration
    """
    with dashboard._lock_context("export_state"):
        lines_data = []
        for name in dashboard._line_order:
            line = dashboard._lines.get(name)
            if not line:
                continue
                
            line_data = {
                "name": name,
                "style": line.style,
            }
            
            # Export stats from the line
            if line.style == "separator":
                line_data["type"] = "separator"
                line_data["pattern"] = line.sep_pattern
            else:
                line_data["type"] = "stats"
                line_data["stats"] = []
                
                for stat_name in line._stat_order:
                    stat = line._stats.get(stat_name)
                    if not stat:
                        continue
                        
                    stat_data = {
                        "name": stat.name,
                        "value": stat.value,
                        "prefix": stat.prefix,
                        "unit": stat.unit,
                        "format_string": stat.format_string,
                        "rendered": _strip_ansi(stat.render()),
                    }
                    line_data["stats"].append(stat_data)
            
            lines_data.append(line_data)
        
        return {
            "lines": lines_data,
            "line_order": list(dashboard._line_order),
            "config": {
                "align_columns": dashboard.align_columns,
                "column_sep": dashboard.column_sep,
                "enable_separators": dashboard.enable_separators,
                "has_status_line": dashboard.has_status_line,
            },
        }


def export_dashboard_json(dashboard: TermDash) -> str:
    """Export dashboard state as JSON string."""
    return json.dumps(export_dashboard_state(dashboard), indent=2)


def stream_dashboard_updates(dashboard: TermDash, callback, interval: float = 0.5):
    """
    Stream dashboard updates to a callback function.
    
    Args:
        dashboard: TermDash instance to monitor
        callback: Function that receives state dict on each update
        interval: Update interval in seconds
        
    Usage:
        def my_callback(state):
            send_to_websocket(json.dumps(state))
        
        stream_dashboard_updates(dashboard, my_callback, interval=0.1)
    """
    import threading
    import time
    
    def stream_loop():
        while dashboard._running:
            try:
                state = export_dashboard_state(dashboard)
                callback(state)
            except Exception:
                pass
            time.sleep(interval)
    
    thread = threading.Thread(target=stream_loop, daemon=True)
    thread.start()
    return thread
