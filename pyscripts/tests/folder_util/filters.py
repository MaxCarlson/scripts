# folder_util/filters.py

import re
import datetime
from typing import List, Dict, Any

def filter_by_size(items: List[Dict[str, Any]], min_size: int = None, max_size: int = None) -> List[Dict[str, Any]]:
    filtered = []
    for item in items:
        size = item.get('size', 0)
        if min_size is not None and size < min_size:
            continue
        if max_size is not None and size > max_size:
            continue
        filtered.append(item)
    return filtered

def filter_by_date(items: List[Dict[str, Any]], start_date: datetime.datetime = None, end_date: datetime.datetime = None,
                   date_field: str = "date_created") -> List[Dict[str, Any]]:
    filtered = []
    for item in items:
        date_val = item.get(date_field, None)
        if date_val is None:
            continue
        if start_date and date_val < start_date:
            continue
        if end_date and date_val > end_date:
            continue
        filtered.append(item)
    return filtered

def filter_by_regex(items: List[Dict[str, Any]], pattern: str, field: str = "name") -> List[Dict[str, Any]]:
    regex = re.compile(pattern)
    return [item for item in items if regex.search(item.get(field, ""))]