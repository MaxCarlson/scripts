"""Lightweight headless runner for Scheduled Task execution of the host heartbeat.

This script executes independently with minimal dependencies, requiring no active user
session, no running notification broker, and no database connection.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from notifications.monitoring.config import load_healthchecks_config, redact_ping_url
from notifications.monitoring.heartbeat import send_heartbeat


def main() -> int:
    try:
        parser = argparse.ArgumentParser(
            prog="scripts-notify-heartbeat-runner",
            description="Headless runner for independent Healthchecks host heartbeat.",
        )
        parser.add_argument("-c", "--config", default=None, help="Path override for healthchecks.json")
        parser.add_argument("-t", "--timeout", type=float, default=10.0, help="Heartbeat request timeout.")
        parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging.")
        args = parser.parse_args()

        log_level = logging.DEBUG if args.verbose else logging.INFO
        logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        logger = logging.getLogger("heartbeat-runner")

        config_path = Path(args.config) if args.config else None
        config = load_healthchecks_config(config_path)

        if not config:
            logger.error("Healthchecks configuration not found. Run 'scripts-notify heartbeat configure' first.")
            return 1

        logger.info("Dispatching host heartbeat for check '%s'...", config.check_name)
        result = send_heartbeat(config.ping_url, timeout=args.timeout)

        if result.success:
            logger.info("Heartbeat confirmed (HTTP %d, %dms)", result.status_code or 200, result.duration_ms)
            return 0
        else:
            logger.error("Heartbeat failed (%s): %s", result.error_category, result.error_message)
            return 1
    except Exception as exc:
        sanitized = redact_ping_url(str(exc))
        sys.stderr.write(f"Unexpected heartbeat runner exception: {sanitized}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
