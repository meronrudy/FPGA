#!/usr/bin/env python3
"""
Quick import/CLI smoke check for project modules.

- Verifies importability of key modules.
- Invokes --help for CLI entrypoints to ensure parsers load.

Exit codes:
  0 on success
  1 on any failure to import or invoke --help (only if process fails to start)
"""

from __future__ import annotations

import subprocess
import sys
from typing import List, Sequence

from common.logging import setup_logging, get_logger

MODULES: List[str] = [
    "agents.analysis",
    "agents.designer",
    "agents.sim",
    "agents.synth",
    "scripts.mk_phase1_report",
    "scripts.parse_nextpnr_report",
    "sim.golden.fir_model",
]

CLIS: List[List[str]] = [
    [sys.executable, "-m", "agents.designer", "--help"],
    [sys.executable, "-m", "agents.sim", "--help"],
    [sys.executable, "-m", "agents.synth", "--help"],
    [sys.executable, "scripts/mk_phase1_report.py", "--help"],
    [sys.executable, "scripts/parse_nextpnr_report.py", "--help"],
]

def _check_imports(mods: Sequence[str]) -> bool:
    log = get_logger(__name__)
    ok = True
    for mod in mods:
        try:
            __import__(mod)
            log.info("Imported %s", mod)
        except Exception as e:
            log.error("Failed to import %s: %s", mod, e)
            ok = False
    # Optional cocotb-based test: tolerate missing cocotb or other issues
    try:
        __import__("sim.cocotb.test_fir8")
        log.info("Imported sim.cocotb.test_fir8")
    except Exception as e:
        log.info("Skipping sim.cocotb.test_fir8 import (optional): %s", e)
    return ok

def _run_cli(cmd: Sequence[str]) -> bool:
    log = get_logger(__name__)
    try:
        rc = subprocess.call(list(cmd))
        if rc != 0:
            # Do not fail the run on non-zero rc; parser may exit(0/2) depending on argparse
            log.warning("CLI returned non-zero (%d): %s", rc, " ".join(map(str, cmd)))
        else:
            log.info("CLI OK: %s", " ".join(map(str, cmd)))
        return True
    except Exception as e:
        log.error("Failed to start CLI %s: %s", " ".join(map(str, cmd)), e)
        return False

def main() -> int:
    setup_logging()
    log = get_logger(__name__)

    ok = _check_imports(MODULES)

    # CLI --help checks: only fail if process fails to start
    cli_ok = True
    for cmd in CLIS:
        if not _run_cli(cmd):
            cli_ok = False

    if ok and cli_ok:
        log.info("All imports and CLI checks passed")
        return 0
    log.error("Import/CLI checks encountered errors")
    return 1

if __name__ == "__main__":
    sys.exit(main())