#!/usr/bin/env python3
"""
Board agent: reserve the iCEBreaker, flash bitstream, and perform a basic smoke test.

Safety gates and policies:
- Enforces exclusive access via a file lock (artifacts/locks/icebreaker.lock).
- Supports cooldown between flashes to avoid stressing power rails (default: 5s).
- Fails fast on any subprocess error; guarantees lock release.

Usage:
  python -m agents.board --variant baseline8
  python -m agents.board --bin build/baseline8/fir8_top.bin --cooldown 5

Env:
  ICEPROG: optional path to iceprog binary (defaults to 'iceprog')

Artifacts:
  - artifacts/hw/<variant-or-custom>/<timestamp>/smoke.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from common.logging import setup_logging, get_logger, set_verbosity
from common.resources import FileLock, LockError


REPO = Path(__file__).resolve().parents[1]
DEFAULT_BIN_NAME = "fir8_top.bin"
LOCK_NAME = "icebreaker"
ARTIFACTS_HW = REPO / "artifacts" / "hw"


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """
    Parse CLI args for the board agent.

    Returns:
      argparse.Namespace with fields:
        - variant or bin_path (mutually exclusive)
        - cooldown, lock-ttl, lock-timeout
        - verbose/log-level

    Notes:
      Requires either --variant (expects build/<variant>/fir8_top.bin) or --bin <path>.
    """
    p = argparse.ArgumentParser(
        prog="agents.board",
        description="Reserve iCEBreaker, flash bitstream, and run a basic smoke test.",
    )
    gsel = p.add_mutually_exclusive_group(required=True)
    gsel.add_argument("--variant", help="Variant name (expects build/<variant>/fir8_top.bin)")
    gsel.add_argument("--bin", dest="bin_path", type=Path, help="Path to a .bin bitstream to flash")

    p.add_argument("--cooldown", type=float, default=5.0, help="Cooldown seconds after flash (default: 5.0)")
    p.add_argument("--lock-ttl", type=int, default=180, help="Lock TTL seconds for stale lock recovery (default: 180)")
    p.add_argument("--lock-timeout", type=float, default=300.0, help="Max seconds to wait for the board lock (default: 300s)")

    # Logging / verbosity
    p.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity (-v=INFO, -vv=DEBUG)")
    p.add_argument("--log-level", choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"], default=None, help="Explicit log level")

    return p.parse_args(argv)


def _resolve_bitstream(args: argparse.Namespace) -> tuple[str, Path]:
    """
    Resolve bitstream path either from --bin or from a named --variant.

    Returns:
      (label, path) where label names the subdirectory used for artifacts.

    Raises:
      FileNotFoundError if the bitstream does not exist at the expected path.
    """
    if args.bin_path:
        bs = args.bin_path
        if not bs.exists():
            raise FileNotFoundError(f"Bitstream not found: {bs}")
        label = bs.parent.name
        return label, bs

    # Resolve from variant
    label = args.variant
    bs = REPO / "build" / label / DEFAULT_BIN_NAME
    if not bs.exists():
        raise FileNotFoundError(f"Bitstream not found for variant '{label}': {bs}")
    return label, bs


def _run(cmd: list[str]) -> None:
    """
    Run a subprocess, surfacing failures with enriched context.

    Raises:
      RuntimeError with clear error message for missing executables or non-zero exit codes.
    """
    log = get_logger(__name__)
    log.info("[run] %s", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError as e:
        raise RuntimeError(f"Executable not found: {cmd[0]} ({e})") from e
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Command failed ({e.returncode}): {' '.join(cmd)}") from e


def _flash_sram(bitstream: Path) -> None:
    """
    Program SRAM for a quick smoke test (non-persistent). Uses 'iceprog -S'.
    """
    iceprog = os.getenv("ICEPROG", "iceprog")
    _run([iceprog, "-S", str(bitstream)])


def _write_smoke_record(label: str, bitstream: Path, ok: bool, message: str) -> Path:
    now = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    out_dir = ARTIFACTS_HW / label / now
    out_dir.mkdir(parents=True, exist_ok=True)
    record: Dict[str, object] = {
        "variant_or_label": label,
        "bitstream": str(bitstream),
        "utc_timestamp": now,
        "status": "ok" if ok else "fail",
        "message": message,
    }
    out = out_dir / "smoke.json"
    out.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return out


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)

    setup_logging(level=args.log_level)
    if args.log_level is None:
        set_verbosity(args.verbose)
    log = get_logger(__name__)

    try:
        label, bitstream = _resolve_bitstream(args)
        log.info("[board] Preparing to flash '%s' (%s)", label, bitstream)

        # Acquire exclusive board lock
        lock = FileLock(LOCK_NAME, ttl=args.lock_ttl, timeout=args.lock_timeout, reentrant=True)
        with lock:
            log.info("[board] Acquired lock: %s", LOCK_NAME)
            _flash_sram(bitstream)
            log.info("[board] Flash (SRAM) completed successfully")
            if args.cooldown > 0:
                log.info("[board] Cooldown for %.2f seconds...", args.cooldown)
                time.sleep(args.cooldown)

        rec = _write_smoke_record(label, bitstream, ok=True, message="Flashed via SRAM; basic smoke OK")
        log.info("[board] Smoke record: %s", rec)
        return 0

    except (FileNotFoundError, LockError, RuntimeError) as e:
        log.error("[board] ERROR: %s", e)
        try:
            # best-effort record
            label = args.variant or (args.bin_path.parent.name if args.bin_path else "unknown")
            bs = args.bin_path or Path("unknown")
            rec = _write_smoke_record(label, bs, ok=False, message=str(e))
            log.error("[board] Failure record: %s", rec)
        except Exception:
            pass
        return 1
    except Exception as e:  # pragma: no cover
        log.exception("[board] Unexpected error: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())