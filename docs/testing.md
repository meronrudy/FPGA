# Testing Methodology

This document describes the verification approach for the parameterized Q1.15 moving‑average FIR, including stimulus strategies, golden model alignment, coverage, and optional formal checks.

Primary assets:
- Golden model: [sim/golden/fir_model.py](sim/golden/fir_model.py)
- cocotb testbench: [sim/cocotb/test_fir8.py](sim/cocotb/test_fir8.py)
- Makefile (sim harness): [sim/cocotb/Makefile](sim/cocotb/Makefile)
- Optional formal: [formal/fir8_formal.v](formal/fir8_formal.v), [formal/fir8.sby](formal/fir8.sby)

## Goals

- Validate correctness across parameterizations TAPS ∈ {4,8,16,32}, PIPELINE ∈ {0,1}, and rounding/saturation modes.
- Exercise edge cases (extremes, rounding boundaries, gaps in valid) and typical inputs (impulse, step, random, alternation, ramps).
- Enforce a coverage threshold (≥ 95%) for configurable bins per run.

## Golden model alignment

The testbench uses the Python golden model [sim/golden/fir_model.py](sim/golden/fir_model.py) to compute expected results with matching semantics:
- Average: `(sum + bias) >>> SHIFT`, where `SHIFT = log2(TAPS)`
- Rounding: symmetric round‑to‑nearest when enabled (`do_round=True`)
- Saturation: clamp to Q1.15; otherwise wrap to 16‑bit

Latency handling:
- The golden model outputs become valid once the window fills (index i ≥ TAPS−1).
- The DUT adds a fixed latency of `1 + PIPELINE` cycles after the window is full.
- The testbench offsets the expected sequence by this latency before comparison.

Relevant source:
- Test harness logic and scoreboard: [sim/cocotb/test_fir8.py](sim/cocotb/test_fir8.py)

## Stimulus strategy

The testbench runs multiple stimulus families to probe the filter’s behavior:
- impulse: single maximum amplitude sample followed by zeros
- step: constant level input to probe steady state
- random: wide distribution across Q1.15 range
- alt: alternating extremes (+32767, −32768) to stress rounding near zero
- ramp: symmetric ramp to exercise linearity around boundaries
- edge: curated extremes to exercise saturation/wrap and rounding transitions
- valid_gap: optional gap/burst behavior when an `in_valid` alias exists

Handshake:
- The core keeps `ready_in = 1`. The testbench drives `valid_in` per cycle (or `in_valid` if available).
- The scoreboarding compares values only when `valid_out` is asserted, using the latency‑aligned expected stream.

## Parameterization in tests

The testbench and simulator read environment variables (numeric):
- `TAPS` ∈ {4,8,16,32}
- `PIPELINE` ∈ {0,1}
- `ROUND` ∈ {0,1} (1=round, 0=truncate)
- `SAT` ∈ {0,1} (1=saturate, 0=wrap)

These are set by the cocotb Makefile defaults or via the simulation agent:
- Makefile: [sim/cocotb/Makefile](sim/cocotb/Makefile)
- Agent: [agents/sim.py](agents/sim.py)

Examples:
```bash
# Agent-driven (Verilator), TOPLEVEL=fir8 to match Makefile
python agents/sim.py --sim verilator --top fir8 --taps 8 --pipeline 0

# Direct Makefile invocation (Icarus, 16-tap pipelined)
make -C sim/cocotb SIM=icarus TAPS=16 PIPELINE=1 ROUND=1 SAT=1
```

## Coverage

The testbench uses `cocotb-coverage` with per-run bins for the active parameterization and stimulus types. At the end of the test sequence:
- Coverage is exported to:
  - `build/coverage_{TAPS}_{PIPELINE}_{ROUND}_{SAT}.yml`
- A coverage threshold is enforced:
  - Test will assert coverage ≥ 95%

Source:
- Coverage collection and export: [sim/cocotb/test_fir8.py](sim/cocotb/test_fir8.py)

Interpreting artifacts:
- The YAML shows bin/cross coverage for the executed stimuli and current parameters.
- Low coverage suggests missing test paths; re-run with more stimuli or additional seeds if needed.

## Edge-case and stress testing

Focus areas:
- Rounding boundaries near zero (alternating sign sequences)
- Saturation clamping when accumulations approach Q1.15 limits
- Wrap behavior when `SAT=0`
- Pipeline latency effects on valid alignment
- Valid gaps (when an `in_valid` alias is present) to ensure event ordering remains correct

Expectations:
- No mismatches are allowed; failures log detailed per-index errors.

## Formal overview (optional)

If applicable in your environment, the repository includes basic formal collateral:
- Harness: [formal/fir8_formal.v](formal/fir8_formal.v)
- Task: [formal/fir8.sby](formal/fir8.sby)

Usage (non-blocking in CI as provided in README):
```bash
make formal
```

Formal properties can complement simulation by proving invariants (e.g., no overflow beyond Q1.15 range when `SAT=1`, latency/valid relationships), but are out-of-scope for this testing guide. Refer to your formal tool setup to extend the harness.

## Pre-PR testing checklist

Before submitting changes:
- Run the quick import/CLI smoke: [scripts/check_imports.py](scripts/check_imports.py)
  ```bash
  python scripts/check_imports.py
  ```
- Run a representative simulation:
  ```bash
  python agents/sim.py --sim verilator --top fir8 --taps 8 --pipeline 0
  ```
- Optionally run additional parameterizations and review coverage YAML.
- For synthesis-impacting RTL changes, run a narrow synth pass to ensure reports parse:
  ```bash
  python agents/synth.py --only baseline8
  ```

## Troubleshooting

- Simulation exits non-zero:
  - Review cocotb logs; enable verbose logging:
    ```bash
    LOG_LEVEL=DEBUG python agents/sim.py --sim verilator --top fir8 --taps 8
    ```
  - Check that `SIM` matches an installed simulator (Verilator/Icarus).
- Coverage below threshold:
  - Ensure all tests executed and the run length (`_len_for_tests`) is sufficient.
  - Try different parameterizations or seeds.
- Environment mismatches:
  - Keep `TOPLEVEL=fir8` in alignment with the Makefile unless you update it.

Related documentation:
- Simulation usage: [docs/simulation.md](docs/simulation.md)
- Hardware behavior/spec: [docs/hw_spec.md](docs/hw_spec.md)