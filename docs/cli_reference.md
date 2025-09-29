# CLI Reference

This reference documents the command‑line interfaces provided by the project’s agents and scripts, including arguments, environment behavior, exit codes, and example invocations.

Tools covered:
- Designer agent: [agents/designer.py](agents/designer.py)
- Simulation agent: [agents/sim.py](agents/sim.py)
- Synthesis agent: [agents/synth.py](agents/synth.py)
- Report generator: [scripts/mk_phase1_report.py](scripts/mk_phase1_report.py)
- PnR report parser: [scripts/parse_nextpnr_report.py](scripts/parse_nextpnr_report.py)
- Import smoke check: [scripts/check_imports.py](scripts/check_imports.py)

Before running any tool, install dependencies listed in [requirements.txt](requirements.txt).

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Check variants and parameters defined for synthesis in [configs/variants.yaml](configs/variants.yaml).

---

## 1) Designer Agent — YAML → JSON

File: [agents/designer.py](agents/designer.py)

Purpose:
- Load a “flat‑schema” YAML file, validate it via [common/config.py](common/config.py), and write normalized JSON to `artifacts/`.

Synopsis:
```bash
python -m agents.designer --help
python -m agents.designer \
  --input configs/variants_flat.yaml \
  --output artifacts/variants.json \
  -vv
```

Arguments:
- -i, --input PATH
  - Path to flat‑schema YAML (default: `configs/variants.yaml`)
  - Note: The repository’s provided [configs/variants.yaml](configs/variants.yaml) is synthesis‑oriented (nested UPPERCASE `params`) and does NOT match the flat schema expected by the designer. Use a separate flat YAML or adjust accordingly.
- -o, --output PATH
  - Output JSON path (default: `artifacts/variants.json`)
- -v, --verbose
  - Increase verbosity: `-v` → INFO, `-vv` → DEBUG
- --log-level {CRITICAL,ERROR,WARNING,INFO,DEBUG,NOTSET}
  - Explicit log level (overrides `-v` and LOG_LEVEL)

Exit codes:
- 0 success
- 2 file not found or YAML parse error
- 3 schema validation error (flat schema)
- 4 write/permission error
- 1 unexpected error

Outputs:
- JSON written to the `--output` path with normalized structure.

---

## 2) Simulation Agent — cocotb front‑end

File: [agents/sim.py](agents/sim.py)

Purpose:
- Drive the cocotb simulation Makefile [sim/cocotb/Makefile](sim/cocotb/Makefile) by preparing environment variables and invoking `make`.

Synopsis:
```bash
python agents/sim.py --help
python agents/sim.py --sim verilator --top fir8 --taps 8 --pipeline 0
python agents/sim.py --sim icarus   --top fir8 --taps 16 --pipeline 1
# Explicit rounding/saturation as strings:
python agents/sim.py --top fir8 --taps 8 --pipeline 0 --round round --sat saturate
python agents/sim.py --top fir8 --taps 8 --pipeline 0 --round truncate --sat wrap
```

Key notes:
- The cocotb Makefile sets `TOPLEVEL := fir8`. Pass `--top fir8` to align with that default.
- Use `--sim verilator` or `--sim icarus`. Defaults to environment or Makefile default if omitted.
- The `--variant` option expects a flat‑schema YAML (via [common/config.py](common/config.py)). The repository’s synthesis file [configs/variants.yaml](configs/variants.yaml) uses nested uppercase `params` and is not compatible with `--variant`. Prefer explicit flags (`--taps/--pipeline/--round/--sat`) unless you maintain a separate flat YAML.

Arguments:
- -m, --makefile PATH (default: `sim/cocotb/Makefile`)
- --module NAME (default: `test_fir8`) → MODULE
- --top NAME (default: `fir8_top`, but use `fir8` for this repo) → TOPLEVEL
- --sim NAME (`verilator` or `icarus`) → SIM
- --variant NAME
  - Load parameters from a flat‑schema YAML (requires a compatible file)
- Overrides (explicit flags win over `--variant`):
  - --taps INT (positive)
  - --pipeline INT (≥ 0)
  - --round {round,truncate}
  - --sat {saturate,wrap}
- Logging:
  - -v/--verbose (counts), --log-level as above

Environment mapping to Make:
- MODULE, TOPLEVEL, SIM, TAPS, PIPELINE, ROUND, SAT

Exit codes:
- 0 success
- 2 file not found (Makefile) or YAML parse error
- 3 validation/config error (missing variant, bad types/choices)
- 4 subprocess failure (make returned non‑zero)
- 1 unexpected error

Outputs:
- Simulator build logs under the cocotb build directories
- Coverage YAML at `build/coverage_{TAPS}_{PIPELINE}_{ROUND}_{SAT}.yml` (see [sim/cocotb/test_fir8.py](sim/cocotb/test_fir8.py))

---

## 3) Synthesis Agent — iCE40 flow

File: [agents/synth.py](agents/synth.py)

Purpose:
- Build one or more variants through Yosys → nextpnr‑ice40 → IceStorm, parse results, and aggregate summaries.

Synopsis:
```bash
python agents/synth.py --help
python agents/synth.py
python agents/synth.py --only baseline8,pipelined8   # check your variant names in configs/variants.yaml
```

Arguments:
- --only "v1,v2,..."
  - Comma‑separated list of variant names (see [configs/variants.yaml](configs/variants.yaml))

Behavior:
- Generates `build/<variant>/run.ys` to:
  - read RTL: [src/rtl/fir8.v](src/rtl/fir8.v), [src/rtl/fir8_top.v](src/rtl/fir8_top.v)
  - chparam fir8 (ROUND,SAT) and fir8_top (TAPS,PIPELINE)
  - synthesize with `synth_ice40`
- Invokes:
  - PnR wrapper: [synth/ice40/nextpnr_ice40.sh](synth/ice40/nextpnr_ice40.sh)
  - Pack wrapper: [synth/ice40/icestorm_pack.sh](synth/ice40/icestorm_pack.sh)
- Parses timing/resources → `build/<variant>/summary.csv` using [scripts/parse_nextpnr_report.py](scripts/parse_nextpnr_report.py)
- Aggregates summaries → `artifacts/variants_summary.csv`

Exit codes:
- 0 success
- 1 if any variant build fails
- 2 on schema errors/unknown variants (load/filter stage)

Outputs per variant (under `build/<variant>/`):
- `run.ys`, `fir8_top.json`, `fir8_top_netlist.v`, `yosys_stat.json`
- `nextpnr.log`, `icetime.log`, `fir8_top.asc`, `fir8_top.bin`
- `meta.json`, `summary.csv`

Aggregated outputs:
- `artifacts/variants_summary.csv`

---

## 4) Report Generator — Phase 1 Markdown

File: [scripts/mk_phase1_report.py](scripts/mk_phase1_report.py)

Purpose:
- Convert aggregated CSV to a Markdown report with timing/utilization per variant and basic resource sanity checks.

Synopsis:
```bash
python scripts/mk_phase1_report.py --help
python scripts/mk_phase1_report.py
python scripts/mk_phase1_report.py --summary artifacts/variants_summary.csv --out artifacts/report_phase1.md
```

Arguments:
- --summary PATH (default: `artifacts/variants_summary.csv`)
- --out PATH (default: `artifacts/report_phase1.md`)

Behavior:
- Reads CSV and renders a GitHub‑friendly Markdown table
- Highlights 12 MHz timing result
- Validates that resources do not exceed the iCE40UP5K totals

Exit codes:
- 0 success
- 2 missing summary file or I/O error
- 3 resource sanity failure (exceeds device totals)

Outputs:
- `artifacts/report_phase1.md` (Markdown)
- Reuses `artifacts/variants_summary.csv` as input

---

## 5) PnR Report Parser — per‑variant CSV

File: [scripts/parse_nextpnr_report.py](scripts/parse_nextpnr_report.py)

Purpose:
- Parse nextpnr/icetime timing and Yosys utilization into `BUILD/summary.csv`.

Synopsis:
```bash
# Using positional build dir
python scripts/parse_nextpnr_report.py build/baseline8
# Or using -i/--input
python scripts/parse_nextpnr_report.py -i build/baseline8
```

Arguments:
- Positional `build_dir` (optional)
- -i, --input PATH (alternative to positional)
- If neither is provided, uses `BUILD` environment variable; else defaults to `build`

Expected inputs in the build directory:
- `nextpnr.log`, `icetime.log`, `yosys_stat.json`, and optional `meta.json`

Exit codes:
- 0 success
- 2 missing inputs, parse errors, or write failures

Outputs:
- `BUILD/summary.csv` with columns:
  - `variant,TAPS,PIPELINE,ROUND,SAT,FMAX_nextpnr_MHz,FMAX_icetime_MHz,Slack_ns_12MHz,Meets_12MHz,LUT4,LUT4_pct,DFF,DFF_pct,BRAM_4K,BRAM_pct,DSP_MAC16,DSP_pct`

---

## 6) Import Smoke — imports + CLI `--help`

File: [scripts/check_imports.py](scripts/check_imports.py)

Purpose:
- Quick smoke to ensure key modules import and CLIs launch with `--help`.

Synopsis:
```bash
python scripts/check_imports.py
```

Behavior:
- Imports selected modules
- Spawns processes to run `--help` on the primary CLIs:
  - `python -m agents.designer --help`
  - `python -m agents.sim --help`
  - `python -m agents.synth --help`
  - `python scripts/mk_phase1_report.py --help`
  - `python scripts/parse_nextpnr_report.py --help`
- Tolerates non‑zero exit from `--help` (argparse may exit with various codes)
- Fails only if a process cannot be started or a module fails to import

Exit codes:
- 0 success
- 1 on any failure to import or failure to start a CLI process

---

## Environment and Logging

Logging:
- All tools use [common/logging.py](common/logging.py). Control verbosity via:
  - `LOG_LEVEL=DEBUG` (environment)
  - `-v/--verbose` or `--log-level` (CLI, when provided)
- See policy and examples in [docs/logging_config.md](docs/logging_config.md)

Python version:
- Tools target Python 3.8+; see [pyproject.toml](pyproject.toml) for Ruff/Mypy settings.

Simulators and toolchains:
- Simulation requires Verilator or Icarus (see [sim/cocotb/Makefile](sim/cocotb/Makefile))
- Synthesis requires yosys, nextpnr‑ice40, and Icestorm utilities
- PnR scripts and constraints: [synth/ice40/nextpnr_ice40.sh](synth/ice40/nextpnr_ice40.sh), [synth/ice40/icestorm_pack.sh](synth/ice40/icestorm_pack.sh), [constraints/icebreaker.pcf](constraints/icebreaker.pcf)

---

## Examples end‑to‑end

1) Simulate default parameters with Verilator:
```bash
python agents/sim.py --sim verilator --top fir8 --taps 8 --pipeline 0
```

2) Build two variants and aggregate:
```bash
python agents/synth.py --only baseline8,pipelined8
python scripts/mk_phase1_report.py
```

3) Parse a single variant after external PnR run:
```bash
python scripts/parse_nextpnr_report.py build/baseline8
```

If you plan to use the designer for YAML→JSON, maintain a separate flat‑schema YAML (see [docs/configuration.md](docs/configuration.md)) rather than reusing the synthesis‑style [configs/variants.yaml](configs/variants.yaml).