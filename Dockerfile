# Reproducible toolchain container for iCEBreaker iCE40UP5K Phase 1
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    git make build-essential ca-certificates pkg-config \
    python3 python3-pip python3-venv \
    yosys nextpnr-ice40 icestorm icetime \
    verilator iverilog \
    symbiyosys boolector \
  && rm -rf /var/lib/apt/lists/*

# Copy repo (or bind mount at runtime)
WORKDIR /workspace
COPY . /workspace

# Python deps for sim/analysis
RUN python3 -m pip install --upgrade pip && \
    pip3 install -r requirements.txt

# Usage (examples):
#   - Simulation (Verilator):   make -C sim/cocotb SIM=verilator
#   - Synthesis/PnR (variants): python3 agents/synth.py
#   - Formal (non-blocking):    make formal
#   - Reports:                  python3 scripts/mk_phase1_report.py
