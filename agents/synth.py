#!/usr/bin/env python3
"""
Parameterized per-variant synthesis/PnR driver for iCE40 (iCEBreaker UP5K).

Features:
- Loads configs/variants.yaml and filters via --only variant1,variant2
- Validates parameter ranges (TAPS in {4,8,16,32}; ROUND/SAT/PIPELINE in {0,1})
- Generates a per-variant Yosys script and runs:
    read_verilog -sv src/rtl/fir8.v src/rtl/fir8_top.v
    chparam -set ROUND ... -set SAT ... fir8
    chparam -set TAPS  ... -set PIPELINE ... fir8_top
    hierarchy -check -top fir8_top
    synth_ice40 -top fir8_top -json build/<variant>/fir8_top.json -abc9 -relut [plus variant.yosys_opts if present]
    write_verilog -noexpr -attr2comment build/<variant>/fir8_top_netlist.v
    stat -json build/<variant>/yosys_stat.json
- Runs nextpnr_ice40.sh with env for JSON/ASC/PCF/TOP/FREQ and optional NEXTPNR_OPTS/SEED
- Packs with icestorm_pack.sh to BIN
- Parses timing/resources with scripts/parse_nextpnr_report.py producing build/<variant>/summary.csv
- Aggregates all summaries into artifacts/variants_summary.csv

Exit behavior:
- On any failing subprocess, logs the variant name and exits non-zero.
- Performs basic YAML schema checks and parameter validation with clear errors.

Usage:
  python3 agents/synth.py               # build all variants
  python3 agents/synth.py --only baseline8,pipelined8

Logging:
- Centralized logging via common.logging; LOG_LEVEL env controls verbosity (default INFO).
"""

import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional

import yaml

from common.logging import setup_logging, get_logger

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "configs" / "variants.yaml"
ARTIFACTS_DIR = REPO_ROOT / "artifacts"
SRC_RTL = [REPO_ROOT / "src" / "rtl" / "fir8.v", REPO_ROOT / "src" / "rtl" / "fir8_top.v"]
PCF = REPO_ROOT / "constraints" / "icebreaker.pcf"
NEXTPNR_SCRIPT = REPO_ROOT / "synth" / "ice40" / "nextpnr_ice40.sh"
ICEPACK_SCRIPT = REPO_ROOT / "synth" / "ice40" / "icestorm_pack.sh"
PARSE_SCRIPT = REPO_ROOT / "scripts" / "parse_nextpnr_report.py"

ALLOWED_TAPS = {4, 8, 16, 32}

# Module logger (configured in main via setup_logging)
log = get_logger(__name__)


def load_variants(path: Path) -> List[Dict[str, Any]]:
    """
    Load and validate the variants configuration from a YAML file.

    The file is expected to be a mapping with a 'variants' list, where each element
    has keys: 'name' and 'params' containing ROUND, SAT, PIPELINE, TAPS, with valid ranges.

    Parameters:
        path: Path to configs/variants.yaml.

    Returns:
        A list of validated variant dictionaries.

    Exit Codes:
        Exits with code 2 on schema errors, missing file, or invalid parameter values.
    """
    if not path.exists():
        log.error(f"[error] Variants file not found: {path}")
        sys.exit(2)
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict) or "variants" not in data or not isinstance(data["variants"], list):
        log.error("[error] variants.yaml schema invalid: expected {'variants': [ ... ]}")
        sys.exit(2)
    variants = data["variants"]
    for idx, v in enumerate(variants):
        if "name" not in v or "params" not in v:
            log.error(f"[error] variants[{idx}] missing 'name' or 'params'")
            sys.exit(2)
        p = v["params"]
        for key in ("ROUND", "SAT", "PIPELINE", "TAPS"):
            if key not in p:
                log.error(f"[error] variants[{idx}] '{v['name']}' missing param '{key}'")
                sys.exit(2)
        # Type normalization
        try:
            p["ROUND"] = int(p["ROUND"])
            p["SAT"] = int(p["SAT"])
            p["PIPELINE"] = int(p["PIPELINE"])
            p["TAPS"] = int(p["TAPS"])
        except Exception as ex:
            log.error(f"[error] variants[{idx}] '{v['name']}' param type error: {ex}")
            sys.exit(2)
        # Validate ranges
        if p["TAPS"] not in ALLOWED_TAPS:
            log.error(f"[error] variants[{idx}] '{v['name']}': TAPS must be one of {sorted(ALLOWED_TAPS)} (got {p['TAPS']})")
            sys.exit(2)
        for bkey in ("ROUND", "SAT", "PIPELINE"):
            if p[bkey] not in (0, 1):
                log.error(f"[error] variants[{idx}] '{v['name']}': {bkey} must be 0 or 1 (got {p[bkey]})")
                sys.exit(2)
        # Optional strategy hooks
        for opt in ("yosys_opts", "nextpnr_opts", "seed"):
            if opt in v and v[opt] is None:
                del v[opt]
    return variants


def filter_variants(variants: List[Dict[str, Any]], only: Optional[str]) -> List[Dict[str, Any]]:
    """
    Filter the list of variants by a comma-separated list of names.

    Parameters:
        variants: All available variants.
        only: Comma-separated variant names to include; if None or empty, returns all.

    Returns:
        A filtered list of variant dicts.

    Exit Codes:
        Exits with code 2 if any requested variant name is unknown.
    """
    if not only:
        return variants
    names = [x.strip() for x in only.split(",") if x.strip()]
    sel = [v for v in variants if v["name"] in names]
    missing = [n for n in names if n not in {v["name"] for v in variants}]
    if missing:
        log.error(f"[error] --only contained unknown variants: {', '.join(missing)}")
        sys.exit(2)
    return sel


def write_yosys_script(build_dir: Path, variant: Dict[str, Any]) -> Path:
    """
    Generate a Yosys script for the given variant and write it into build_dir.

    Parameters:
        build_dir: The variant's build directory.
        variant: The variant dictionary containing 'name', 'params', and optional 'yosys_opts'.

    Returns:
        Path to the generated run.ys script.
    """
    params = variant["params"]
    name = variant["name"]
    json_out = build_dir / "fir8_top.json"
    netlist_out = build_dir / "fir8_top_netlist.v"
    stat_out = build_dir / "yosys_stat.json"

    yosys_opts = variant.get("yosys_opts", "")
    # Compose synth_ice40 line with defaults and optional extras
    synth_line = f"synth_ice40 -top fir8_top -json {json_out} -abc9 -relut"
    if yosys_opts:
        synth_line += f" {yosys_opts}"

    # IMPORTANT: chparam both the core (ROUND/SAT) and the top-level (TAPS/PIPELINE)
    # because fir8_top forwards TAPS/PIPELINE as instance overrides.
    ys = f"""# Auto-generated Yosys script for variant {name}
read_verilog -sv {SRC_RTL[0]} {SRC_RTL[1]}
chparam -set ROUND {params['ROUND']} -set SAT {params['SAT']} fir8
chparam -set TAPS {params['TAPS']} -set PIPELINE {params['PIPELINE']} fir8_top
hierarchy -check -top fir8_top
{synth_line}
write_verilog -noexpr -attr2comment {netlist_out}
stat -json {stat_out}
"""
    ys_path = build_dir / "run.ys"
    ys_path.write_text(ys, encoding="utf-8")
    return ys_path


def run(cmd: List[str], cwd: Optional[Path] = None, env: Optional[Dict[str, str]] = None) -> None:
    """
    Run a subprocess command with optional working directory and environment.

    Parameters:
        cmd: The command and arguments to execute.
        cwd: Optional working directory.
        env: Optional environment variables to pass to the subprocess.

    Raises:
        RuntimeError: If the subprocess exits with a non-zero status.
    """
    log.info(f"[run] {' '.join(cmd)}")
    try:
        subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, check=True)
    except subprocess.CalledProcessError as ex:
        raise RuntimeError(f"command failed with code {ex.returncode}: {' '.join(cmd)}") from ex


def build_variant(variant: Dict[str, Any]) -> Path:
    """
    Build the specified variant through Yosys, nextpnr, and icestorm pack; then parse results.

    Parameters:
        variant: The variant dictionary with 'name', 'params', and optional flow options.

    Returns:
        The Path to the variant's build directory.

    Raises:
        Exception: Re-raises underlying failures after logging an error.
    """
    name = variant["name"]
    params = variant["params"]
    log.info(f"[variant] Building '{name}' with params {params}")

    build_dir = REPO_ROOT / "build" / name
    build_dir.mkdir(parents=True, exist_ok=True)

    # Persist metadata for downstream parsers
    meta = {
        "variant": name,
        "params": params,
    }
    (build_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # 1) Yosys
    ys_path = write_yosys_script(build_dir, variant)
    try:
        run(["yosys", "-q", "-c", str(ys_path)])
    except Exception as ex:
        log.error(f"[error] Yosys failed for variant '{name}': {ex}")
        raise

    # 2) nextpnr/icetime
    env = os.environ.copy()
    env.update({
        "TOP": "fir8_top",
        "JSON": str(build_dir / "fir8_top.json"),
        "ASC": str(build_dir / "fir8_top.asc"),
        "PCF": str(PCF),
        "FREQ": "12",
        # Pass through optional options
        "NEXTPNR_OPTS": str(variant.get("nextpnr_opts", "")).strip(),
    })
    if "seed" in variant and variant["seed"] is not None:
        env["SEED"] = str(variant["seed"])
    try:
        run(["bash", str(NEXTPNR_SCRIPT)], env=env)
    except Exception as ex:
        log.error(f"[error] nextpnr failed for variant '{name}': {ex}")
        raise

    # 3) Pack to BIN
    env_pack = os.environ.copy()
    env_pack.update({
        "ASC": str(build_dir / "fir8_top.asc"),
        "BIN": str(build_dir / "fir8_top.bin"),
    })
    try:
        run(["bash", str(ICEPACK_SCRIPT)], env=env_pack)
    except Exception as ex:
        log.error(f"[error] icepack failed for variant '{name}': {ex}")
        raise

    # 4) Parse timing/resources, produce summary.csv
    try:
        run(["python3", str(PARSE_SCRIPT), str(build_dir)])
    except Exception as ex:
        log.error(f"[error] parse_nextpnr_report failed for variant '{name}': {ex}")
        raise

    log.info(f"[variant] Completed '{name}' -> {build_dir}")
    return build_dir


def aggregate_summaries(variant_names: List[str]) -> Path:
    """
    Aggregate per-variant summary.csv files into artifacts/variants_summary.csv.

    Parameters:
        variant_names: Names of variants to include in the aggregation.

    Returns:
        Path to the aggregated CSV in artifacts/.
    """
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = ARTIFACTS_DIR / "variants_summary.csv"

    # Header as specified
    header = [
        "variant", "TAPS", "PIPELINE", "ROUND", "SAT",
        "FMAX_nextpnr_MHz", "FMAX_icetime_MHz", "Slack_ns_12MHz", "Meets_12MHz",
        "LUT4", "LUT4_pct", "DFF", "DFF_pct", "BRAM_4K", "BRAM_pct", "DSP_MAC16", "DSP_pct"
    ]

    with out_csv.open("w", newline="", encoding="utf-8") as fh_out:
        writer = csv.writer(fh_out)
        writer.writerow(header)
        for name in variant_names:
            summary = REPO_ROOT / "build" / name / "summary.csv"
            if not summary.exists():
                log.warning(f"[warn] summary.csv missing for variant '{name}', skipping aggregation")
                continue
            with summary.open("r", encoding="utf-8") as fh_in:
                rows = list(csv.reader(fh_in))
                if not rows:
                    continue
                # Skip header of the per-variant summary (first row)
                for row in rows[1:]:
                    writer.writerow(row)

    log.info(f"[aggregate] Wrote {out_csv}")
    return out_csv


def main() -> None:
    """
    CLI entrypoint. Builds selected variants and aggregates summaries.

    Honors:
        --only: Comma-separated set of variants to build.

    Exit Codes:
        1 if any variant build fails; 0 on success.
    """
    setup_logging()
    _ = get_logger(__name__)  # Ensures module logger is configured

    parser = argparse.ArgumentParser(description="Parameterized per-variant synth/PnR for iCE40")
    parser.add_argument("--only", help="Comma-separated variant names to build", default=None)
    args = parser.parse_args()

    variants = load_variants(CONFIG_PATH)
    selected = filter_variants(variants, args.only)

    built_names: List[str] = []
    for v in selected:
        try:
            build_variant(v)
            built_names.append(v["name"])
        except Exception:
            log.error(f"[fatal] Build failed for variant '{v['name']}'")
            sys.exit(1)

    aggregate_summaries(built_names)


if __name__ == "__main__":
    main()