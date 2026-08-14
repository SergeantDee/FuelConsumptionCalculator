from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fuel_consumption_calculator.config import LOG_BACKUP_COUNT, LOG_MAX_BYTES


def configure_logging(log_file: Path) -> logging.Logger:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    for handler in list(root_logger.handlers):
        if getattr(handler, "_fuel_calculator_handler", False):
            root_logger.removeHandler(handler)
            handler.close()

    handler = RotatingFileHandler(
        log_file,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler._fuel_calculator_handler = True  # type: ignore[attr-defined]
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    root_logger.addHandler(handler)
    return logging.getLogger("fuel_consumption_calculator")
