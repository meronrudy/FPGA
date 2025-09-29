# common/__init__.py
"""Common utilities package for logging and configuration."""

from . import logging as logging  # re-export submodule
from . import config as config    # re-export submodule

__all__ = ["logging", "config"]
__version__ = "0.1.0"