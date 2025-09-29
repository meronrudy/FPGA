# Hardware Specification — Q1.15 Moving‑Average FIR

This document specifies the behavior, numeric conventions, and parameterization of the hardware FIR core and iCEBreaker top in this repository.

Core and top RTL:
- FIR core: [src/rtl/fir8.v](src/rtl/fir8.v)
- iCEBreaker top: [src/rtl/fir8_top.v](src/rtl/fir8_top.v)

Supporting assets:
- Constraints (iCEBreaker pins): [constraints/icebreaker.pcf](constraints/icebreaker.pcf)
- Formal harness and job (optional): [formal/fir8_formal.v](formal/fir8_formal.v), [formal/fir8.sby](formal/fir8.sby)

Reference model and tests:
- Golden model: [sim/golden/fir_model.py](sim/golden/fir_model.py)
- cocotb tests: [sim/cocotb/test_fir8.py](sim/cocotb/test_fir8.py)

## 1) Filter behavior

- Filter type: Length‑N moving‑average FIR, with N = TAPS ∈ {4, 8, 16, 32}.
- Input/output format: Signed Q1.15 fixed‑point, range [−32768, 32767].
- Windowing: The output at time n is the arithmetic mean of the most recent N samples.

Conceptually:
- sum_window(n) = x[n] + x[n−1] + … + x[n−N+1]
- SHIFT = log2(N) since N is restricted to powers of two
- average(n) = (sum_window(n) + bias) >>> SHIFT

Where:
- For ROUND=1, bias = +2^(SHIFT−1) if sum_window ≥ 0, else −2^(SHIFT−1)
- For ROUND=0, bias = 0 (truncate via arithmetic right shift)

Saturation/wrap:
- SAT=1: Clamp final result to Q1.15 [−32768, 32767]
- SAT=0: Wrap final result to signed 16‑bit (two’s complement)

## 2) Fixed‑point and numeric ranges (Q1.15)

- Q1.15 range: [−1.0000, +0.9999…] represented as signed 16‑bit integers:
  - +0.9999 ≈ 0x7FFF (32767)
  - −1.0000 = 0x8000 (−32768)

Bit‑growth:
- For a moving average, intermediate sum growth is bounded by SHIFT = log2(TAPS).
- The implementation uses a widened intermediate width SUM_W = 16 + SHIFT + 1 (includes sign).
- The final right‑shift by SHIFT returns to a Q1.15‑scaled value before saturation/wrap.

Rounding vs truncate:
- ROUND=1: Symmetric round‑to‑nearest with ties away from zero by adding ±2^(SHIFT−1) pre‑shift.
- ROUND=0: Truncate via arithmetic right shift (toward −∞ for negative sums).

Saturation vs wrap:
- SAT=1: Clamp to Q1.15 range after rounding/truncate.
- SAT=0: Two’s‑complement wrap to 16 bits after rounding/truncate.

## 3) Latency and handshake

- Input handshake: valid_in asserted per cycle to accept a sample. ready_in is always 1 in this phase (no backpressure).
- Output valid protocol:
  - Output becomes valid one cycle after the N‑sample window is full.
  - Optional PIPELINE=1 inserts an extra output register, adding +1 cycle latency.

Total latency once the window is full (with continuous valid_in):
- latency_cycles = 1 + PIPELINE

Notes:
- Reset behavior initializes the window and internal registers to 0; valid_out is deasserted until the window fill condition and latency pipeline are satisfied.

## 4) Parameterization

The FIR core supports the following parameters (checked at elaboration):

- TAPS: Allowed values {4, 8, 16, 32}. Must be power‑of‑two.
- PIPELINE: 0 or 1. When 1, adds a second output register stage.
- ROUND: 0 or 1. 1 = symmetric round‑to‑nearest; 0 = truncate.
- SAT: 0 or 1. 1 = saturate to Q1.15; 0 = wrap to 16‑bit.

Behavioral expectations per parameter:
- Increasing TAPS increases averaging window and latency until the window fills; it does not change post‑fill per‑sample latency beyond the fixed 1 + PIPELINE cycles.
- Enabling PIPELINE=1 increases Fmax headroom at the cost of +1 cycle latency.
- ROUND=1 reduces average bias vs truncate, especially near rounding boundaries.
- SAT=1 prevents numerical wraparound at Q1.15 extremes.

## 5) Top‑level (iCEBreaker) integration

Top wrapper [src/rtl/fir8_top.v](src/rtl/fir8_top.v):
- Parameters forwarded to the core: TAPS, PIPELINE (ROUND/SAT left at defaults in top).
- Ports:
  - clk: 12 MHz reference (see [constraints/icebreaker.pcf](constraints/icebreaker.pcf))
  - led: observable LED output combining a heartbeat divider and FIR MSB
- Behavior:
  - Synchronous POR stretches reset at power‑up
  - 16‑bit Fibonacci LFSR generates stimulus; valid_in is held high
  - LED = heartbeat_bit XOR sample_out[15] for easy visual activity

## 6) Formal and constraints

- Constraints: board pin assignments reside in [constraints/icebreaker.pcf](constraints/icebreaker.pcf)
- Optional formal assets:
  - Harness: [formal/fir8_formal.v](formal/fir8_formal.v)
  - SBY task: [formal/fir8.sby](formal/fir8.sby)

## 7) Parameter table and valid ranges

The design and tooling validate parameters in multiple places:

- RTL checks (elaboration errors) in [src/rtl/fir8.v](src/rtl/fir8.v):
  - TAPS ∈ {4,8,16,32}; PIPELINE ∈ {0,1}; ROUND ∈ {0,1}; SAT ∈ {0,1}

- Synthesis driver validation in [agents/synth.py](agents/synth.py):
  - Expects YAML entries with uppercase numeric params nested under `params`:
    - TAPS ∈ {4,8,16,32}
    - PIPELINE, ROUND, SAT ∈ {0,1}
    - Optional per‑variant flow hooks: `yosys_opts`, `nextpnr_opts`, `seed`

- Configuration loader validation in [common/config.py](common/config.py):
  - Validates a minimal “flat” schema (per‑variant keys at the top level): name, taps, optional pipeline/round/sat/seed/yosys_opts/nextpnr_opts/freq.
  - Used by [agents/designer.py](agents/designer.py) and optionally by [agents/sim.py](agents/sim.py) when `--variant` is used.

Schema note:
- The repository’s sample [configs/variants.yaml](configs/variants.yaml) is tailored for the synthesis flow (nested uppercase `params`). If you intend to use [agents/designer.py](agents/designer.py) or the simulation agent’s `--variant` resolution, provide a flat YAML matching the minimal schema enforced by [common/config.py](common/config.py), or maintain a separate YAML for that purpose.

Example entries:

Synthesis‑style (used by [agents/synth.py](agents/synth.py)):
```yaml
variants:
  - name: baseline8
    params: { ROUND: 1, SAT: 1, PIPELINE: 0, TAPS: 8 }
```

Flat schema (validated by [common/config.py](common/config.py), used by [agents/designer.py](agents/designer.py)):
```yaml
variants:
  - name: baseline8
    taps: 8
    pipeline: 0
    round: "round"       # or "truncate"
    sat: "saturate"      # or "wrap"
    # optional:
    yosys_opts: ""
    nextpnr_opts: ""
    seed: 1
    freq: 12
```

## 8) Compliance with the golden model

The Python golden model [sim/golden/fir_model.py](sim/golden/fir_model.py):
- Implements the same moving‑average behavior and Q1.15 semantics (round/sat/wrap).
- Produces “valid” outputs once the window is full; the cocotb testbench applies the DUT’s additional latency offset of (1 + PIPELINE) when comparing streams.

## 9) References

- FIR core RTL: [src/rtl/fir8.v](src/rtl/fir8.v)
- iCEBreaker top: [src/rtl/fir8_top.v](src/rtl/fir8_top.v)
- Golden model: [sim/golden/fir_model.py](sim/golden/fir_model.py)
- Testbench: [sim/cocotb/test_fir8.py](sim/cocotb/test_fir8.py)
- Constraints: [constraints/icebreaker.pcf](constraints/icebreaker.pcf)
- Formal collateral: [formal/fir8_formal.v](formal/fir8_formal.v), [formal/fir8.sby](formal/fir8.sby)