#!/usr/bin/env python3
"""
Parse nextpnr/icetime timing and Yosys utilization into a per-variant CSV summary.

Inputs:
  - BUILD directory:
      Via positional argument 'build_dir' OR -i/--input PATH.
      If neither is provided, falls back to environment variable BUILD.
      If BUILD is not set, defaults to "build".
    Expected files inside BUILD:
      - nextpnr.log
      - icetime.log
      - yosys_stat.json
      - meta.json (contains {"variant": <name>, "params": {TAPS, PIPELINE, ROUND, SAT}})
        If absent or invalid, defaults are used.

Outputs:
  - BUILD/summary.csv with columns:
      variant, TAPS, PIPELINE, ROUND, SAT,
      FMAX_nextpnr_MHz, FMAX_icetime_MHz, Slack_ns_12MHz, Meets_12MHz,
      LUT4, LUT4_pct, DFF, DFF_pct, BRAM_4K, BRAM_pct, DSP_MAC16, DSP_pct

Assumptions:
  - Device: iCE40UP5K
    Resource totals (approx/estimates):
      LUT4_TOTAL       = 5280
      DFF_TOTAL        = 5280
      BRAM_4K_TOTAL    = 30
      DSP_MAC16_TOTAL  = 8
  - Target period for slack: 83.333 ns (12 MHz)

Exit codes:
  - 0: success
  - 2: missing inputs, parse errors, or write failures

Logging:
  - Uses centralized logging (LOG_LEVEL env controls verbosity; default INFO).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from common.logging import setup_logging, get_logger

# Device totals for iCE40UP5K (estimates)
LUT4_TOTAL = 5280
DFF_TOTAL = 5280
BRAM_4K_TOTAL = 30
DSP_MAC16_TOTAL = 8

TARGET_PERIOD_NS = 83.333  # 12 MHz

log = get_logger(__name__)


def read_text(path: Path) -> str:
    """
    Read a text file with UTF-8 encoding.

    Exits with code 2 on error.
    """
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception as ex:
        log.error("[error] failed to read %s: %s", path, ex)
        sys.exit(2)


def parse_nextpnr_fmax(nextpnr_log: Path) -> float:
    """
    Parse nextpnr log to extract Fmax in MHz.

    Returns:
        Fmax in MHz (0.0 if not found).
    """
    text = read_text(nextpnr_log)
    # Common patterns nextpnr may print
    pats = [
        r"Max frequency:\s*([0-9]+(?:\.[0-9]+)?)\s*MHz",
        r"Info:\s*Max frequency is\s*([0-9]+(?:\.[0-9]+)?)\s*MHz",
        r"Critical path delay:\s*([0-9]+(?:\.[0-9]+)?)\s*ns",
    ]
    fmax: Optional[float] = None
    crit_ns: Optional[float] = None
    for pat in pats:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            if "MHz" in pat:
                fmax = float(m.group(1))
                break
            else:
                crit_ns = float(m.group(1))
                # convert to MHz
                if crit_ns > 0:
                    fmax = 1000.0 / crit_ns
                    break
    return fmax or 0.0


def parse_icetime_metrics(icetime_log: Path) -> Tuple[float, float]:
    """
    Parse icetime log.

    Returns:
        (fmax_mhz, critical_ns)
    """
    text = read_text(icetime_log)
    fmax = 0.0
    crit_ns = 0.0

    m = re.search(r"Max frequency:\s*([0-9]+(?:\.[0-9]+)?)\s*MHz", text, re.IGNORECASE)
    if m:
        fmax = float(m.group(1))
        if fmax > 0:
            crit_ns = 1000.0 / fmax

    # If no fmax, look for total path delay
    if fmax <= 0.0:
        m2 = re.search(r"Total path delay:\s*([0-9]+(?:\.[0-9]+)?)\s*ns", text, re.IGNORECASE)
        if m2:
            crit_ns = float(m2.group(1))
            if crit_ns > 0:
                fmax = 1000.0 / crit_ns

    return fmax, crit_ns


def parse_yosys_stat(yosys_stat_json: Path) -> Tuple[int, int, int, int]:
    """
    Parse a Yosys 'stat -json' output file.

    Returns:
        (lut4, dff, bram_4k, dsp_mac16)

    Exits with code 2 on parse failure.
    """
    try:
        data = json.loads(read_text(yosys_stat_json))
    except Exception as ex:
        log.error("[error] failed to parse JSON %s: %s", yosys_stat_json, ex)
        sys.exit(2)

    # The "stat -json" format can contain top-level "cells" or per-module details.
    # Aggregate by scanning for known iCE40 cell types.
    def agg_cells(cells_dict: Dict[str, Any]) -> Tuple[int, int, int, int]:
        lut4 = int(cells_dict.get("SB_LUT4", 0))
        dff = int(cells_dict.get("SB_DFF", 0))
        # Also count variants like SB_DFFR, SB_DFFS, SB_DFFSR, etc.
        for k, v in cells_dict.items():
            if k.startswith("SB_DFF") and k != "SB_DFF":
                dff += int(v)
        bram = int(cells_dict.get("SB_RAM40_4K", 0))
        dsp = int(cells_dict.get("SB_MAC16", 0))
        return lut4, dff, bram, dsp

    lut4 = dff = bram = dsp = 0

    if isinstance(data, dict):
        # Newer Yosys places "cells" at the root with totals
        if "cells" in data and isinstance(data["cells"], dict):
            l, d, b, m = agg_cells(data["cells"])
            lut4 += l
            dff += d
            bram += b
            dsp += m

        # Also look into "modules" if present
        mods = data.get("modules", {})
        if isinstance(mods, dict):
            for _mname, mdef in mods.items():
                if "cells" in mdef and isinstance(mdef["cells"], dict):
                    # mdef["cells"] is a map of cell instances -> type; need to tally types
                    type_counts: Dict[str, int] = {}
                    for _inst, cinfo in mdef["cells"].items():
                        ctype = cinfo.get("type")
                        if ctype:
                            type_counts[ctype] = type_counts.get(ctype, 0) + 1
                    l, d, b, m = agg_cells(type_counts)
                    lut4 += l
                    dff += d
                    bram += b
                    dsp += m

    return lut4, dff, bram, dsp


def pct(used: int, total: int) -> float:
    """
    Compute percentage of used over total.
    """
    if total <= 0:
        return 0.0
    return (float(used) / float(total)) * 100.0


def load_meta(build_dir: Path) -> Dict[str, Any]:
    """
    Load meta.json for variant name and parameters.

    Returns:
        Dict with at least keys: "variant", "params".
    """
    meta_path = build_dir / "meta.json"
    if not meta_path.exists():
        # fallback if meta is absent
        return {
            "variant": build_dir.name,
            "params": {"TAPS": 8, "PIPELINE": 0, "ROUND": 1, "SAT": 1},
        }
    try:
        return json.loads(read_text(meta_path))
    except Exception as ex:
        log.warning("[warn] Failed to parse meta.json: %s, using defaults", ex)
        return {
            "variant": build_dir.name,
            "params": {"TAPS": 8, "PIPELINE": 0, "ROUND": 1, "SAT": 1},
        }


def build_arg_parser() -> argparse.ArgumentParser:
    """
    Build the CLI argument parser.

    Supports:
      - Optional positional 'build_dir'
      - Optional -i/--input PATH (alternative to positional)
      - Environment fallback BUILD when neither provided
    """
    parser = argparse.ArgumentParser(
        description="Parse nextpnr/icetime timing and Yosys utilization into BUILD/summary.csv"
    )
    parser.add_argument(
        "build_dir",
        nargs="?",
        help="Build directory containing logs (default: env BUILD or 'build')",
    )
    parser.add_argument(
        "-i",
        "--input",
        dest="input",
        help="Alternative input build directory path",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    """
    Program entry point. Parses arguments, validates inputs, writes summary CSV.
    """
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    # Determine build directory precedence:
    # 1) --input if provided
    # 2) positional build_dir if provided
    # 3) env BUILD
    # 4) "build"
    build_dir_str = (
        args.input
        if args.input
        else (args.build_dir if args.build_dir else os.environ.get("BUILD", "build"))
    )
    build_dir = Path(build_dir_str).resolve()

    nextpnr_log = build_dir / "nextpnr.log"
    icetime_log = build_dir / "icetime.log"
    yosys_stat_json = build_dir / "yosys_stat.json"

    for p in (nextpnr_log, icetime_log, yosys_stat_json):
        if not p.exists():
            log.error("[error] missing expected file: %s", p)
            sys.exit(2)

    meta = load_meta(build_dir)
    name = meta.get("variant", build_dir.name)
    params = meta.get("params", {})
    taps = int(params.get("TAPS", 8))
    pipeline = int(params.get("PIPELINE", 0))
    round_en = int(params.get("ROUND", 1))
    sat_en = int(params.get("SAT", 1))

    # Parse timing
    fmax_nextpnr = parse_nextpnr_fmax(nextpnr_log)
    fmax_icetime, crit_ns_icetime = parse_icetime_metrics(icetime_log)

    # Derive critical path and slack using icetime result if available, else from nextpnr
    if crit_ns_icetime > 0.0:
        critical_ns = crit_ns_icetime
    else:
        critical_ns = 1000.0 / fmax_nextpnr if fmax_nextpnr > 0 else 0.0

    slack_ns = TARGET_PERIOD_NS - critical_ns if critical_ns > 0 else 0.0
    meets = slack_ns >= 0.0

    # Parse resources
    lut4, dff, bram4k, dsp = parse_yosys_stat(yosys_stat_json)

    # Percentages
    lut4_pct = pct(lut4, LUT4_TOTAL)
    dff_pct = pct(dff, DFF_TOTAL)
    bram_pct = pct(bram4k, BRAM_4K_TOTAL)
    dsp_pct = pct(dsp, DSP_MAC16_TOTAL)

    # Write CSV
    out_csv = build_dir / "summary.csv"
    header = [
        "variant",
        "TAPS",
        "PIPELINE",
        "ROUND",
        "SAT",
        "FMAX_nextpnr_MHz",
        "FMAX_icetime_MHz",
        "Slack_ns_12MHz",
        "Meets_12MHz",
        "LUT4",
        "LUT4_pct",
        "DFF",
        "DFF_pct",
        "BRAM_4K",
        "BRAM_pct",
        "DSP_MAC16",
        "DSP_pct",
    ]
    row = [
        name,
        str(taps),
        str(pipeline),
        str(round_en),
        str(sat_en),
        f"{fmax_nextpnr:.2f}",
        f"{fmax_icetime:.2f}",
        f"{slack_ns:.3f}",
        "YES" if meets else "NO",
        str(lut4),
        f"{lut4_pct:.2f}",
        str(dff),
        f"{dff_pct:.2f}",
        str(bram4k),
        f"{bram_pct:.2f}",
        str(dsp),
        f"{dsp_pct:.2f}",
    ]

    try:
        with out_csv.open("w", encoding="utf-8") as fh:
            fh.write(",".join(header) + "\n")
            fh.write(",".join(row) + "\n")
    except Exception as ex:
        log.error("[error] failed to write %s: %s", out_csv, ex)
        sys.exit(2)

    log.info("[summary] Wrote %s", out_csv)


if __name__ == "__main__":
    setup_logging(level=None)
    main()
