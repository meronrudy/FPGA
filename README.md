
## CrewAI orchestrator and safety gates

This repo includes an orchestration layer compatible with CrewAI that coordinates the agents and enforces safety gates:
- Orchestrator (CrewAI‑compatible, local fallback): [orchestrator/crew.py](orchestrator/crew.py)
- Agents:
  - Designer (config validation/normalization): [agents/designer.py](agents/designer.py)
  - Simulation (cocotb): [agents/sim.py](agents/sim.py)
  - Synthesis/PnR (Yosys → nextpnr → icepack): [agents/synth.py](agents/synth.py)
  - Analysis (report generation): [agents/analysis.py](agents/analysis.py)
  - Board (optional hardware flash/smoke with locking): [agents/board.py](agents/board.py)

Promotion policy (“promote late”):
- A variant must pass simulation before synthesis runs.
- Hardware is never touched unless both simulation and synthesis succeed.
- The board agent uses a file‑based lock to ensure a single iCEBreaker is programmed at a time and enforces cooldown between flashes. Hardware CI is manual‑approval gated.

CrewAI usage:
- If the `crewai` library is installed (see [requirements.txt](requirements.txt)), the orchestrator initializes Crew/Agents; execution still uses robust subprocess boundaries.
- If `crewai` is not installed, the orchestrator runs in local mode automatically.
- Details and runbook: [docs/crewai.md](docs/crewai.md)

Virtual wind tunnel sketchpad:
- Blueprint for a tiered, parallel software gauntlet (lint/smoke, randomized sim, formal micro‑checks, and synth dry‑run) to prune designs before hardware. See [docs/windtunnel.md](docs/windtunnel.md).

## High‑level architecture

A stimulus stream feeds the FIR DUT, which produces filtered Q1.15 output. Parameterization controls window length, latency, rounding, and saturation behavior. For a deep dive and block diagram, see [docs/architecture.md](docs/architecture.md).

## Quick start

Prerequisites:
- Python 3.8+ (tools and linters configured for py38)
- Sim: Verilator or Icarus Verilog
- Synthesis/PnR: yosys, nextpnr-ice40, icestorm
- Optional: SymbiYosys (sby) + Boolector for formal
- Python deps: `pip install -r` [requirements.txt](requirements.txt)

Install Python requirements:
```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Smoke check (imports and CLI `--help`):
```bash
python scripts/check_imports.py
```
Tooling details: [scripts/check_imports.py](scripts/check_imports.py)

### Run simulation (cocotb)

Use the agent to launch the cocotb Makefile‑driven testbench:
```bash
python -m agents.sim --help
```

Example (Verilator) with safe defaults that match the repository Makefile:
```bash
# The cocotb Makefile defaults TOPLEVEL=fir8; pass matching --top to be explicit.
python -m agents.sim --sim verilator --top fir8 --taps 8 --pipeline 0
```

Notes:
- The testbench reads TAPS/PIPELINE/ROUND/SAT from the environment. The Makefile sets numeric defaults: `ROUND=1`, `SAT=1`, `PIPELINE=0`, `TAPS=8`. Prefer numeric values for these variables.
- The Makefile in [sim/cocotb/Makefile](sim/cocotb/Makefile) defines `TOPLEVEL := fir8`. If you pass a different `--top` via the agent, the Makefile’s setting will take precedence unless you edit it. Keep `--top fir8` to align with the current setup.
- For simulator choice, use `--sim verilator` or `--sim icarus`.

Simulation testbench and golden model:
- Testbench: [sim/cocotb/test_fir8.py](sim/cocotb/test_fir8.py)
- Golden model: [sim/golden/fir_model.py](sim/golden/fir_model.py)
- Makefile: [sim/cocotb/Makefile](sim/cocotb/Makefile)

More details: [docs/simulation.md](docs/simulation.md) and [docs/cocotb_integration.md](docs/cocotb_integration.md)

### Run synthesis / place & route

The synthesis agent drives yosys → nextpnr‑ice40 → icepack, one build directory per variant, and aggregates results.

Help:
```bash
python -m agents.synth --help
```

Build all configured variants:
```bash
python -m agents.synth
```

Build a subset:
```bash
python -m agents.synth --only baseline8,pipelined8
```

Artifacts per variant (under `build/<variant>/`):
- fir8_top.json, fir8_top.asc, fir8_top.bin
- nextpnr.log, icetime.log
- yosys_stat.json, summary.csv

Summaries:
- Per‑variant CSV: `build/<variant>/summary.csv` (produced by [scripts/parse_nextpnr_report.py](scripts/parse_nextpnr_report.py))
- Aggregated CSV: `artifacts/variants_summary.csv`

More details: [docs/synthesis.md](docs/synthesis.md) and [docs/build.md](docs/build.md)

### Generate Phase 1 report

Render a Markdown table from the aggregated CSV:
```bash
python scripts/mk_phase1_report.py --help
python scripts/mk_phase1_report.py
```
Outputs:
- `artifacts/report_phase1.md`
- `artifacts/variants_summary.csv`

The report includes a “Hardware smoke results” section when smoke artifacts exist (produced by the board agent). Report generator: [scripts/mk_phase1_report.py](scripts/mk_phase1_report.py)

### Orchestrated end‑to‑end runs (software‑only)

Run orchestrated pipeline locally without hardware:
```bash
python -m orchestrator.crew --variants baseline8
```

Local dry run convenience wrapper:
```bash
bash scripts/local_dry_run.sh baseline8
# Optional acceptance checks & Slack ping:
ACCEPTANCE=1 SLACK_WEBHOOK_URL=https://hooks.slack... bash scripts/local_dry_run.sh baseline8
```

Acceptance tests for gating logic:
```bash
pytest tests/acceptance/test_gates.py -q
```

## Configuration management (flat schema)

Design variants and flow options are defined in [configs/variants.yaml](configs/variants.yaml). The repository uses a flat schema compatible with [common/config.py](common/config.py):
- Required per variant:
  - name (str), taps (int), pipeline (int|bool), round (“round”|“truncate”), sat (“saturate”|“wrap”)
- Optional:
  - seed (int), yosys_opts (str), nextpnr_opts (str), freq (int MHz; defaults to 12)

Helpers:
- Designer agent (YAML → normalized JSON): [agents/designer.py](agents/designer.py)
- Config loader/validation: [common/config.py](common/config.py)
- Legacy nested→flat converter: [scripts/convert_variants_schema.py](scripts/convert_variants_schema.py)

How to author and validate configs: [docs/configuration.md](docs/configuration.md)

## Hardware lane (board agent)

The board agent performs an SRAM flash and basic smoke test, with safety features:
- Exclusive resource lock: [common/resources.py](common/resources.py)
- Cooldown between flashes
- Smoke record under `artifacts/hw/<variant>/<timestamp>/smoke.json`

Run directly:
```bash
python -m agents.board --variant baseline8 --cooldown 5
```

Or run orchestrator with hardware (requires iCEBreaker attached and `iceprog`):
```bash
python -m orchestrator.crew --variants baseline8 --with-hardware
```

In CI, hardware runs are gated with manual approval and Slack notifications. See [\.github/workflows/ci.yml](.github/workflows/ci.yml).

## Slack notifications

A minimal notifier is included; if `SLACK_WEBHOOK_URL` is not set, notifications are skipped (non‑fatal):
- Notifier: [common/notify.py](common/notify.py)
- Example:
```bash
python -m common.notify --status success --variant baseline8 --message "Hardware smoke passed"
```

## Logging

Centralized logging is initialized by agents and scripts. Control verbosity via the `LOG_LEVEL` environment variable or CLI verbosity flags where available.
- Logging utilities: [common/logging.py](common/logging.py)
- Details and policies: [docs/logging_config.md](docs/logging_config.md)

## Testing overview

- cocotb testbench exercises impulse/step/random/alternating/ramp/extremes, with optional handling for `in_valid` if present in some environments.
- Scoreboarding compares RTL against the Q1.15 golden model.
- Coverage is exported to YAML; tests enforce a coverage threshold.

Read more: [docs/simulation.md](docs/simulation.md), [docs/testing.md](docs/testing.md)

## Build / synthesis overview

- yosys script generation per variant, nextpnr for PnR, and icepack for bitstream.
- Parsed reports and CSV summaries, plus a consolidated artifacts table.

Flow details: [docs/synthesis.md](docs/synthesis.md), build system notes: [docs/build.md](docs/build.md)

## Static analysis and type checking

- Python: Ruff and Mypy configured for Python 3.8+
- Config: [pyproject.toml](pyproject.toml)

Instructions: [docs/static_analysis.md](docs/static_analysis.md)

## Troubleshooting

Common pitfalls (missing toolchains, YAML errors, sim failures, and report parsing) and diagnostic tips: [docs/troubleshooting.md](docs/troubleshooting.md)

## Contributing

Style, typing, docstrings, PR checks, and pre‑PR smoke steps are described in [docs/contributing.md](docs/contributing.md)

## Additional references

- CrewAI plan and runbook: [docs/crewai.md](docs/crewai.md)
- Virtual wind tunnel sketchpad: [docs/windtunnel.md](docs/windtunnel.md)
- Hardware architecture and ports: [docs/architecture.md](docs/architecture.md)
- Hardware specification: [docs/hw_spec.md](docs/hw_spec.md)
- Fixed‑point background: [docs/fixed_point.md](docs/fixed_point.md)
- FIR reference guide (Q1.15, rounding, saturation): [docs/reference_fir.md](docs/reference_fir.md)
- CLI reference for all agents and scripts: [docs/cli_reference.md](docs/cli_reference.md)

# Parameterized Q1.15 Moving‑Average FIR on iCE40UP5K

[CI badge — replace with your repository URL](.github/workflows/ci.yml)

This project implements a parameterized moving‑average FIR filter in fixed‑point Q1.15 for the Lattice iCE40UP5K (iCEBreaker). It includes RTL, cocotb simulation, synthesis/PnR (Yosys/nextpnr-ice40/Icestorm), optional formal checks, and scripts to aggregate timing/utilization reports.

Design parameters:
- TAPS: 4, 8, 16, 32 (power‑of‑two)
- PIPELINE: 0 or 1 (adds +1 output register when 1)
- ROUND: 0 or 1 (truncate vs symmetric round‑to‑nearest)
- SAT: 0 or 1 (wrap vs saturate to Q1.15)

Core RTL and top:
- Core: [src/rtl/fir8.v](src/rtl/fir8.v)
- iCEBreaker top: [src/rtl/fir8_top.v](src/rtl/fir8_top.v)
- Constraints: [constraints/icebreaker.pcf](constraints/icebreaker.pcf)

See fixed‑point background in [docs/fixed_point.md](docs/fixed_point.md).
