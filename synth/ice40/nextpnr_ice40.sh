#!/usr/bin/env bash
# nextpnr place-and-route for iCEBreaker (iCE40UP5K-SG48)
# Inputs (via env or defaults):
#   TOP=fir8_top
#   JSON=build/${TOP}.json
#   ASC=build/${TOP}.asc
#   PCF=constraints/icebreaker.pcf
#   PACKAGE=sg48
#   FREQ=12 (MHz)
#   NEXTPNR_OPTS="" (extra flags appended, e.g. "--placer heap --router router2")
#   SEED unset (if set, appended as --seed ${SEED})
# Outputs (in LOGDIR="$(dirname "$ASC")"):
#   - nextpnr.log
#   - icetime.log
# Notes:
#   - Base target for CI timing checks is 12 MHz (83.333 ns period)
set -euo pipefail

TOP=${TOP:-fir8_top}
JSON=${JSON:-build/${TOP}.json}
ASC=${ASC:-build/${TOP}.asc}
PCF=${PCF:-constraints/icebreaker.pcf}
PACKAGE=${PACKAGE:-sg48}   # iCEBreaker uses SG48
DEVICE_FLAG=--up5k         # iCE40UP5K
FREQ=${FREQ:-12}           # MHz target check (Phase 1: 12 MHz XO)
NEXTPNR_OPTS=${NEXTPNR_OPTS:-}
SEED=${SEED:-}

# Ensure output directory exists based on ASC path
LOGDIR="$(dirname "${ASC}")"
mkdir -p "${LOGDIR}"

echo "[nextpnr] Running place-and-route for ${TOP} ..."
CMD=(nextpnr-ice40
  ${DEVICE_FLAG}
  --package "${PACKAGE}"
  --pcf "${PCF}"
  --json "${JSON}"
  --asc "${ASC}"
  --freq "${FREQ}"
  --placer heap
  --router router2
)

# Append optional flags
if [[ -n "${NEXTPNR_OPTS}" ]]; then
  # shellcheck disable=SC2206
  EXTRA=(${NEXTPNR_OPTS})
  CMD+=("${EXTRA[@]}")
fi
if [[ -n "${SEED}" ]]; then
  CMD+=(--seed "${SEED}")
fi

echo "[nextpnr] ${CMD[*]}"
"${CMD[@]}" 2>&1 | tee "${LOGDIR}/nextpnr.log"

# Optional icetime timing estimate (static analysis)
# Note: icetime supports -d up5k and -P sg48 for iCEBreaker
echo "[icetime] Static timing estimate ..."
icetime -d up5k -P "${PACKAGE}" -p "${PCF}" "${ASC}" 2>&1 | tee "${LOGDIR}/icetime.log"

echo "[nextpnr] Done. ASC written to ${ASC}"