"""
Independent logging configuration for sp_digitaltwin.

Usage:
    from logger_config import get_logger
    logger = get_logger("solver")
    logger.info("Solver started")
    logger.error("Something went wrong", exc_info=True)

Log files are written to <project_root>/logs/ with automatic rotation.
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Optional


_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-20s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB per log file
_BACKUP_COUNT = 5

_initialized = False
_log_dir: Optional[Path] = None


def _find_project_root() -> Path:
    """Walk up from this file to find the project root (contains backend/)."""
    current = Path(__file__).resolve().parent
    for candidate in [current, *current.parents]:
        if (candidate / "backend").is_dir():
            return candidate
        if (candidate / "start_app.py").is_file():
            return candidate
    return current


def _get_log_dir() -> Path:
    global _log_dir
    if _log_dir is None:
        root = _find_project_root()
        _log_dir = root / "logs"
        _log_dir.mkdir(exist_ok=True)
    return _log_dir


def _ensure_initialized():
    global _initialized
    if _initialized:
        return
    _initialized = True

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
    root_logger.addHandler(console)

    log_dir = _get_log_dir()

    app_handler = logging.handlers.RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    app_handler.setLevel(logging.DEBUG)
    app_handler.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
    app_handler.addFilter(lambda record: not record.name.startswith("solver"))
    root_logger.addHandler(app_handler)

    solver_handler = logging.handlers.RotatingFileHandler(
        log_dir / "solver.log",
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    solver_handler.setLevel(logging.DEBUG)
    solver_handler.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
    solver_handler.addFilter(lambda record: record.name.startswith("solver"))
    root_logger.addHandler(solver_handler)


def get_logger(name: str) -> logging.Logger:
    """
    Get a named logger. Call once per component.

    Known names:
        "app"        - application lifecycle (start/stop/errors)
        "solver"     - optimization solver runs (heuristic, LP, compare)
        "run"        - start_app.py launcher
        "api"        - FastAPI endpoints
        "graph"      - graph service / serializer
        "scheduler"  - simulation runner
    """
    _ensure_initialized()
    return logging.getLogger(name)
