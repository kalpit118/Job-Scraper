"""
utils/logger.py
---------------
Centralized logging configuration using loguru.
Creates daily rotating log files in the logs/ directory and outputs
coloured logs to stderr for local debugging.
"""

import sys
from pathlib import Path

from loguru import logger


def setup_logger() -> None:
    """
    Configure the global loguru logger.

    - Removes the default sink.
    - Adds a coloured stderr sink for local development.
    - Adds a daily-rotating file sink under logs/.
    """
    # Remove default loguru handler
    logger.remove()

    # Console sink – human-readable, coloured
    logger.add(
        sys.stderr,
        level="INFO",
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> — "
            "<level>{message}</level>"
        ),
        colorize=True,
        backtrace=True,
        diagnose=True,
    )

    # File sink – daily rotation, 30-day retention
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    logger.add(
        log_dir / "job_alert_{time:YYYY-MM-DD}.log",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} — {message}",
        rotation="00:00",       # Rotate at midnight
        retention="30 days",    # Keep 30 days of logs
        compression="zip",      # Compress old files
        backtrace=True,
        diagnose=True,
        enqueue=True,           # Thread-safe writing
    )


# Initialise on import so every module that does `from utils.logger import logger`
# gets the correctly configured logger.
setup_logger()

__all__ = ["logger", "setup_logger"]
