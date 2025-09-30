#!/usr/bin/env bash
# Minimal local end-to-end dry run (software-only) with optional acceptance checks.
# Usage:
#   scripts/local_dry_run.sh [variant]
# Env:
#   SIM=verilator|icarus (default: verilator)
#   ACCEPTANCE=1 to run acceptance checks (Slack ping, artifact asserts)
#   SLACK_WEBHOOK_URL for Slack check (optional)

set -euo pipefail

usage() {
  cat <<'EOF'
local_dry_run.sh - run software-only pipeline locally

Usage:
  scripts/local_dry_run.sh [variant]

Environment:
  SIM                Cocotb simulator (default: verilator)
  ACCEPTANCE=1       Enable acceptance checks (Slack ping, artifact asserts)
  SLACK_WEBHOOK_URL  Webhook for Slack acceptance ping (optional)

Steps:
  1) Designer validate config
  2) Simulation via cocotb (Make)
  3) Synthesis/PnR (bitstream + summary)
  4) Report generation (includes hardware section if artifacts exist)

Examples:
  scripts/local_dry_run.sh baseline8
  SIM=icarus scripts/local_dry_run.sh baseline16
  ACCEPTANCE=1 scripts/local_dry_run.sh baseline8
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
cd "$REPO_DIR"

VARIANT="${1:-baseline8}"
SIM="${SIM:-verilator}"

echo "[dry-run] Repo: ${REPO_DIR}"
echo "[dry-run] Variant: ${VARIANT}"
echo "[dry-run] Simulator: ${SIM}"

# 1) Designer (non-fatal if skipped downstream)
echo "[dry-run] Designer validation"
python -m agents.designer || true

# 2) Simulation
echo "[dry-run] Simulation (cocotb)"
python -m agents.sim --variant "${VARIANT}" --sim "${SIM}"

# 3) Synthesis/PnR
echo "[dry-run] Synthesis/PnR"
python agents/synth.py --only "${VARIANT}"

# 4) Report
echo "[dry-run] Analysis/report"
python -m agents.analysis

echo "[dry-run] Completed software-only flow for variant '${VARIANT}'"

# Optional acceptance checks
if [[ "${ACCEPTANCE:-0}" == "1" ]]; then
  echo "[acceptance] Running acceptance checks"

  # Check key artifacts exist
  BIN="build/${VARIANT}/fir8_top.bin"
  REPORT="artifacts/report_phase1.md"
  SUMMARY="artifacts/variants_summary.csv"

  if [[ ! -f "${BIN}" ]]; then
    echo "[acceptance][FAIL] Missing bitstream: ${BIN}" >&2
    exit 1
  fi
  if [[ ! -f "${SUMMARY}" ]]; then
    echo "[acceptance][FAIL] Missing summary CSV: ${SUMMARY}" >&2
    exit 1
  fi
  if [[ ! -f "${REPORT}" ]]; then
    echo "[acceptance][FAIL] Missing report: ${REPORT}" >&2
    exit 1
  fi

  echo "[acceptance] Artifacts present ✅"

  # Slack ping (non-fatal if not configured)
  if [[ -n "${SLACK_WEBHOOK_URL:-}" ]]; then
    echo "[acceptance] Slack notification ping"
    python -m common.notify --status info --variant "${VARIANT}" --message "Acceptance ping from local_dry_run.sh"
  else
    echo "[acceptance] SLACK_WEBHOOK_URL not set; skipping Slack ping"
  fi

  echo "[acceptance] Completed ✅"
fi

echo "[dry-run] Done."