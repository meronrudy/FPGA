# Self-hosted Runner Setup (Ubuntu 22.04)

This repository includes a helper to provision required FPGA and formal tools.

## One-time setup

1. Provision Ubuntu 22.04 VM or machine.
2. Clone this repository into the runner working directory.
3. Run the setup script as root:

```bash
sudo ci/setup_runner.sh
```

This installs:
- yosys, nextpnr-ice40, icestorm (inc. icetime)
- verilator, iverilog
- symbiyosys, boolector
- Python 3 + pip and the repo `requirements.txt` packages

## CI jobs overview

- Simulation: cocotb + Verilator with parameter matrix (ROUND/SAT).
- Synthesis: per-variant build under `build/<variant>/`, logs per variant, aggregate CSV at `artifacts/variants_summary.csv`.
- Formal (non-blocking): SymbiYosys BMC depth 20.
- Reporting: `scripts/mk_phase1_report.py` writes `artifacts/report_phase1.md`.

Ensure the runner has sufficient disk space and network access to apt repositories.
