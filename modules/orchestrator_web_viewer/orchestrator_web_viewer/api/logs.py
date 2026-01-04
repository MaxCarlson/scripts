"""API router for querying and controlling server logs."""
from __future__ import annotations

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ..log_utils import (
    LOG_LEVELS,
    get_recent_logs,
    list_logger_levels,
    update_logger_level,
)

router = APIRouter()
logger = logging.getLogger(__name__)


class LogLevelUpdate(BaseModel):
    logger_name: Optional[str] = Field(default="root", description="Logger to update")
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


@router.get("")
async def read_logs(
    limit: int = Query(200, ge=1, le=2000),
    min_level: str = Query("INFO", pattern="^(?i)(DEBUG|INFO|WARNING|ERROR|CRITICAL)$"),
    include_access: bool = Query(False),
):
    """Return recent log entries."""
    entries = get_recent_logs(limit=limit, min_level_name=min_level, include_access=include_access)
    return {"logs": entries}


@router.get("/levels")
async def get_levels():
    """Report effective levels for notable loggers."""
    return {
        "available_levels": LOG_LEVELS,
        "loggers": list_logger_levels(),
    }


@router.post("/level")
async def set_level(payload: LogLevelUpdate):
    """Update the configured level for a logger."""
    updated = update_logger_level(payload.logger_name or "root", payload.level)
    logger.info("LOG_LEVEL_UPDATE logger=%s level=%s", updated["name"], updated["level"])
    return updated
