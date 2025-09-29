# Synthesis and Place/Route (iCE40UP5K)

This document explains the iCE40 synthesis/PnR flow driven by the synthesis agent, the expected inputs/outputs, and how to interpret the generated artifacts.

Primary components:
- Driver: [agents/synth.py](agents/synth.py)
- Yosys script template (per‑variant generated): see variant `run.ys` under `build/<variant>/`
- PnR wrapper scripts: [synth/ice40/nextpnr_ice40.sh](synth/ice40/nextpnr_ice40.sh), [synth/ice40/icestorm_pack.sh](synth/ice40/icestorm_pack.sh)
- Constraints: [constraints/icebreaker.pcf](constraints/icebreaker.pcf)
- Report parser: [scripts/parse_nextpnr_report.py](scripts/parse_nextpnr_report.py)
- Report aggregator: [scripts/mk_phase1_report.py](scripts/mk_phase1_report.py)

Design sources:
- RTL core and top: [src/rtl/fir8.v](src/rtl/fir8.v), [src/rtl/fir8_top.v](src/rtl/fir8_top.v)

## Flow overview

Per selected variant, the agent performs:
1) Generate a tailored Yosys script `run.ys` with parameter overrides.
2) Run `yosys` to synthesize the design and emit JSON netlist and utilization stats.
3) Invoke nextpnr‑ice40 to place/route with board constraints.
4) Pack the routed design to a `.bin` bitstream using IceStorm.
5) Parse timing/resource reports into `summary.csv`.
6) Aggregate all variant summaries into `artifacts/variants_summary.csv`.

All per‑variant artifacts are written under `build/<variant>/`.

## Running the flow

Help:
```bash
python agents/synth.py --help
```

Build all configured variants (from [configs/variants.yaml](configs/variants.yaml)):
```bash
python agents/synth.py
```

Build a subset:
```bash
python agents/synth.py --only baseline8,pipelined8
```

Notes:
- The synthesis flow expects `params` in [configs/variants.yaml](configs/variants.yaml) with uppercase numeric keys: `TAPS`, `PIPELINE`, `ROUND`, `SAT`. Optional per‑variant flow hooks include `yosys_opts`, `nextpnr_opts`, and `seed`.
- The agent validates parameter ranges: TAPS ∈ {4,8,16,32}; PIPELINE/ROUND/SAT ∈ {0,1}.

## Tools used

- Yosys (synthesis + statistics)
- nextpnr‑ice40 (place & route)
- icestorm (icepack)
- Python reporting/parsing scripts

PnR/pack wrappers:
- [synth/ice40/nextpnr_ice40.sh](synth/ice40/nextpnr_ice40.sh)
- [synth/ice40/icestorm_pack.sh](synth/ice40/icestorm_pack.sh)

Board constraints:
- [constraints/icebreaker.pcf](constraints/icebreaker.pcf)

## Inputs and parameterization

The agent reads variants from [configs/variants.yaml](configs/variants.yaml) and generates a Yosys script similar to:
- Read RTL: [src/rtl/fir8.v](src/rtl/fir8.v), [src/rtl/fir8_top.v](src/rtl/fir8_top.v)
- Apply parameters:
  - Core (fir8): `ROUND`, `SAT`
  - Top (fir8_top): `TAPS`, `PIPELINE`
- Synthesize for iCE40 and emit:
  - JSON netlist: `build/<variant>/fir8_top.json`
  - Netlist Verilog: `build/<variant>/fir8_top_netlist.v`
  - Utilization stats: `build/<variant>/yosys_stat.json`

nextpnr‑ice40 environment variables (set by the agent when calling [synth/ice40/nextpnr_ice40.sh](synth/ice40/nextpnr_ice40.sh)):
- `TOP=fir8_top`
- `JSON=build/<variant>/fir8_top.json`
- `ASC=build/<variant>/fir8_top.asc`
- `PCF=constraints/icebreaker.pcf`
- `FREQ=12` (MHz target context for timing comparison)
- `NEXTPNR_OPTS` (optional; from variant)
- `SEED` (optional; from variant)

Pack (IceStorm) environment for [synth/ice40/icestorm_pack.sh](synth/ice40/icestorm_pack.sh)):
- `ASC=build/<variant>/fir8_top.asc`
- `BIN=build/<variant>/fir8_top.bin`

## Outputs and directory layout

For each selected variant (e.g., `baseline8`), the agent creates:
- `build/baseline8/run.ys` — auto‑generated Yosys script
- `build/baseline8/fir8_top.json` — synthesized netlist (yosys)
- `build/baseline8/fir8_top_netlist.v` — synthesized Verilog (yosys)
- `build/baseline8/yosys_stat.json` — utilization stats
- `build/baseline8/nextpnr.log` — place/route log
- `build/baseline8/icetime.log` — timing estimate log (if produced by flow)
- `build/baseline8/fir8_top.asc` — routed ASCII bitstream
- `build/baseline8/fir8_top.bin` — packed bitstream
- `build/baseline8/meta.json` — variant metadata (name, params)
- `build/baseline8/summary.csv` — parsed summary table

Aggregated artifacts:
- `artifacts/variants_summary.csv` — combined summary across built variants
- `artifacts/report_phase1.md` — optional report, produced by [scripts/mk_phase1_report.py](scripts/mk_phase1_report.py)

## Parsing reports and summarizing

The agent calls [scripts/parse_nextpnr_report.py](scripts/parse_nextpnr_report.py) to extract:
- Timing: Fmax from nextpnr/icetime, critical path, slack at 12 MHz, meets target
- Resources: LUT4, DFF (including variants like SB_DFFR/SR), BRAM_4K, DSP_MAC16
- Percent utilization based on iCE40UP5K totals

Per‑variant summary CSV columns:
- `variant,TAPS,PIPELINE,ROUND,SAT,FMAX_nextpnr_MHz,FMAX_icetime_MHz,Slack_ns_12MHz,Meets_12MHz,LUT4,LUT4_pct,DFF,DFF_pct,BRAM_4K,BRAM_pct,DSP_MAC16,DSP_pct`

Aggregation:
- The agent merges all per‑variant `summary.csv` into [artifacts/variants_summary.csv](artifacts/variants_summary.csv).
- Generate a Markdown report:
  ```bash
  python scripts/mk_phase1_report.py --help
  python scripts/mk_phase1_report.py
  ```
  Outputs [artifacts/report_phase1.md](artifacts/report_phase1.md).

## Constraints

The iCEBreaker board pinout is defined in [constraints/icebreaker.pcf](constraints/icebreaker.pcf). Ensure your clock and LED pins match your board revision if you modify the top.

## Advanced options

Per‑variant options in [configs/variants.yaml](configs/variants.yaml):
- `yosys_opts`: extra switches appended to the Yosys `synth_ice40` command
- `nextpnr_opts`: switches added to the nextpnr invocation (e.g., placer/router selection)
- `seed`: integer seed for nextpnr

Example (from repo):
```yaml
variants:
  - name: resource4
    params: { ROUND: 1, SAT: 1, PIPELINE: 0, TAPS: 4 }
    yosys_opts: "-abc9 -relut"
    nextpnr_opts: "--placer heap --router router2"
    seed: 1
```

## Tips

- Re‑running a variant simply overwrites its build directory files.
- If nextpnr or yosys are missing, see troubleshooting: [docs/troubleshooting.md](docs/troubleshooting.md).
- To analyze a single build directory post‑hoc, run:
  ```bash
  python scripts/parse_nextpnr_report.py build/<variant>
  ```

## Related documentation

- Simulation and coverage: [docs/simulation.md](docs/simulation.md)
- Build layout and CI: [docs/build.md](docs/build.md)
- Hardware spec and parameters: [docs/hw_spec.md](docs/hw_spec.md)