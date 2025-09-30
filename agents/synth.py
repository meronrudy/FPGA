#!/usr/bin/env python3
"""
Synthesis/PnR agent — per-variant build, metrics extraction, and CSV aggregation (iCE40 UP5K).

Purpose
- Given a validated, flat-schema variants file, build each selected variant through:
  Yosys → nextpnr-ice40 → icestorm pack, then parse timing/resource reports and aggregate results.

Data flow
- Inputs:
  - configs/variants.yaml (flat), validated via common.config.load_config
  - Optional per-variant strategy knobs: yosys_opts, nextpnr_opts, seed, freq (MHz)
- Parameter mapping:
  - round: "round"→1, "truncate"→0  (applies to core fir8)
  - sat:   "saturate"→1, "wrap"→0    (applies to core fir8)
  - pipeline: bool|{0,1}→{0,1}       (applies to top fir8_top)
  - taps: one of {4,8,16,32}         (applies to top fir8_top)
- Outputs:
  - build/<variant>/: fir8_top.json, fir8_top.asc, fir8_top.bin, fir8_top_netlist.v, yosys_stat.json, summary.csv
  - artifacts/variants_summary.csv aggregated across built variants

Nominal flow (per variant)
  1) Yosys:
     read_verilog -sv src/rtl/fir8.v src/rtl/fir8_top.v
     chparam -set ROUND .. -set SAT .. fir8                 # core behavior
     chparam -set TAPS .. -set PIPELINE .. fir8_top         # wrapper/latency
     hierarchy -check -top fir8_top
     synth_ice40 -top fir8_top -json build/<v>/fir8_top.json -abc9 -relut [<yosys_opts>]
     write_verilog -noexpr -attr2comment build/<v>/fir8_top_netlist.v
     stat -json build/<v>/yosys_stat.json
  2) Place/Route:
     bash synth/ice40/nextpnr_ice40.sh (env JSON/ASC/PCF/TOP/FREQ and optional NEXTPNR_OPTS/SEED)
  3) Pack:
     bash synth/ice40/icestorm_pack.sh → BIN
  4) Parse timing/resources:
     python3 scripts/parse_nextpnr_report.py build/<variant>

Error handling
- Validation errors (schema/values) → log error and exit(1) at CLI entry.
- Subprocess failures are surfaced with clear variant context; the first failure causes exit(1).
- Missing summary.csv files for a variant are skipped during aggregation with a warning.

Exit codes
- 0 on success (all selected variants built and aggregation written)
- 1 if any selected variant build fails
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from common.logging import setup_logging, get_logger
from common.config import load_config, ConfigError

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


def _coerce_pipeline(val: Any) -> int:
    """
    Normalize pipeline flag to 0/1.

    Accepted:
      - bool → 1/0
      - int in {0,1}

    Raises:
      ValueError for other values.
    """
    if isinstance(val, bool):
        return 1 if val else 0
    if isinstance(val, int):
        if val in (0, 1):
            return val
    raise ValueError(f"PIPELINE must be 0 or 1 (or bool), got {val!r}")


def _coerce_round(val: Optional[str]) -> int:
    """
    Map textual rounding mode to toolchain flag.

    Mapping:
      "round" → 1
      "truncate" → 0
      None → default 1 (round)

    Raises:
      ValueError if not in {"round","truncate"}.
    """
    if val is None:
        # Default to "round" if unspecified
        return 1
    if val not in ("round", "truncate"):
        raise ValueError("round must be 'round' or 'truncate'")
    return 1 if val == "round" else 0


def _coerce_sat(val: Optional[str]) -> int:
    """
    Map textual saturation mode to toolchain flag.

    Mapping:
      "saturate" → 1
      "wrap"     → 0
      None → default 1 (saturate)

    Raises:
      ValueError if not in {"saturate","wrap"}.
    """
    if val is None:
        # Default to "saturate" if unspecified
        return 1
    if val not in ("saturate", "wrap"):
        raise ValueError("sat must be 'saturate' or 'wrap'")
    return 1 if val == "saturate" else 0


def load_flat_variants(path: Path) -> List[Dict[str, Any]]:
    """
    Load and validate flat-schema variants via common.config.load_config.

    Returns a list of normalized variant dicts:
      {
        'name': str,
        'params': {'TAPS': int, 'PIPELINE': 0|1, 'ROUND': 0|1, 'SAT': 0|1},
        'yosys_opts': str (optional),
        'nextpnr_opts': str (optional),
        'seed': int (optional),
        'freq': int (optional, default 12)
      }
    """
    cfg = load_config(path)
    norm: List[Dict[str, Any]] = []
    for idx, v in enumerate(cfg.variants):
        if not isinstance(v, dict):
            raise ConfigError(f"variants[{idx}] must be a mapping")
        if "name" not in v or not isinstance(v["name"], str) or not v["name"].strip():
            raise ConfigError(f"variants[{idx}].name must be a non-empty string")
        name = v["name"].strip()

        if "taps" not in v or not isinstance(v["taps"], int):
            raise ConfigError(f"variants[{idx}].taps must be an integer")
        taps = int(v["taps"])
        if taps not in ALLOWED_TAPS:
            raise ConfigError(f"variants[{idx}] '{name}': taps must be one of {sorted(ALLOWED_TAPS)} (got {taps})")

        pipeline = _coerce_pipeline(v.get("pipeline", 0))
        rnd = _coerce_round(v.get("round"))
        sat = _coerce_sat(v.get("sat"))
        freq = v.get("freq", 12)
        if not isinstance(freq, int) or freq <= 0:
            raise ConfigError(f"variants[{idx}] '{name}': freq must be a positive integer MHz when present")

        # Optional strategy hooks
        out: Dict[str, Any] = {
            "name": name,
            "params": {
                "TAPS": taps,
                "PIPELINE": pipeline,
                "ROUND": rnd,
                "SAT": sat,
            },
            "freq": freq,
        }
        if "yosys_opts" in v and v["yosys_opts"]:
            if not isinstance(v["yosys_opts"], str):
                raise ConfigError(f"variants[{idx}] '{name}': yosys_opts must be string when present")
            out["yosys_opts"] = v["yosys_opts"]
        if "nextpnr_opts" in v and v["nextpnr_opts"]:
            if not isinstance(v["nextpnr_opts"], str):
                raise ConfigError(f"variants[{idx}] '{name}': nextpnr_opts must be string when present")
            out["nextpnr_opts"] = v["nextpnr_opts"]
        if "seed" in v and v["seed"] is not None:
            if not isinstance(v["seed"], int):
                raise ConfigError(f"variants[{idx}] '{name}': seed must be integer when present")
            out["seed"] = int(v["seed"])
        norm.append(out)
    return norm


def filter_variants(variants: List[Dict[str, Any]], only: Optional[str]) -> List[Dict[str, Any]]:
    """
    Filter the list of variants by a comma-separated list of names.

    Parameters:
        variants: All available variants.
        only: Comma-separated variant names to include; if None or empty, returns all.

    Returns:
        A filtered list of variant dicts.

    Raises:
        ConfigError if any requested variant name is unknown.
    """
    if not only:
        return variants
    names = [x.strip() for x in only.split(",") if x.strip()]
    sel = [v for v in variants if v["name"] in names]
    missing = [n for n in names if n not in {v["name"] for v in variants}]
    if missing:
        raise ConfigError(f"--only contained unknown variants: {', '.join(missing)}")
    return sel


def write_yosys_script(build_dir: Path, variant: Dict[str, Any]) -> Path:
    """
    Generate a Yosys script for the given variant and write it into build_dir.

    Parameters:
        build_dir: The variant's build directory.
        variant: Normalized variant dict including 'name', 'params', and optional 'yosys_opts'.

    Returns:
        Path to the generated run.ys script.
    """
    params = variant["params"]
    name = variant["name"]
    json_out = build_dir / "fir8_top.json"
    netlist_out = build_dir / "fir8_top_netlist.v"
    stat_out = build_dir / "yosys_stat.json"

    yosys_opts = variant.get("yosys_opts", "")
    synth_line = f"synth_ice40 -top fir8_top -json {json_out} -abc9 -relut"
    if yosys_opts:
        synth_line += f" {yosys_opts}"

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
    """Run a subprocess command with optional working directory and environment."""
    log.info(f"[run] {' '.join(cmd)}")
    try:
        subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, check=True)
    except subprocess.CalledProcessError as ex:
        raise RuntimeError(f"command failed with code {ex.returncode}: {' '.join(cmd)}") from ex


def build_variant(variant: Dict[str, Any]) -> Path:
    """
    Build the specified variant through Yosys, nextpnr, and icestorm pack; then parse results.

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
        "FREQ": str(variant.get("freq", 12)),
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
    """
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = ARTIFACTS_DIR / "variants_summary.csv"

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

    parser = argparse.ArgumentParser(description="Parameterized per-variant synth/PnR for iCE40 (flat-schema config)")
    parser.add_argument("--only", help="Comma-separated variant names to build", default=None)
    args = parser.parse_args()

    try:
        variants = load_flat_variants(CONFIG_PATH)
        selected = filter_variants(variants, args.only)
    except (ConfigError, ValueError) as e:
        log.error(f"[error] Config validation: {e}")
        sys.exit(1)

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