"""
Designer agent: load design variants from YAML and emit a validated JSON form.

This tool reads the project configuration from [configs/variants.yaml](configs/variants.yaml),
validates its minimal schema using [common/config.py](common/config.py), and writes a normalized
JSON file for downstream tools in artifacts.

Example:
    python -m agents.designer --input configs/variants.yaml --output artifacts/variants.json -v

Exit codes:
    0  success
    2  file not found or YAML parse error
    3  schema validation error
    4  output write/permission error
    1  unexpected error
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Optional
import sys

import yaml  # for catching yaml.YAMLError from common.config.load_config

from common.logging import setup_logging, get_logger, set_verbosity
from common.config import load_config, ConfigError


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments for the designer agent."""
    parser = argparse.ArgumentParser(
        prog="agents.designer",
        description="Load variants from YAML and emit validated JSON for downstream tools",
    )
    parser.add_argument(
        "-i", "--input",
        type=Path,
        default=Path("configs/variants.yaml"),
        help="Path to input YAML configuration (default: configs/variants.yaml)",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=Path("artifacts/variants.json"),
        help="Path to output JSON file (default: artifacts/variants.json)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v for INFO, -vv for DEBUG)",
    )
    parser.add_argument(
        "--log-level",
        choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"],
        default=None,
        help="Explicit log level (overrides -v and LOG_LEVEL)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """Program entrypoint. Returns an exit code per the module docstring."""
    args = parse_args(argv)

    # Initialize logging and verbosity
    setup_logging(level=args.log_level)
    if args.log_level is None:
        set_verbosity(args.verbose)
    log = get_logger(__name__)

    try:
        log.info("Loading configuration: %s", args.input)
        cfg = load_config(args.input)

        # Ensure output directory exists and write JSON
        out_path: Path = args.output
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cfg.dump_json(out_path)
        log.info("Wrote %d variants to %s", len(cfg.variants), out_path)
        return 0

    except FileNotFoundError as e:
        log.error("%s", e)
        return 2
    except yaml.YAMLError as e:
        log.error("YAML parse error: %s", e)
        return 2
    except ConfigError as e:
        log.error("Configuration validation error: %s", e)
        return 3
    except PermissionError as e:
        log.error("Write permission error: %s", e)
        return 4
    except Exception as e:  # pragma: no cover - unexpected
        log.exception("Unexpected error: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
