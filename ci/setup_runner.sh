#!/usr/bin/env bash
# Idempotent setup for Ubuntu 22.04 self-hosted runner
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run as root (sudo)."
  exit 1
fi

apt-get update
apt-get install -y --no-install-recommends \
  git make build-essential ca-certificates pkg-config \
  python3 python3-pip python3-venv \
  yosys nextpnr-ice40 icestorm icetime \
  verilator iverilog \
  symbiyosys boolector

python3 -m pip install --upgrade pip
if [[ -f "requirements.txt" ]]; then
  pip3 install -r requirements.txt
fi

echo "[setup_runner] Toolchain and Python deps installed."
