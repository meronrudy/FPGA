#!/usr/bin/env python3
"""
Convert configs/variants.yaml from nested params schema to flat schema.

- Input default: [configs/variants.yaml](configs/variants.yaml)
- Output:
  - If --in-place, overwrites the input file (with optional .bak backup).
  - Else, writes to --output path.

Schemas
- Nested (legacy)
  variants:
    - name: baseline8
      params: { ROUND: 1, SAT: 1, PIPELINE: 0, TAPS: 8 }
      yosys_opts: "...", nextpnr_opts: "...", seed: 1

- Flat (target; validated by [common.config.load_config](common/config.py:95))
  variants:
    - name: baseline8
      taps: 8
      pipeline: 0
      round: "round"      # or "truncate"
      sat: "saturate"     # or "wrap"
      yosys_opts: "...", nextpnr_opts: "...", seed: 1, freq: 12

Exit codes:
  0 success
  2 input file not found or YAML parse error
  3 schema validation error
  4 output write error
  1 unexpected error
"""

from __future__ import annotations

# Extend module docstring with explicit before/after examples and mapping notes.
__doc__ += r"""

Schema mapping — before/after examples

Legacy (nested) example:
  variants:
    - name: baseline8
      params: { ROUND: 1, SAT: 1, PIPELINE: 0, TAPS: 8 }
      yosys_opts: "-abc9 -relut"
      nextpnr_opts: "--placer heap --router router2"
      seed: 1

Flat (target) example:
  variants:
    - name: baseline8
      taps: 8
      pipeline: 0
      round: "round"      # (ROUND=1 → "round"; ROUND=0 → "truncate")
      sat: "saturate"     # (SAT=1 → "saturate"; SAT=0 → "wrap")
      yosys_opts: "-abc9 -relut"
      nextpnr_opts: "--placer heap --router router2"
      seed: 1
      # optional freq (int MHz) if desired, default 12 in downstream flows

Mapping summary:
  TAPS (int)           → taps (int)
  PIPELINE (0|1)       → pipeline (0|1)
  ROUND (0|1)          → round ("truncate"|"round")
  SAT (0|1)            → sat ("wrap"|"saturate")
  yosys_opts (str)     → passthrough
  nextpnr_opts (str)   → passthrough
  seed (int)           → passthrough
  freq (int, optional) → passthrough if present in legacy

Error handling:
- Mixed schemas (both nested and flat in one file) are rejected for manual normalization.
- Non-integer or out-of-range values cause a schema/validation error (exit 3).
- With --in-place --backup, writes a .bak copy before overwriting.

"""

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from common.logging import setup_logging, get_logger, set_verbosity


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="scripts.convert_variants_schema",
        description="Convert variants.yaml from nested params schema to flat schema",
    )
    p.add_argument(
        "-i", "--input",
        type=Path,
        default=Path("configs/variants.yaml"),
        help="Path to input YAML (default: configs/variants.yaml)",
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument(
        "-o", "--output",
        type=Path,
        help="Path to output YAML (if omitted with --in-place, overwrites input)",
    )
    g.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite the input file in place",
    )
    p.add_argument(
        "--backup",
        action="store_true",
        help="When used with --in-place, write a .bak backup of the original",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write any files; print summary only",
    )
    p.add_argument(
        "-v", "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v=INFO, -vv=DEBUG)",
    )
    p.add_argument(
        "--log-level",
        choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"],
        default=None,
        help="Explicit log level (overrides -v and LOG_LEVEL)",
    )
    return p.parse_args(argv)


def _is_nested_variant(v: Any) -> bool:
    return isinstance(v, dict) and "params" in v and isinstance(v["params"], dict)


def _is_flat_variant(v: Any) -> bool:
    return isinstance(v, dict) and "taps" in v and "pipeline" in v and ("round" in v or "sat" in v)


def _round_int_to_str(val: int) -> str:
    if val not in (0, 1):
        raise ValueError("ROUND must be 0 or 1")
    return "round" if val == 1 else "truncate"


def _sat_int_to_str(val: int) -> str:
    if val not in (0, 1):
        raise ValueError("SAT must be 0 or 1")
    return "saturate" if val == 1 else "wrap"


def convert_nested_to_flat(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert a nested-schema config dict to a flat-schema dict.

    Parameters:
      data: Mapping with top-level key "variants" (list[dict]) in legacy nested form.

    Returns:
      dict with {"variants": [flat variants...]}, preserving optional passthroughs
      (yosys_opts, nextpnr_opts, seed, freq) when present.

    Raises:
      ValueError on structural/type errors (missing keys, wrong types, out-of-range).
    """
    if "variants" not in data or not isinstance(data["variants"], list):
        raise ValueError('Missing top-level "variants" list')
    out: Dict[str, Any] = {"variants": []}
    for idx, v in enumerate(data["variants"]):
        if not _is_nested_variant(v):
            raise ValueError(f"variants[{idx}] not in nested schema (missing 'params')")
        name = v.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"variants[{idx}].name must be a non-empty string")

        p = v["params"]
        try:
            taps = int(p["TAPS"])
            pipeline = int(p["PIPELINE"])
            round_i = int(p["ROUND"])
            sat_i = int(p["SAT"])
        except Exception as ex:
            raise ValueError(f"variants[{idx}] '{name}' params type error: {ex}") from ex

        flat: Dict[str, Any] = {
            "name": name.strip(),
            "taps": taps,
            "pipeline": 1 if pipeline else 0,
            "round": _round_int_to_str(round_i),
            "sat": _sat_int_to_str(sat_i),
        }

        # Optional passthroughs
        for opt_key in ("yosys_opts", "nextpnr_opts", "seed", "freq"):
            if opt_key in v and v[opt_key] is not None:
                flat[opt_key] = v[opt_key]

        out["variants"].append(flat)
    return out


def load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise
    if not isinstance(data, dict):
        raise ValueError("Top-level YAML must be a mapping")
    return data


def dump_yaml(path: Path, data: Dict[str, Any]) -> None:
    content = yaml.safe_dump(
        data,
        sort_keys=False,
        default_flow_style=False,
        width=100,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    setup_logging(level=args.log_level)
    if args.log_level is None:
        set_verbosity(args.verbose)
    log = get_logger(__name__)

    try:
        src: Path = args.input
        data = load_yaml(src)

        variants = data.get("variants")
        if not isinstance(variants, list):
            log.error('Missing top-level "variants" list')
            return 3

        has_nested = any(_is_nested_variant(v) for v in variants)
        has_flat = any(_is_flat_variant(v) for v in variants)

        if has_nested and has_flat:
            log.error("Mixed schemas detected (nested and flat). Normalize manually.")
            return 3

        if has_flat and not has_nested:
            log.info("Input appears to already be in flat schema; nothing to convert.")
            return 0

        # Convert nested → flat
        flat = convert_nested_to_flat(data)

        # Output decision
        if args.dry_run:
            log.info("Dry run: would convert %s variants and write to %s",
                     len(flat["variants"]),
                     (str(args.output) if args.output else (str(src) + " (in-place)")))
            return 0

        # Determine output path
        if args.in_place and not args.output:
            if args.backup:
                bak = src.with_suffix(src.suffix + ".bak")
                bak.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
                log.info("Wrote backup: %s", bak)
            dump_yaml(src, flat)
            log.info("Converted in place: %s", src)
        else:
            out = args.output or src
            dump_yaml(out, flat)
            log.info("Converted and wrote: %s", out)

        return 0

    except FileNotFoundError as e:
        log.error("%s", e)
        return 2
    except yaml.YAMLError as e:
        log.error("YAML parse error: %s", e)
        return 2
    except ValueError as e:
        log.error("Schema/validation error: %s", e)
        return 3
    except PermissionError as e:
        log.error("Write permission error: %s", e)
        return 4
    except Exception as e:  # pragma: no cover
        log.exception("Unexpected error: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())