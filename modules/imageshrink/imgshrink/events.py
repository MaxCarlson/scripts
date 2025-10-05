#!/usr/bin/env python3
"""
Event models used between workers and the UI/orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Literal


EventType = Literal[
    "WORKER_ONLINE",
    "FOLDER_START",
    "FOLDER_PROGRESS",
    "FOLDER_STATS",
    "FOLDER_FINISH",
    "FOLDER_ERROR",
    "LOG",
    "SHUTDOWN",
]


@dataclass
class Event:
    type: EventType
    worker_id: int
    payload: Dict = field(default_factory=dict)


def ev(worker_id: int, etype: EventType, **payload) -> Event:
    return Event(type=etype, worker_id=worker_id, payload=payload)