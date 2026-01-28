from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict


LOGGER_NAME = "research_api"


def setup_logging() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger


def log_event(logger: logging.Logger, payload: Dict[str, Any]) -> None:
    payload["timestamp"] = datetime.now(timezone.utc).isoformat()
    logger.info(json.dumps(payload, ensure_ascii=True))
