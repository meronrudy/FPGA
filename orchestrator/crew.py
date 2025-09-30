#!/usr/bin/env python3
"""
CrewAI-compatible orchestrator (with local fallback) for the FPGA variant workflow.

Design philosophy
- Promote late: only designs that repeatedly “fly” in software (lint, simulation tiers, formal micro-checks)
  are promoted to expensive hardware.
- Automate aggressively but safely: centralized gates ensure hardware is never touched unless upstream
  criteria are met (simulation pass, optional formal essentials, synth dry-run thresholds).
- Be reproducible: log seeds, versions, artifacts; keep boundaries between steps explicit (subprocesses).
- Scale out where cheap: parallelize simulation/formal; queue and backpressure for synth/hardware.

This orchestrator currently implements the Phase 1 pipeline:
    designer → sim → synth → (optional) board → analysis

Where:
- designer validates/normalizes the variants configuration (YAML → normalized JSON artifact, optional).
- sim drives cocotb tests on a per-variant basis.
- synth runs the open-source flow: Yosys → nextpnr → icestorm pack → summary parse; aggregates CSV.
- board (optional) acquires the single iCEBreaker resource, flashes SRAM (iceprog -S), performs a smoke test,
  writes smoke.json under artifacts/hw/<variant>/<timestamp>/.
- analysis regenerates artifacts/report_phase1.md, which now includes a Hardware smoke results section.

CrewAI note
- If the 'crewai' library is installed, a light Crew/Agent scaffolding is constructed to align with the
  intended multi-agent abstraction. Execution still uses robust subprocess calls for traceability.
- If CrewAI is not available, the orchestrator runs in a local, dependency-free mode.

Module I/O conventions
- Each helper (run_*) returns a process return code (0 = success). The orchestrator uses these RCs to gate
  subsequent steps. All helpers are side-effectful via per-agent artifacts/logs.

Related modules
- Agents used via module entrypoints:
  - Designer: python -m agents.designer
  - Simulation: python -m agents.sim
  - Synthesis: python -m agents.synth
  - Board: python -m agents.board
  - Analysis: python -m agents.analysis
- Shared utilities:
  - Locking: common.resources.FileLock (single-board mutual exclusion)
  - Notifications: common.notify.notify_slack
- Report generator (Phase 1): scripts/mk_phase1_report.py (run by agents/analysis.py)

Security & safety guardrails
- No hardware unless simulation for that variant returns success.
- Board agent enforces file-based lock and cooldown; hardware job in CI requires manual approval.
- Subprocess boundaries minimize blast radius if a step misbehaves.

"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from common.logging import setup_logging, get_logger, set_verbosity
from common.config import load_config, ConfigError

REPO = Path(__file__).resolve().parents[1]

# Optional CrewAI import; fallback to local orchestration if not available
try:
    # CrewAI is optional; install in dev/CI if you want Agent/Crew scaffolding visible.
    from crewai import Crew, Agent  # type: ignore
    CREW_AVAILABLE = True
except Exception:
    CREW_AVAILABLE = False


def _run(cmd: List[str]) -> int:
    """
    Execute a subprocess with repository root as CWD.

    Parameters:
        cmd: Command tokens, e.g. [sys.executable, "-m", "agents.sim", "--variant", "baseline8"].

    Returns:
        int: Return code of the process (0 indicates success).

    Notes:
        - stdout/stderr stream to the parent process for real-time logs in CI/local runs.
        - This boundary keeps each agent self-contained and testable.
    """
    log = get_logger(__name__)
    log.info("[orchestrator.run] %s", " ".join(cmd))
    try:
        completed = subprocess.run(cmd, cwd=REPO.as_posix())
        return completed.returncode
    except FileNotFoundError as e:
        log.error("Executable not found: %s (%s)", cmd[0], e)
        return 127
    except Exception as e:
        log.exception("Unexpected error running %s: %s", cmd, e)
        return 1


def run_designer() -> int:
    """
    Run the designer agent to validate/normalize the variants config.

    Side effects:
        - Writes artifacts/variants.json (optional downstream use).
        - Logs schema validation details.

    Returns:
        int: 0 on success; non-zero on failure.
    """
    return _run([sys.executable, "-m", "agents.designer"])


def run_sim(variant: str, sim: str = "verilator") -> int:
    """
    Run simulation (cocotb) for a single variant.

    Parameters:
        variant: Name of variant in configs/variants.yaml.
        sim: Simulator choice (e.g., "verilator", "icarus").

    Side effects:
        - Produces cocotb results and optional coverage artifacts in build/.
        - Propagates parameters from the selected variant.

    Returns:
        int: 0 on success; non-zero triggers gate to skip synth/hardware.
    """
    return _run([sys.executable, "-m", "agents.sim", "--variant", variant, "--sim", sim])


def run_synth(variant: str) -> int:
    """
    Synthesize and PnR a single variant; parse timing/resources and aggregate.

    Parameters:
        variant: Variant name.

    Side effects:
        - build/<variant>/ contains json/asc/bin/netlist/stat/summary.csv
        - artifacts/variants_summary.csv aggregated across successful variants

    Returns:
        int: 0 on success; non-zero signals gate to skip hardware for this variant.
    """
    # Use module entry for robustness when running “python -m”
    return _run([sys.executable, "-m", "agents.synth", "--only", variant])


def run_board(variant: str, cooldown: float = 5.0) -> int:
    """
    Flash SRAM and perform a basic smoke test for a single variant.

    Parameters:
        variant: Variant name (expects build/<variant>/fir8_top.bin).
        cooldown: Seconds to idle after flash (power rail stabilization).

    Side effects:
        - artifacts/hw/<variant>/<timestamp>/smoke.json
        - Enforces single-board lock via common.resources.FileLock.

    Returns:
        int: 0 on success; non-zero on flash or smoke failure.
    """
    return _run([sys.executable, "-m", "agents.board", "--variant", variant, "--cooldown", str(cooldown)])


def run_analysis() -> int:
    """
    Generate/refresh Phase 1 report (Markdown).

    Side effects:
        - artifacts/report_phase1.md (includes Hardware smoke results if present)
        - Logs summary of write path

    Returns:
        int: 0 on success; non-zero if report generation script fails.
    """
    return _run([sys.executable, "-m", "agents.analysis"])


def _all_variant_names_from_config(config_path: Path) -> List[str]:
    """
    Load the variants config and return the list of variant names.

    Parameters:
        config_path: Path to YAML file (configs/variants.yaml)

    Returns:
        List[str]: Variant names in order of appearance.

    Raises:
        ConfigError: If the config structure is invalid.
        FileNotFoundError: If the file is missing.
    """
    cfg = load_config(config_path)
    return [v["name"] for v in cfg.variants if isinstance(v, dict) and "name" in v]


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """
    Parse CLI arguments for the orchestrator.

    Returns:
        argparse.Namespace with fields:
            variants: Optional[List[str]] explicit variant names
            with_hardware: bool include hardware flash/smoke step
            sim: str simulator name for cocotb (default "verilator")
            cooldown: float cooldown seconds after flash
            verbose / log_level: logging controls
    """
    p = argparse.ArgumentParser(
        prog="orchestrator.crew",
        description=(
            "CrewAI-orchestrated flow (local fallback): "
            "designer → sim → synth → [board] → analysis"
        ),
    )
    p.add_argument(
        "--variants",
        nargs="+",
        default=None,
        help="Variant names to process; default: all variants in configs/variants.yaml",
    )
    p.add_argument("--with-hardware", action="store_true", help="Include hardware flash/smoke step")
    p.add_argument("--sim", default="verilator", help="Simulator for cocotb (default: verilator)")
    p.add_argument("--cooldown", type=float, default=5.0, help="Cooldown seconds after flashing (default: 5.0)")

    # Logging / verbosity
    p.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity (-v=INFO, -vv=DEBUG)")
    p.add_argument("--log-level", choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"], default=None)

    return p.parse_args(argv)


def run_phase1(args: argparse.Namespace, variants: List[str]) -> int:
    """
    Step-by-step workflow for Phase 1 with explicit commentary on each gate.

    Phases:
      0) Designer (optional preflight)
      1) Simulation (gate)
      2) Synthesis/PnR (gate)
      3) Hardware flash/smoke (optional)
      4) Analysis/report

    Gates:
      - Hardware never runs unless simulation passed and synthesis succeeded for that variant.

    Parameters:
      args: Parsed CLI namespace (with_hardware, sim, cooldown, etc.)
      variants: Ordered list of variant names to process.

    Returns:
      int: Return code from analysis phase (0 on success).
    """
    log = get_logger(__name__)

    # (0) Optional preflight: configuration/normalization.
    #     This helps surface schema errors early but is not required for downstream steps,
    #     since each agent validates its inputs independently.
    log.info("[phase1] Preflight: designer validation/normalization")
    _ = run_designer()

    # (1-3) Per-variant pipeline
    for name in variants:
        # 1) Simulation gate
        log.info("[phase1] Variant %s: simulation start (sim=%s)", name, args.sim)
        rc = run_sim(name, sim=args.sim)
        if rc != 0:
            log.error("[phase1] Variant %s: simulation failed (rc=%d); skipping synth/hardware", name, rc)
            continue  # Fail-fast for this variant; do not attempt expensive steps

        # 2) Synthesis/PnR gate
        log.info("[phase1] Variant %s: synthesis/PnR", name)
        rc = run_synth(name)
        if rc != 0:
            log.error("[phase1] Variant %s: synthesis failed (rc=%d); skipping hardware", name, rc)
            continue

        # 3) Hardware (optional)
        if args.with_hardware:
            # Board access is mutually exclusive and requires a manual approval gate in CI.
            # The board agent internally obtains the lock and enforces cooldown between flashes.
            log.info("[phase1] Variant %s: hardware flash/smoke (cooldown=%.2fs)", name, args.cooldown)
            rc = run_board(name, cooldown=args.cooldown)
            if rc != 0:
                log.error("[phase1] Variant %s: hardware smoke failed (rc=%d)", name, rc)

    # (4) Analysis/report: generate consolidated Markdown and link artifacts (incl. smoke results if any).
    log.info("[phase1] Analysis/report")
    return run_analysis()


def local_orchestrate(args: argparse.Namespace) -> int:
    """
    Local fallback orchestrator (no CrewAI dependency).

    Behavior:
      - Resolves the target variants list (CLI-specified or via configs/variants.yaml).
      - Executes run_phase1 with the resolved variant list.

    Returns:
      int: Return code from run_phase1 (0 on success).
    """
    log = get_logger(__name__)

    # Determine target variants
    try:
        variants = args.variants or _all_variant_names_from_config(REPO / "configs" / "variants.yaml")
    except (ConfigError, FileNotFoundError) as e:
        log.error("Failed to load variants: %s", e)
        return 2

    if not variants:
        log.error("No variants to process")
        return 2

    return run_phase1(args, variants)


def main(argv: Optional[List[str]] = None) -> int:
    """
    Orchestrator entrypoint.

    - Parses CLI.
    - Optionally sets up CrewAI Agents/Crew for visibility (no-op execution-wise in v1).
    - Executes the local robust orchestrator (run_phase1) to perform the work.

    Returns:
      int: Overall return code (0 on success).
    """
    args = parse_args(argv)
    setup_logging(level=args.log_level)
    if args.log_level is None:
        set_verbosity(args.verbose)
    log = get_logger(__name__)

    if CREW_AVAILABLE:
        # Initialize lightweight Agent scaffolding (advisory; execution remains in subprocess helpers).
        log.info("[crew] CrewAI detected; initializing agents")

        designer_agent = Agent(
            name="designer",
            role="Load and validate variant definitions",
            goal="Produce normalized variant list",
            backstory="Reads YAML and ensures schema is correct for downstream tools.",
            verbose=False,
        )
        sim_agent = Agent(
            name="sim",
            role="Run simulation",
            goal="Execute cocotb testbench with resolved parameters",
            backstory="Drives Make-based cocotb flow and reports pass/fail.",
            verbose=False,
        )
        synth_agent = Agent(
            name="synth",
            role="Synthesize and place/route",
            goal="Emit bitstreams and timing/utilization reports",
            backstory="Runs Yosys/nextpnr/icestorm and parsers.",
            verbose=False,
        )
        board_agent = Agent(
            name="board",
            role="Hardware flash/smoke",
            goal="Program iCEBreaker SRAM and verify basic health",
            backstory="Enforces exclusive access, cooldown, and fail-safe cleanup.",
            verbose=False,
        )
        analysis_agent = Agent(
            name="analysis",
            role="Aggregate and report",
            goal="Produce consolidated report artifacts",
            backstory="Summarizes results and artifacts for CI.",
            verbose=False,
        )

        # Construct Crew (no tasks yet; orchestration handled by run_phase1).
        _ = Crew(
            agents=[designer_agent, sim_agent, synth_agent, board_agent, analysis_agent],
            tasks=[],
            verbose=False,
        )

    # Always execute the robust local pipeline (Crew presence is advisory in v1)
    return local_orchestrate(args)


if __name__ == "__main__":
    sys.exit(main())