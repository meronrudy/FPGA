#!/usr/bin/env python3
"""
Simulation agent: drive the cocotb testbench via Make with configurable parameters.

This tool launches the cocotb test in [sim/cocotb/Makefile](sim/cocotb/Makefile), passing the
test module (MODULE), HDL top (TOPLEVEL), and optional design parameters (TAPS, PIPELINE, ROUND, SAT)
via environment variables. Parameters can be sourced from a named variant in
[configs/variants.yaml](configs/variants.yaml) and overridden explicitly via CLI flags.

Exit codes:
    0  success
    2  file not found (Makefile) or YAML parse error
    3  validation/config error (e.g., missing variant, bad types)
    4  subprocess failure (Make returned non-zero)
    1  unexpected error
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml  # for catching yaml.YAMLError transparently

from common.config import ConfigError, load_config
from common.logging import get_logger, set_verbosity, setup_logging


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agents.sim",
        description="Run cocotb testbench via Make with optional design parameters",
    )
    parser.add_argument(
        "-m", "--makefile",
        type=Path,
        default=Path("sim/cocotb/Makefile"),
        help="Path to cocotb Makefile (default: sim/cocotb/Makefile)",
    )
    parser.add_argument(
        "--module",
        default="test_fir8",
        help="Cocotb test module name (MODULE) (default: test_fir8)",
    )
    parser.add_argument(
        "--top",
        default="fir8_top",
        help="HDL top module name (TOPLEVEL) (default: fir8_top)",
    )
    parser.add_argument(
        "--sim",
        default=None,
        help="Optional simulator selection (SIM), e.g., icarus or verilator",
    )
    parser.add_argument(
        "--variant",
        default=None,
        help="Variant name to load parameters from configs/variants.yaml",
    )
    # Explicit overrides
    parser.add_argument("--taps", type=int, help="Number of taps (overrides variant)")
    parser.add_argument("--pipeline", type=int, help="Pipeline stages (overrides variant)")
    parser.add_argument(
        "--round",
        choices=["round", "truncate"],
        help="Rounding mode (overrides variant)",
    )
    parser.add_argument(
        "--sat",
        choices=["saturate", "wrap"],
        help="Saturation mode (overrides variant)",
    )
    # Logging / verbosity
    parser.add_argument(
        "-v", "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v=INFO, -vv=DEBUG)",
    )
    parser.add_argument(
        "--log-level",
        choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"],
        default=None,
        help="Explicit log level (overrides -v and LOG_LEVEL)",
    )
    return parser.parse_args(argv)


def _load_variant_params(name: str) -> Dict[str, object]:
    cfg = load_config("configs/variants.yaml")
    for v in cfg.variants:
        if v.get("name") == name:
            return {
                k: v.get(k)
                for k in ("taps", "pipeline", "round", "sat")
                if k in v
            }
    raise ConfigError(f"Variant not found: {name}")


def _merge_params(variant: Optional[Dict[str, object]], args: argparse.Namespace) -> Dict[str, object]:
    params: Dict[str, object] = {}
    if variant:
        params.update(variant)
    # Explicit overrides win
    if args.taps is not None:
        params["taps"] = args.taps
    if args.pipeline is not None:
        params["pipeline"] = args.pipeline
    if args.round is not None:
        params["round"] = args.round
    if args.sat is not None:
        params["sat"] = args.sat
    return params


def _validate_params(p: Dict[str, object]) -> None:
    if "taps" in p and (not isinstance(p["taps"], int) or p["taps"] <= 0):
        raise ConfigError("--taps must be a positive integer")
    if "pipeline" in p and (not isinstance(p["pipeline"], int) or p["pipeline"] < 0):
        raise ConfigError("--pipeline must be a non-negative integer")
    if "round" in p and p["round"] not in {"round", "truncate"}:
        raise ConfigError("--round must be 'round' or 'truncate'")
    if "sat" in p and p["sat"] not in {"saturate", "wrap"}:
        raise ConfigError("--sat must be 'saturate' or 'wrap'")


def _build_env(args: argparse.Namespace, params: Dict[str, object]) -> Dict[str, str]:
    env = dict(os.environ)
    env["MODULE"] = str(args.module)
    env["TOPLEVEL"] = str(args.top)
    if args.sim:
        env["SIM"] = str(args.sim)
    # Optional parameters
    if "taps" in params:
        env["TAPS"] = str(params["taps"])
    if "pipeline" in params:
        env["PIPELINE"] = str(params["pipeline"])
    if "round" in params:
        env["ROUND"] = str(params["round"])
    if "sat" in params:
        env["SAT"] = str(params["sat"])
    return env


def _run_make(makefile: Path, env: Dict[str, str]) -> int:
    cmd = ["make", "-f", str(makefile)]
    # inherit stdout/stderr for real-time logs
    proc = subprocess.run(cmd, env=env)
    return proc.returncode


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    setup_logging(level=args.log_level)
    if args.log_level is None:
        set_verbosity(args.verbose)
    log = get_logger(__name__)

    try:
        makefile: Path = args.makefile
        if not makefile.exists():
            log.error("Makefile not found: %s", makefile)
            return 2

        variant_params: Optional[Dict[str, object]] = None
        if args.variant:
            variant_params = _load_variant_params(args.variant)

        params = _merge_params(variant_params, args)
        _validate_params(params)

        env = _build_env(args, params)

        # Log resolved settings (compact)
        kv = {k: env[k] for k in ["MODULE", "TOPLEVEL"] if k in env}
        for k in ("SIM", "TAPS", "PIPELINE", "ROUND", "SAT"):
            if k in env:
                kv[k] = env[k]
        log.info("Launching cocotb: make -f %s with %s", makefile, kv)

        rc = _run_make(makefile, env)
        if rc != 0:
            log.error("Simulation failed (exit %d)", rc)
            return 4
        log.info("Simulation completed successfully")
        return 0

    except FileNotFoundError as e:
        log.error("%s", e)
        return 2
    except yaml.YAMLError as e:
        log.error("YAML parse error: %s", e)
        return 2
    except ConfigError as e:
        log.error("Configuration error: %s", e)
        return 3
    except Exception as e:  # pragma: no cover
        log.exception("Unexpected error: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
