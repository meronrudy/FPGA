# cocotb Integration

This document explains how the Makefile‑driven cocotb flow is wired for the FIR project, how the simulation agent hands environment settings to the Makefile, and how to switch simulators reliably.

Primary components:
- Testbench: [sim/cocotb/test_fir8.py](sim/cocotb/test_fir8.py)
- Makefile: [sim/cocotb/Makefile](sim/cocotb/Makefile)
- Core DUT (sim): [src/rtl/fir8.v](src/rtl/fir8.v)
- Driver agent: [agents/sim.py](agents/sim.py)

## Variables and handoff

Makefile defaults (see [sim/cocotb/Makefile](sim/cocotb/Makefile)):
- TOPLEVEL_LANG := verilog
- SIM := verilator
- MODULE := test_fir8
- TOPLEVEL := fir8
- Parameters (numeric): `ROUND?=1`, `SAT?=1`, `PIPELINE?=0`, `TAPS?=8`

Agent → Makefile environment mapping (see [agents/sim.py](agents/sim.py)):
- MODULE → MODULE
- TOPLEVEL → TOPLEVEL (keep `fir8` to match the Makefile)
- SIM → SIM (`verilator` or `icarus`)
- TAPS, PIPELINE, ROUND, SAT → used both by the simulator parameterization and by the Python testbench

The agent runs:
```text
make -f sim/cocotb/Makefile
```
with the above environment populated. You can pass `--makefile` to point elsewhere if needed.

## Parameter passing to simulators

The Makefile translates parameters to each simulator’s flags:

- Verilator (default SIM):
  - Adds `--trace`
  - Passes parameters with `-G` flags:
    - `-GROUND=$(ROUND) -GSAT=$(SAT) -GPIPELINE=$(PIPELINE) -GTAPS=$(TAPS)`
- Icarus (SIM=icarus):
  - Passes parameters with `-P` flags:
    - `-Pfir8.ROUND=$(ROUND) -Pfir8.SAT=$(SAT) -Pfir8.PIPELINE=$(PIPELINE) -Pfir8.TAPS=$(TAPS)`

These map to `parameter integer` declarations in [src/rtl/fir8.v](src/rtl/fir8.v). Ensure numeric values are used for these environment variables.

## Running with the agent

Help:
```bash
python agents/sim.py --help
```

Typical runs (keep `--top fir8` to match the Makefile):
```bash
# Verilator, default parameters
python agents/sim.py --sim verilator --top fir8 --taps 8 --pipeline 0

# Icarus, 16-tap, pipelined
python agents/sim.py --sim icarus --top fir8 --taps 16 --pipeline 1
```

Explicit rounding/saturation with the agent:
```bash
# Round + saturate
python agents/sim.py --top fir8 --taps 8 --pipeline 0 --round round --sat saturate

# Truncate + wrap
python agents/sim.py --top fir8 --taps 8 --pipeline 0 --round truncate --sat wrap
```

Note on `--variant`:
- The agent’s `--variant` attempts to read a flat‑schema YAML via [common/config.py](common/config.py), which is not the same schema as the synthesis‑oriented [configs/variants.yaml](configs/variants.yaml). Prefer explicit flags for this repository or supply a separate flat YAML.

## Direct Makefile invocation

You can bypass the agent and call Make directly:
```bash
# Defaults: SIM=verilator, TOPLEVEL=fir8, MODULE=test_fir8
make -C sim/cocotb

# Switch simulator
make -C sim/cocotb SIM=icarus

# Change parameters (numeric)
make -C sim/cocotb SIM=verilator TAPS=32 PIPELINE=1 ROUND=1 SAT=1
```

The Makefile exports `PYTHONPATH` to the repo root so that the testbench can import the golden model [sim/golden/fir_model.py](sim/golden/fir_model.py).

## Testbench behavior and environment

Testbench: [sim/cocotb/test_fir8.py](sim/cocotb/test_fir8.py)
- Reads `TAPS`, `PIPELINE`, `ROUND`, `SAT` from the environment
- Computes expected outputs via the golden model [sim/golden/fir_model.py](sim/golden/fir_model.py)
- Applies DUT latency offset of `(1 + PIPELINE)` cycles
- Exports coverage to:
  - `build/coverage_{TAPS}_{PIPELINE}_{ROUND}_{SAT}.yml`
- Handles optional `in_valid` alias if such a signal exists in other environments; primary handshake remains `valid_in`/`ready_in`/`valid_out`

## Switching simulators and environment nuances

- Verilator:
  - Typically faster, with waveform tracing enabled by `--trace`
  - Ensure `verilator` is on PATH; install from your package manager
- Icarus:
  - Lightweight alternative; ensure `iverilog` is on PATH

Common issues and tips:
- TOPLEVEL mismatch:
  - The Makefile sets `TOPLEVEL := fir8`; keep `--top fir8` with the agent to stay aligned.
- Parameter types:
  - For the Makefile, use numeric env vars (`ROUND=0|1`, `SAT=0|1`, etc.).
  - For the agent, `--round {round,truncate}`, `--sat {saturate,wrap}` are strings; the agent converts to env vars consumed by tests.
- Import errors:
  - Ensure the repo root is on `PYTHONPATH` (the Makefile sets this for cocotb).
- Debug logs:
  - Increase verbosity with `LOG_LEVEL=DEBUG`, e.g.:
    ```bash
    LOG_LEVEL=DEBUG python agents/sim.py --sim verilator --top fir8 --taps 8
    ```

## Related documentation

- Simulation guide: [docs/simulation.md](docs/simulation.md)
- Hardware spec and latency: [docs/hw_spec.md](docs/hw_spec.md)
- Troubleshooting: [docs/troubleshooting.md](docs/troubleshooting.md)