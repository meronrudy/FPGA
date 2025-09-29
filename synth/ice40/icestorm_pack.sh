#!/usr/bin/env bash
# icepack: Convert nextpnr ASC to BIN for iCE40 devices (iCEBreaker)
# Inputs:
#   - build/fir8_top.asc
# Outputs:
#   - build/fir8_top.bin
set -euo pipefail

TOP=${TOP:-fir8_top}
ASC=${ASC:-build/${TOP}.asc}
BIN=${BIN:-build/${TOP}.bin}

mkdir -p build

if [[ ! -f "${ASC}" ]]; then
  echo "[icepack] ERROR: ASC not found at ${ASC}"
  exit 1
fi

echo "[icepack] Packing ${ASC} -> ${BIN}"
icepack "${ASC}" "${BIN}"
echo "[icepack] Done. BIN written to ${BIN}"