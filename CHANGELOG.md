# Changelog

All notable changes to this project will be documented in this file.

## 2025-09-29 — Phase 1 Completion

Phase 1 completes end-to-end parameterization, testing, CI, and reporting. Hardware programming steps and Phase 1.5 streaming I/O are intentionally excluded.

Deliverables:

- Parameterized RTL
  - Generic moving-average FIR with parameters TAPS ∈ {4, 8, 16, 32}, PIPELINE ∈ {0, 1}, ROUND ∈ {0, 1}, SAT ∈ {0, 1}.
  - Power-of-two and range checks at elaboration; safe `$error` usage.
  - Baseline latency is 1 cycle after window fill; optional +1 cycle when PIPELINE=1.
  - Rounding to nearest via bias ±(1<<(SHIFT-1)); saturation to Q1.15 when enabled.
  - Inline header documentation describing parameters, timing, and 12 MHz target.
  - Files:
    - [src/rtl/fir8.v](src/rtl/fir8.v)
    - [src/rtl/fir8_top.v](src/rtl/fir8_top.v)

- Top-level (iCEBreaker)
  - Synchronous POR, heartbeat divider.
  - 16-bit Fibonacci LFSR stimulus; observable LED path: heartbeat XOR FIR MSB.
  - Parameter forwarding for TAPS/PIPELINE; keep attributes applied to stimulus nets.
  - Files:
    - [src/rtl/fir8_top.v](src/rtl/fir8_top.v)
    - [constraints/icebreaker.pcf](constraints/icebreaker.pcf)

- Golden model (Python)
  - Generic Q1.15 moving-average model matching RTL rounding/saturation.
  - Impulse response helper.
  - Files:
    - [sim/golden/fir_model.py](sim/golden/fir_model.py)

- Cocotb tests and coverage
  - Stimuli: impulse, step, random, alternating-sign, ramp; length ≥ 4×TAPS.
  - Coverage with cocotb-coverage; exported YAML per run; threshold enforced ≥ 95%.
  - Environment-driven parameterization (ROUND, SAT, PIPELINE, TAPS).
  - Files:
    - [sim/cocotb/test_fir8.py](sim/cocotb/test_fir8.py)
    - [sim/cocotb/Makefile](sim/cocotb/Makefile)

- Variants grid and synthesis/PnR
  - Variants config with 5 named entries (baseline8, pipelined8, baseline16, baseline32, resource4).
  - Per-variant Yosys/nextpnr/icestorm flow with hooks (yosys_opts/nextpnr_opts/seed).
  - Parsed timing/utilization with slack vs 12 MHz target.
  - Aggregated CSV artifacts across all variants.
  - Files:
    - [configs/variants.yaml](configs/variants.yaml)
    - [agents/synth.py](agents/synth.py)
    - [synth/ice40/nextpnr_ice40.sh](synth/ice40/nextpnr_ice40.sh)
    - [scripts/parse_nextpnr_report.py](scripts/parse_nextpnr_report.py)

- Reporting and docs
  - Aggregation to artifacts/variants_summary.csv and a Markdown Phase 1 report.
  - Fixed-point and latency documentation including formula:
    - latency_cycles = (TAPS window fill) + 1 + PIPELINE.
  - Files:
    - [scripts/mk_phase1_report.py](scripts/mk_phase1_report.py)
    - [docs/fixed_point.md](docs/fixed_point.md)
    - [README.md](README.md)
    - [LICENSE](LICENSE)

- Formal (non-blocking in CI)
  - Parameterized wrapper and SBY config (BMC depth=20, boolector).
  - Files:
    - [formal/fir8_formal.v](formal/fir8_formal.v)
    - [formal/fir8.sby](formal/fir8.sby)

- CI
  - Simulation matrix (5 variants) with cocotb (Verilator) and coverage artifacts.
  - Formal job continue-on-error.
  - Per-variant synth/PnR on push to main, artifacts uploaded per variant.
  - Aggregate job merges CSVs and generates Phase 1 report.
  - Files:
    - [.github/workflows/ci.yml](.github/workflows/ci.yml)

- Tooling and scripts
  - Local dry-run helper that runs selected cocotb tests, builds all variants, and prints slack summary.
  - Pinned Python requirements for reproducibility.
  - Files:
    - [scripts/local_dry_run.sh](scripts/local_dry_run.sh)
    - [requirements.txt](requirements.txt)

Notes:
- All scripts perform parameter validation and fail with clear error messages on problems.
- No Phase 1.5 hardware programming steps are included.