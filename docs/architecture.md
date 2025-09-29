# Architecture Overview

This project implements a parameterized moving-average FIR filter in Q1.15, targeted at the Lattice iCE40UP5K. The design supports configurable taps, an optional output pipeline, and selectable rounding and saturation behavior, with a consistent simulation and synthesis workflow.

Key RTL files:
- Core FIR: [src/rtl/fir8.v](src/rtl/fir8.v)
- iCEBreaker top: [src/rtl/fir8_top.v](src/rtl/fir8_top.v)
- Board constraints: [constraints/icebreaker.pcf](constraints/icebreaker.pcf)
- Formal collateral: [formal/fir8_formal.v](formal/fir8_formal.v), [formal/fir8.sby](formal/fir8.sby)

Golden model and testbench:
- Python golden model: [sim/golden/fir_model.py](sim/golden/fir_model.py)
- cocotb testbench: [sim/cocotb/test_fir8.py](sim/cocotb/test_fir8.py)

## Data flow summary

Stimulus → DUT [src/rtl/fir8_top.v](src/rtl/fir8_top.v) → Core [src/rtl/fir8.v](src/rtl/fir8.v) → Output

## Block diagram (data flow)

```
Stimulus (LFSR on hardware or cocotb sequences in sim)
            |
            v
        +----------+         +--------+
        |  DUT     |  -->    |  Core  |  -->  Filtered Q1.15 Output
        | fir8_top |         |  fir8  |
        +----------+         +--------+
             (iCEBreaker top-level)      (parameterized FIR)
```

- On hardware, [src/rtl/fir8_top.v](src/rtl/fir8_top.v) generates stimulus (16-bit LFSR) and forwards it to the FIR core.
- In simulation, the cocotb flow targets the core [src/rtl/fir8.v](src/rtl/fir8.v) directly (TOPLEVEL=fir8) with test-generated stimuli.

## Parameterization

Design-time parameters (validated in RTL and flows):
- TAPS: 4, 8, 16, 32 (power-of-two window size)
- PIPELINE: 0 or 1 (adds +1 output register when 1)
- ROUND: 0 or 1 (truncate vs symmetric round-to-nearest)
- SAT: 0 or 1 (wrap vs saturate to Q1.15)

Behavioral summary:
- Average computed as (sum_window + bias) >>> SHIFT, where SHIFT = log2(TAPS).
- Rounding when ROUND=1 uses symmetric bias ±2^(SHIFT−1) based on the sign of the pre-shift sum.
- Saturation when SAT=1 clamps to Q1.15 [-32768, 32767]; when SAT=0, output wraps to signed 16-bit.
- Latency (continuous valid_in): output becomes valid one cycle after the window fills, plus +1 cycle if PIPELINE=1.

## Module interfaces

Core FIR (fir8) — [src/rtl/fir8.v](src/rtl/fir8.v)
- Parameters: TAPS, PIPELINE, ROUND, SAT
- Ports:
  - clk: clock
  - rst: synchronous active-high reset
  - sample_in [15:0] (signed): Q1.15 input
  - valid_in: input sample valid
  - ready_in: always 1 (no backpressure in this phase)
  - sample_out [15:0] (signed): Q1.15 output
  - valid_out: output sample valid

Top-level (fir8_top) — [src/rtl/fir8_top.v](src/rtl/fir8_top.v)
- Parameters: TAPS, PIPELINE (ROUND and SAT left at core defaults for hardware top)
- Ports:
  - clk: 12 MHz board clock (see [constraints/icebreaker.pcf](constraints/icebreaker.pcf))
  - led: observable output combining a heartbeat divider and FIR MSB

Handshake notes:
- The core’s ready_in is statically 1 in this phase. Some test scenarios optionally reference a signal `in_valid`; the cocotb testbench gracefully handles environments with or without such an alias, and primarily drives `valid_in`.

## Data path and latency

- Window buffer holds TAPS previous samples.
- Combinational path:
  - sum_window = sample_in + sum(taps[0..TAPS−2])
  - bias = ±2^(SHIFT−1) when ROUND=1; else 0
  - avg = (sum_window + bias) >>> SHIFT
- Output stage:
  - Baseline: one registered stage with valid delayed to align one cycle after the window becomes full
  - Optional PIPELINE: adds a second register stage, increasing the latency by +1 cycle
- Total latency from continuous input after reset/window-fill:
  - latency_cycles = 1 + PIPELINE, applied starting once the window is full

## Formal and constraints

- Board pins for iCEBreaker are defined in [constraints/icebreaker.pcf](constraints/icebreaker.pcf).
- Optional formal checks and SBY configuration are provided:
  - Formal harness: [formal/fir8_formal.v](formal/fir8_formal.v)
  - SymbiYosys script: [formal/fir8.sby](formal/fir8.sby)

## Simulation and golden reference

- The Python golden model implements the same moving-average behavior with matching rounding/saturation semantics: [sim/golden/fir_model.py](sim/golden/fir_model.py)
- cocotb tests drive diverse stimuli (impulse, step, random, alternating, ramps, extremes) and compare against the golden model, accounting for DUT latency: [sim/cocotb/test_fir8.py](sim/cocotb/test_fir8.py)
- The cocotb Makefile configures TOPLEVEL=fir8 by default: [sim/cocotb/Makefile](sim/cocotb/Makefile)

## Related documentation

- Build and synthesis flow: [docs/synthesis.md](docs/synthesis.md)
- Simulation usage and coverage: [docs/simulation.md](docs/simulation.md)
- Hardware specification details (Q1.15, rounding, saturation): [docs/hw_spec.md](docs/hw_spec.md)