#!/usr/bin/env bash
# Local Phase 1 dry-run:
#  1) Run three cocotb variants locally:
#     - baseline8     (TAPS=8,  PIPELINE=0, ROUND=1, SAT=1)
#     - round_no_sat  (TAPS=8,  PIPELINE=0, ROUND=1, SAT=0)
#     - pipelined8    (TAPS=8,  PIPELINE=1, ROUND=1, SAT=1)
#  2) Build all configured variants via agents/synth.py
#  3) Print artifact locations and slack summary table
#
# Requirements:
#  - Verilator or Icarus, Yosys, nextpnr-ice40, icestorm, icetime
#  - Python deps from requirements.txt
#
# Usage:
#  ./scripts/local_dry_run.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SIM_DIR="${ROOT_DIR}/sim/cocotb"
BUILD_DIR="${ROOT_DIR}/build"
ART_DIR="${ROOT_DIR}/artifacts"

# Colors
RED="$(printf '\033[31m')"
GRN="$(printf '\033[32m')"
YEL="$(printf '\033[33m')"
BLU="$(printf '\033[34m')"
RST="$(printf '\033[0m')"

log() { echo -e "${BLU}[*]${RST} $*"; }
ok()  { echo -e "${GRN}[OK]${RST} $*"; }
err() { echo -e "${RED}[ERR]${RST} $*"; }

check_cmd() {
  command -v "$1" >/dev/null 2>&1 || { err "Missing command: $1"; exit 2; }
}

run_cocotb() {
  local name="$1" taps="$2" pipeline="$3" round="$4" sat="$5"
  log "Cocotb: ${name} (TAPS=${taps} PIPELINE=${pipeline} ROUND=${round} SAT=${sat})"
  ( ROUND="${round}" SAT="${sat}" PIPELINE="${pipeline}" TAPS="${taps}" SIM=verilator \
    make -C "${SIM_DIR}" SIM=verilator )
  local cov="${BUILD_DIR}/coverage_${taps}_${pipeline}_${round}_${sat}.yml"
  if [[ -f "${cov}" ]]; then
    ok "Coverage written: ${cov}"
  else
    err "Coverage YAML not found: ${cov}"
  fi
}

slack_summary() {
  local csv="${ART_DIR}/variants_summary.csv"
  if [[ ! -f "${csv}" ]]; then
    err "Summary CSV not found: ${csv}"
    return 1
  fi
  echo
  echo "Slack summary @12 MHz (ns):"
  echo "variant, Slack_ns_12MHz, Meets_12MHz"
  # Fields (1-based):
  # 1=variant, 8=Slack_ns_12MHz, 9=Meets_12MHz
  tail -n +2 "${csv}" | cut -d, -f1,8,9
}

main() {
  log "Repo root: ${ROOT_DIR}"

  # Tool checks
  check_cmd python3
  check_cmd make

  # Optional: prefer Verilator; fall back to Icarus if verilator missing
  if ! command -v verilator >/dev/null 2>&1; then
    log "Verilator not found; attempting Icarus for sim"
    export SIM=icarus
  fi

  # 1) Cocotb runs
  run_cocotb "baseline8"    8 0 1 1
  run_cocotb "round_no_sat" 8 0 1 0
  run_cocotb "pipelined8"   8 1 1 1

  # 2) Synthesis/PnR (all configured variants)
  log "Running agents/synth.py for all variants..."
  python3 "${ROOT_DIR}/agents/synth.py"

  # 3) Aggregate report (ensure we have summaries and markdown)
  log "Generating Phase 1 report..."
  python3 "${ROOT_DIR}/scripts/mk_phase1_report.py"

  echo
  ok "Artifacts directory: ${ART_DIR}"
  if [[ -f "${ART_DIR}/variants_summary.csv" ]]; then
    ok "Summary CSV: ${ART_DIR}/variants_summary.csv"
  fi
  if [[ -f "${ART_DIR}/report_phase1.md" ]]; then
    ok "Markdown report: ${ART_DIR}/report_phase1.md"
  fi

  # Print slack summary
  slack_summary || true
  echo
  ok "Local dry-run completed."
}

main "$@"