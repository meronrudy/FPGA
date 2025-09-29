# Troubleshooting

This guide lists common issues across simulation, synthesis/PnR, configuration, and reporting for the parameterized Q1.15 moving‑average FIR project, with concrete diagnostics and fixes.

Useful entry points:
- Import/CLI smoke: [scripts/check_imports.py](scripts/check_imports.py)
- Simulation agent: [agents/sim.py](agents/sim.py)
- Synthesis agent: [agents/synth.py](agents/synth.py)
- Report parser: [scripts/parse_nextpnr_report.py](scripts/parse_nextpnr_report.py)
- Report generator: [scripts/mk_phase1_report.py](scripts/mk_phase1_report.py)
- Constraints: [constraints/icebreaker.pcf](constraints/icebreaker.pcf)
- DUT and top RTL: [src/rtl/fir8.v](src/rtl/fir8.v), [src/rtl/fir8_top.v](src/rtl/fir8_top.v)

General tip:
- Increase verbosity to see detailed context:
  ```bash
  LOG_LEVEL=DEBUG python agents/sim.py --sim verilator --top fir8 --taps 8
  LOG_LEVEL=DEBUG python agents/synth.py --only baseline8
  ```

## Quick diagnostics checklist

1) Verify Python and dependencies
```bash
python --version
python -m pip install --upgrade pip
pip install -r requirements.txt
```

2) Verify EDA toolchains are on PATH
```bash
yosys -V
nextpnr-ice40 --version
icepack -h
verilator --version   # if using Verilator
iverilog -V           # if using Icarus
```

3) Run the smoke check
```bash
python scripts/check_imports.py
```

4) Confirm files exist where tools expect them
- Makefile for cocotb: [sim/cocotb/Makefile](sim/cocotb/Makefile)
- Variants YAML for synthesis: [configs/variants.yaml](configs/variants.yaml)

---

## Missing toolchains

Symptoms:
- “command not found” or version queries fail for `yosys`, `nextpnr-ice40`, `icepack`, `verilator`, or `iverilog`.

Resolution:
- Install the missing tools and ensure they are on PATH.
- After installation, confirm versions:
  ```bash
  yosys -V && nextpnr-ice40 --version && icepack -h
  verilator --version || iverilog -V
  ```

Notes:
- You can switch simulators by changing `--sim` for the agent or `SIM` for the Makefile (see [sim/cocotb/Makefile](sim/cocotb/Makefile)).

---

## YAML parse/validation errors

Common messages:
- “YAML parse error” (syntax)
- “Configuration validation error” (flat schema)
- “variants.yaml schema invalid … expected {'variants': [ … ]}” (synthesis schema)
- “Variant not found: NAME”

Causes and fixes:
- Mixing schemas:
  - Synthesis uses uppercase numeric `params` under each variant (see [configs/variants.yaml](configs/variants.yaml) and [agents/synth.py](agents/synth.py)).
  - The simulation agent `--variant` and the designer expect a flat schema (semantic strings for `round` and `sat`) validated by [common/config.py](common/config.py).
  - Fix by using explicit CLI overrides for sim (recommended), or maintain a separate flat YAML.
- Syntax problems:
  - Validate YAML with a linter or correct indentation/maps.
- Unknown variant:
  - Ensure the name matches an entry in the active YAML.
  - For synthesis: `--only` names must exist exactly as authored.

Diagnostics:
```bash
# For synthesis schema issues
LOG_LEVEL=DEBUG python agents/synth.py --only baseline8

# For flat schema (designer/sim --variant)
python -m agents.designer --input your_flat.yaml --output artifacts/variants.json -vv
```

---

## Simulation failures

Entry: [agents/sim.py](agents/sim.py)

Exit codes:
- 0 success
- 2 file not found (Makefile) or YAML parse error
- 3 validation/config error (bad params or variant)
- 4 subprocess failure (make returned non‑zero)
- 1 unexpected error

Common problems and fixes:
- “Makefile not found: sim/cocotb/Makefile”
  - Confirm path; pass `--makefile sim/cocotb/Makefile` if needed.
- TOPLEVEL mismatch
  - The Makefile sets `TOPLEVEL := fir8` (see [sim/cocotb/Makefile](sim/cocotb/Makefile)).
  - Keep `--top fir8` for the agent to align with the Makefile default.
- Simulator not installed / mis‑set
  - Try switching simulators:
    ```bash
    python agents/sim.py --sim icarus --top fir8 --taps 8
    ```
- Parameter type issues
  - For the agent’s explicit flags:
    - `--taps` (int), `--pipeline` (int ≥ 0)
    - `--round {round,truncate}`, `--sat {saturate,wrap}`
  - For the Makefile:
    - numeric environment variables: `TAPS/PIPELINE/ROUND/SAT`
- Coverage threshold failures
  - Review cocotb logs; ensure all tests ran.
  - Increase sequence length or try different parameterizations.

Direct Make examples:
```bash
make -C sim/cocotb SIM=verilator TAPS=8 PIPELINE=0 ROUND=1 SAT=1
make -C sim/cocotb SIM=icarus    TAPS=16 PIPELINE=1 ROUND=1 SAT=1
```

---

## Synthesis/PnR failures

Entry: [agents/synth.py](agents/synth.py)

Common problems and fixes:
- Unknown variant in `--only`
  - Ensure names exist in [configs/variants.yaml](configs/variants.yaml).
- Schema/type issues in variants
  - The agent requires uppercase numeric keys in the nested `params` map.
- nextpnr/icepack errors
  - Confirm versions and PATH; re-run with `LOG_LEVEL=DEBUG` to capture the failing command line.
- Missing logs or outputs
  - If `build/<variant>/nextpnr.log` or other expected files are missing, check the prior Yosys step and the wrapper scripts:
    - [synth/ice40/nextpnr_ice40.sh](synth/ice40/nextpnr_ice40.sh)
    - [synth/ice40/icestorm_pack.sh](synth/ice40/icestorm_pack.sh)

Re-run parsing manually for a single build:
```bash
python scripts/parse_nextpnr_report.py build/<variant>
```

---

## Report parsing failures

Entry: [scripts/parse_nextpnr_report.py](scripts/parse_nextpnr_report.py)

Symptoms:
- “[error] missing expected file: …/nextpnr.log”
- “[error] failed to parse JSON …/yosys_stat.json”
- Exit code 2

Fixes:
- Ensure the synthesis step completed and produced the expected files.
- Check that `summary.csv` is writable under `build/<variant>/`.
- Re-run with explicit input:
  ```bash
  python scripts/parse_nextpnr_report.py -i build/<variant>
  ```

---

## Phase report generation issues

Entry: [scripts/mk_phase1_report.py](scripts/mk_phase1_report.py)

Symptoms:
- “Missing summary CSV” or resource sanity failures (exit 3)

Fixes:
- Regenerate/aggregate variant summaries:
  ```bash
  python agents/synth.py --only baseline8,pipelined8
  python scripts/mk_phase1_report.py
  ```
- If resource totals exceed device limits, verify that constraints and target device assumptions are correct.

---

## Formal flow issues (optional)

Targets: [formal/fir8_formal.v](formal/fir8_formal.v), [formal/fir8.sby](formal/fir8.sby)

Symptoms:
- `sby` not found or solver missing

Fixes:
- Install SymbiYosys (`sby`) and a solver (e.g., Boolector).
- Run:
  ```bash
  make formal
  ```

---

## CI‑specific issues

- Badge or artifact links
  - Ensure the workflow file exists at [.github/workflows/ci.yml](.github/workflows/ci.yml) and the badge URL in README matches your repo.
- Cocotb import warnings (optional tests import)
  - [scripts/check_imports.py](scripts/check_imports.py) doesn’t fail CI on optional cocotb test module import; messages are informational.

---

## When to open an issue

Include:
- Command invoked and full output with `LOG_LEVEL=DEBUG`
- OS, Python, and tool versions (`yosys -V`, `nextpnr-ice40 --version`, simulator version)
- Variant name(s) and relevant snippets from [configs/variants.yaml](configs/variants.yaml)
- Any produced logs: `build/<variant>/nextpnr.log`, `build/<variant>/yosys_stat.json`, `build/<variant>/summary.csv`