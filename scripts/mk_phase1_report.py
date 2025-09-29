#!/usr/bin/env python3
"""
Generate Phase 1 report from aggregated synthesis/PnR summaries.

Inputs:
  - artifacts/variants_summary.csv (required, override with --summary)

Outputs:
  - artifacts/report_phase1.md (override with --out)

Behavior:
  - Renders a Markdown table with timing/utilization per variant.
  - Highlights 12 MHz timing result.
  - Sanity-checks resource usage against device totals and exits non-zero if exceeded.

CLI:
  - --summary PATH: path to variants_summary.csv (defaults to artifacts/variants_summary.csv)
  - --out PATH: path to write report (defaults to artifacts/report_phase1.md)

Exit codes:
  - 0: success
  - 2: missing summary file or I/O error
  - 3: resource sanity failure (exceeds device totals)
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import List, Dict, Optional

from common.logging import setup_logging, get_logger

REPO_ROOT = Path(__file__).resolve().parents[1]
ART_DIR = REPO_ROOT / "artifacts"
SUMMARY_CSV = ART_DIR / "variants_summary.csv"
REPORT_MD = ART_DIR / "report_phase1.md"

# Device totals for sanity checks (iCE40UP5K estimates)
LUT4_TOTAL = 5280
DFF_TOTAL = 5280
BRAM_4K_TOTAL = 30
DSP_MAC16_TOTAL = 8

log = get_logger(__name__)


def read_rows(path: Path) -> List[Dict[str, str]]:
    """
    Read CSV rows from the given summary path.
    Exits with code 2 if the file is missing.
    """
    if not path.exists():
        log.error("[error] Missing summary CSV: %s", path)
        sys.exit(2)
    with path.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader)


def sanity_check_resources(rows: List[Dict[str, str]]) -> None:
    """
    Validate resource usage does not exceed device totals.
    Exits with code 3 on failure.
    """
    ok = True
    for r in rows:
        try:
            lut = int(float(r.get("LUT4", "0")))
            dff = int(float(r.get("DFF", "0")))
            bram = int(float(r.get("BRAM_4K", "0")))
            dsp = int(float(r.get("DSP_MAC16", "0")))
        except Exception:
            log.warning("[warn] Non-integer resource values in row: %s", r)
            continue

        if lut > LUT4_TOTAL:
            ok = False
            log.error(
                "[error] LUT4 exceeds device total: %d > %d (variant=%s)",
                lut, LUT4_TOTAL, r.get("variant"),
            )
        if dff > DFF_TOTAL:
            ok = False
            log.error(
                "[error] DFF exceeds device total: %d > %d (variant=%s)",
                dff, DFF_TOTAL, r.get("variant"),
            )
        if bram > BRAM_4K_TOTAL:
            ok = False
            log.error(
                "[error] BRAM_4K exceeds device total: %d > %d (variant=%s)",
                bram, BRAM_4K_TOTAL, r.get("variant"),
            )
        if dsp > DSP_MAC16_TOTAL:
            ok = False
            log.error(
                "[error] DSP_MAC16 exceeds device total: %d > %d (variant=%s)",
                dsp, DSP_MAC16_TOTAL, r.get("variant"),
            )

    if not ok:
        sys.exit(3)


def render_report(rows: List[Dict[str, str]]) -> str:
    """
    Render the Markdown report content. Does not modify files.
    """
    # Sort rows by variant name for stable output
    rows = sorted(rows, key=lambda r: r.get("variant", ""))

    md: List[str] = []
    md.append("# Phase 1 Report")
    md.append("")
    md.append("Target timing: 12 MHz (83.333 ns period).")
    md.append("")
    md.append("| Variant | TAPS | PIPELINE | ROUND | SAT | Fmax nextpnr (MHz) | Fmax icetime (MHz) | Slack @12MHz (ns) | Meets 12MHz | LUT4 | DFF | BRAM4K | DSP |")
    md.append("|---|---:|---:|---:|---:|---:|---:|---:|:---:|---:|---:|---:|---:|")
    for r in rows:
        meets = str(r.get("Meets_12MHz", "")).strip().upper()
        meets_badge = "✅" if meets in ("YES", "TRUE", "1") else "❌"
        md.append(
            "| {v} | {t} | {p} | {r_} | {s} | {fn} | {fi} | {sl} | {mb} | {lut} | {dff} | {br} | {dsp} |".format(
                v=r.get("variant", ""),
                t=r.get("TAPS", ""),
                p=r.get("PIPELINE", ""),
                r_=r.get("ROUND", ""),
                s=r.get("SAT", ""),
                fn=r.get("FMAX_nextpnr_MHz", ""),
                fi=r.get("FMAX_icetime_MHz", ""),
                sl=r.get("Slack_ns_12MHz", ""),
                mb=meets_badge,
                lut=r.get("LUT4", ""),
                dff=r.get("DFF", ""),
                br=r.get("BRAM_4K", ""),
                dsp=r.get("DSP_MAC16", ""),
            )
        )
    md.append("")
    md.append("Artifacts:")
    md.append("- artifacts/variants_summary.csv")
    md.append("- artifacts/report_phase1.md (this file)")
    md.append("")
    return "\n".join(md)


def build_arg_parser() -> argparse.ArgumentParser:
    """
    Build the CLI argument parser.
    """
    parser = argparse.ArgumentParser(
        description="Generate Phase 1 Markdown report from variants summary CSV."
    )
    parser.add_argument(
        "--summary",
        type=str,
        default=str(SUMMARY_CSV),
        help=f"Path to variants_summary.csv (default: {SUMMARY_CSV})",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=str(REPORT_MD),
        help=f"Output Markdown path (default: {REPORT_MD})",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    """
    Program entry point. Parses args, validates inputs, writes report.
    """
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    summary_path = Path(args.summary)
    out_path = Path(args.out)

    rows = read_rows(summary_path)
    # Checks and render
    sanity_check_resources(rows)
    report = render_report(rows)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report + "\n", encoding="utf-8")
    log.info("[report] Wrote %s", out_path)


if __name__ == "__main__":
    setup_logging(level=None)
    main()
