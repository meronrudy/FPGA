#!/usr/bin/env python3
"""
Analysis agent to generate Phase 1 report artifacts.

This module invokes scripts/mk_phase1_report.py from the repository root
and emits a generated report at artifacts/report_phase1.md.

Logging is centralized via common.logging. LOG_LEVEL environment variable
controls verbosity (default INFO). No work is executed at import time.
"""

import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from common.logging import setup_logging, get_logger

REPO = Path(__file__).resolve().parents[1]


def main(argv: Optional[List[str]] = None) -> int:
    """
    Program entrypoint for the analysis agent.

    Behavior:
    - Runs scripts/mk_phase1_report.py from the repository root.
    - On success, logs a confirmation message.
    - On failure due to subprocess.CalledProcessError, logs the error and
      returns the underlying non-zero return code.

    Parameters:
        argv: Unused; present for API completeness and testing.

    Returns:
        0 on success; non-zero error code if the report generation subprocess fails.
    """
    setup_logging()
    log = get_logger(__name__)

    try:
        subprocess.run(
            ["python3", "scripts/mk_phase1_report.py"],
            cwd=REPO.as_posix(),
            check=True,
        )
        log.info("[analysis] Generated artifacts/report_phase1.md")
        return 0
    except subprocess.CalledProcessError as e:
        log.error(f"[analysis] ERROR running mk_phase1_report.py: {e}")
        return e.returncode


if __name__ == "__main__":
    sys.exit(main())
