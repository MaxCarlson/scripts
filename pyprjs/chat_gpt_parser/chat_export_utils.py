# chat_export_utils.py
import json
from datetime import datetime, timezone
import os

DEFAULT_CONVERSATIONS_FILE = "conversations.json"

def format_timestamp_util(ts, default_val="N/A"):
    """Converts UNIX timestamp to a human-readable string."""
    if ts is None:
        return default_val
    try:
        return datetime.fromtimestamp(float(ts), timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    except (ValueError, TypeError):
        return default_val

def load_and_sort_conversations(filepath):
    """Loads conversations.json and sorts them by update_time (most recent first)."""
    if not os.path.exists(filepath):
        print(f"Error: Source file '{filepath}' not found.")
        return None
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
        if not isinstance(raw_data, list):
            print(f"Error: Expected a list of conversations in {filepath}, but got {type(raw_data)}")
            return None
        
        # Sort by 'update_time' primarily, fallback to 'create_time' if update_time is missing
        # We want the latest modified conversation to appear first for a gizmo_id
        def sort_key(c):
            if not isinstance(c, dict): return 0
            update_time = c.get("update_time")
            create_time = c.get("create_time")
            if update_time is not None:
                return float(update_time)
            if create_time is not None:
                return float(create_time)
            return 0

        sorted_conversations = sorted(raw_data, key=sort_key, reverse=True)
        print(f"Successfully loaded and sorted {len(sorted_conversations)} conversations from '{filepath}'.")
        return sorted_conversations
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from '{filepath}'. It might be corrupted.")
        return None
    except Exception as e:
        print(f"An unexpected error occurred while loading or sorting '{filepath}': {e}")
        return None

if __name__ == '__main__':
    # Example usage if run directly (for testing utils)
    print("Chat Export Utilities Module")
    # test_data = load_and_sort_conversations("conversations.json")
    # if test_data:
    #     print(f"First conversation title after sort: {test_data[0].get('title')}")
    #     print(f"Update time: {format_timestamp_util(test_data[0].get('update_time'))}")
    #     print(f"Create time: {format_timestamp_util(test_data[0].get('create_time'))}")
