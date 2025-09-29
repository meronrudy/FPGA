# common/logging.py
"""
Centralized logging utilities.

Usage:
    from common.logging import setup_logging, get_logger

    logger = setup_logging(level="INFO")
    log = get_logger(__name__)
    log.info("Hello")

Env:
    LOG_LEVEL: Optional. If not provided via parameter, this decides the log level.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional, Union


_LEVEL_NAMES = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "NOTSET": logging.NOTSET,
}


def _coerce_level(level: Optional[Union[str, int]]) -> int:
    """Coerce a string/int log level to logging module level.

    Accepted:
    - int levels (e.g., logging.INFO)
    - str names (e.g., "INFO", "debug")
    - None → derive from LOG_LEVEL or default INFO
    """
    if isinstance(level, int):
        return level
    env_level = os.getenv("LOG_LEVEL")
    name = (level or env_level or "INFO").upper()
    return _LEVEL_NAMES.get(name, logging.INFO)


def setup_logging(
    level: Optional[Union[str, int]] = None,
    *,
    fmt: str = "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt: str = "%Y-%m-%d %H:%M:%S",
    propagate: bool = False,
) -> logging.Logger:
    """Initialize root logging configuration and return the root logger.

    Parameters:
        level: Explicit level or name; if None, uses LOG_LEVEL env or INFO.
        fmt: Log message format.
        datefmt: Timestamp format.
        propagate: If True, allow messages to bubble up to parent handlers.

    Returns:
        The configured root logger.
    """
    lvl = _coerce_level(level)
    root = logging.getLogger()
    root.setLevel(lvl)

    # Clear existing handlers to avoid duplicate logs in re-inits
    if root.handlers:
        for h in list(root.handlers):
            root.removeHandler(h)

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setLevel(lvl)
    handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
    root.addHandler(handler)

    root.propagate = propagate
    return root


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a logger for the given module or name."""
    return logging.getLogger(name if name else __name__)


def set_verbosity(v: int) -> None:
    """Convenience mapping for -v counts.

    v = 0 → WARNING
    v = 1 → INFO
    v ≥ 2 → DEBUG
    """
    level = logging.WARNING if v <= 0 else (logging.INFO if v == 1 else logging.DEBUG)
    logging.getLogger().setLevel(level)