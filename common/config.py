# common/config.py
"""
YAML configuration loader and validator for design variants.

This module validates the minimal schema required by project tools while
preserving any additional keys in the YAML for forward compatibility.

Expected top-level structure (see [configs/variants.yaml](configs/variants.yaml)):

    variants:
      - name: example
        taps: 8
        pipeline: 0        # optional (int|bool)
        round: "round"     # optional ("round"|"truncate")
        sat: "saturate"    # optional ("saturate"|"wrap")
        seed: 1            # optional (int)
        yosys_opts: ""     # optional (str)
        nextpnr_opts: ""   # optional (str)
        freq: 12           # optional (int)

"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

log = logging.getLogger(__name__)


class ConfigError(Exception):
    """Raised when configuration loading or validation fails."""


@dataclass
class Config:
    """Typed wrapper for the loaded and validated configuration."""

    variants: List[Dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> str:
        """Serialize the config to a JSON string (UTF-8)."""
        return json.dumps({"variants": self.variants}, indent=2, sort_keys=True)

    def dump_json(self, path: Union[str, Path]) -> None:
        """Write the config JSON to a file path."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_json(), encoding="utf-8")


def _validate_variant(idx: int, v: Dict[str, Any]) -> None:
    if not isinstance(v, dict):
        raise ConfigError(f"variants[{idx}] must be a mapping, got {type(v).__name__}")

    # Required keys
    if "name" not in v or not isinstance(v["name"], str) or not v["name"].strip():
        raise ConfigError(f"variants[{idx}].name must be a non-empty string")
    if "taps" not in v or not isinstance(v["taps"], int):
        raise ConfigError(f"variants[{idx}].taps must be an integer")

    # Optional known keys (validate type if present)
    if "pipeline" in v and not isinstance(v["pipeline"], (int, bool)):
        raise ConfigError(f"variants[{idx}].pipeline must be int or bool when present")
    if "round" in v and not isinstance(v["round"], str):
        raise ConfigError(f"variants[{idx}].round must be a string when present")
    if "sat" in v and not isinstance(v["sat"], str):
        raise ConfigError(f"variants[{idx}].sat must be a string when present")
    if "seed" in v and not isinstance(v["seed"], int):
        raise ConfigError(f"variants[{idx}].seed must be an integer when present")
    if "yosys_opts" in v and not isinstance(v["yosys_opts"], str):
        raise ConfigError(f"variants[{idx}].yosys_opts must be a string when present")
    if "nextpnr_opts" in v and not isinstance(v["nextpnr_opts"], str):
        raise ConfigError(f"variants[{idx}].nextpnr_opts must be a string when present")
    if "freq" in v and not isinstance(v["freq"], int):
        raise ConfigError(f"variants[{idx}].freq must be an integer when present")


def _validate(data: Dict[str, Any]) -> Config:
    if "variants" not in data:
        raise ConfigError('Missing top-level "variants" key')
    variants = data["variants"]
    if not isinstance(variants, list):
        raise ConfigError('"variants" must be a list')
    for i, v in enumerate(variants):
        _validate_variant(i, v)
    return Config(variants=variants)


def load_config(path: Union[str, Path]) -> Config:
    """Load and validate a configuration file from YAML.

    Raises:
        ConfigError for structural or type problems.
        FileNotFoundError if path does not exist.
        yaml.YAMLError for YAML syntax problems.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")
    try:
        text = p.read_text(encoding="utf-8")
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        # surface YAML syntax errors explicitly
        raise
    except Exception as e:  # pragma: no cover - unexpected I/O errors
        raise ConfigError(f"Failed to read config: {e}") from e

    cfg = _validate(data)
    log.debug("Loaded config with %d variants from %s", len(cfg.variants), p)
    return cfg