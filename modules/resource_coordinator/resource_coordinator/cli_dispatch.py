"""Normalize command spelling into stable operation and legacy handler fields."""

from __future__ import annotations

import argparse


def normalize_dispatch_args(args: argparse.Namespace) -> argparse.Namespace:
    """Return a copy shaped for the existing application handlers.

    `operation_id` is independent of the spelling used by the caller. The
    legacy-shaped `command` and child fields let existing handlers remain the
    single implementation for both canonical and compatibility paths.
    """
    normalized = argparse.Namespace(**vars(args))
    operation_id = normalized.operation_id
    parts = operation_id.split(".")

    if parts[0] == "control":
        normalized.command = parts[1]
        if parts[1] == "gaming":
            normalized.gaming_command = {
                "on": "start",
                "off": "stop",
            }.get(parts[2], parts[2])
        elif parts[1] == "miner":
            normalized.miner_command = parts[2]
    elif parts[0] == "service":
        normalized.command = "serve" if parts[1] == "run" else parts[1]
    elif parts[0] == "system":
        normalized.command = parts[1]
        if parts[1] == "startup":
            normalized.startup_command = parts[2]
        elif parts[1] == "auth":
            normalized.auth_command = parts[2]
    elif parts[0] == "check":
        normalized.command = {
            "health": "doctor",
            "telemetry": "diagnose",
        }.get(parts[1], parts[1])
    elif parts[0] == "config":
        normalized.command = "config"
    else:
        normalized.command = parts[0]
    return normalized
