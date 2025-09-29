# FIR Reference — Moving‑Average and Q1.15 Fixed‑Point

This document explains the FIR background behind the project’s moving‑average design, the discrete‑time equation, and how Q1.15 fixed‑point arithmetic, rounding, and saturation/wrap rules are applied. It complements the hardware spec and test docs.

Key references:
- Golden model: [sim/golden/fir_model.py](sim/golden/fir_model.py)
- Testbench: [sim/cocotb/test_fir8.py](sim/cocotb/test_fir8.py)
- Hardware spec: [docs/hw_spec.md](docs/hw_spec.md)
- Fixed‑point notes: [docs/fixed_point.md](docs/fixed_point.md)

## 1) FIR basics

A discrete‑time FIR (Finite Impulse Response) filter computes output y[n] as a weighted sum (convolution) of the current and past inputs x[n−k] with coefficients h[k]:

- y[n] = Σ (k=0..N−1) h[k] · x[n−k]

For a moving‑average FIR of length N (also called a rectangular or boxcar average):

- h[k] = 1/N for k ∈ {0, …, N−1}
- y[n] = (1/N) · Σ (k=0..N−1) x[n−k]

When N is a power of two (N = 2^SHIFT), (1/N) = 1 / (2^SHIFT) is efficiently implemented with an arithmetic right shift by SHIFT bits.

## 2) Moving average in the project

- N ≡ TAPS ∈ {4, 8, 16, 32} (all powers of two)
- SHIFT = log2(TAPS) ∈ {2, 3, 4, 5}
- average = (sum_window) >>> SHIFT

The RTL and golden model restrict TAPS to this set so division becomes a shift, avoiding multipliers and saving resources on the iCE40UP5K.

## 3) Q1.15 fixed‑point representation

- Format: signed 16‑bit, with 1 sign bit and 15 fractional bits
- Nominal range: [−1.0000, +0.9999…]
  - +0.9999… ≈ 0x7FFF = 32767
  - −1.0000 = 0x8000 = −32768
- Conversion (real → Q1.15 integer):
  - q15 = round(real · 2^15), then clamp/wrap to 16‑bit as appropriate

Examples:
- 0.5 ≈ 0x4000 = 16384
- −0.5 ≈ 0xC000 = −16384
- 1.0 is not exactly representable; the maximum positive value is 0x7FFF

## 4) Bit growth and intermediate widths

Summing TAPS Q1.15 values increases the number of integer bits by SHIFT:

- sum_window width ≈ (sign) + 16 + SHIFT
- In RTL, an extra safety/sign bit is included: SUM_W = 16 + SHIFT + 1
- After summation, divide by TAPS via arithmetic shift by SHIFT to return to Q1.15 scale

## 5) Rounding vs truncate

Because we divide by a power of two, the average is computed with an arithmetic right shift. Two modes are supported:

- Truncate (ROUND=0): average = (sum_window) >>> SHIFT
  - Arithmetic right shift in two’s complement (negative values shift toward −∞)
- Symmetric round‑to‑nearest (ROUND=1):
  - bias = +2^(SHIFT−1) if sum_window ≥ 0; else −2^(SHIFT−1)
  - average = (sum_window + bias) >>> SHIFT
  - “Ties away from zero” behavior for exact half‑LSB cases before the shift

Intuition:
- Positive sums: add +half‑LSB before shifting → rounds up at halfway
- Negative sums: add −half‑LSB before shifting → rounds down (more negative) at halfway
- Compared to truncate, enabling rounding reduces average bias around zero

Example (SHIFT=3, i.e., TAPS=8):
- sum_window = +4
  - Truncate: 4 >>> 3 = 0
  - Round: (4 + 4) >>> 3 = 8 >>> 3 = 1
- sum_window = −4
  - Truncate: (−4) >>> 3 = −1 (arithmetic)
  - Round: (−4 − 4) >>> 3 = (−8) >>> 3 = −1

In the negative tie example above, both yield −1 due to arithmetic shift, but for other values rounding still reduces systematic bias.

## 6) Saturation vs wrap

After computing the average in Q1.15, results can be either saturated or wrapped:

- SAT=1 (saturate): clamp to [−32768, 32767]
- SAT=0 (wrap): keep only the low 16 bits (two’s‑complement wrap)

Examples:
- Value = 40000 (post‑shift intermediate)
  - Saturate → 32767
  - Wrap → 40000 & 0xFFFF = 40000 − 65536 = −25536
- Value = −40000
  - Saturate → −32768
  - Wrap → (−40000) & 0xFFFF = 25536 (positive wrapped representation) which is interpreted as +25536 if cast improperly; proper signed wrap gives −40000 mod 2^16 = 25536 − 65536 = −40000 (in practice, hardware takes low 16 bits and casts as signed)

Note: The golden model and RTL implement wrap by truncating to 16 bits and then reinterpreting as signed.

## 7) End‑to‑end moving‑average examples

Example A: TAPS=4 (SHIFT=2), all inputs at +0.5 (0x4000)
- sum_window = 0x4000 * 4 = 0x10000 = 65536
- Truncate:
  - avg = 65536 >>> 2 = 16384 = 0x4000 (+0.5)
- Round:
  - Bias for positive sum: +2^(2−1) = +2
  - avg = (65536 + 2) >>> 2 = 16384 (rounding has no effect here due to exact divisibility)

Example B: TAPS=8 (SHIFT=3), alternating extremes [+0x7FFF, −0x7FFF, +0x7FFF, −0x7FFF, …]
- Short windows hover near zero
- Truncate: averages trend slightly negative for negative‑leaning windows due to arithmetic right shift
- Round: symmetric bias reduces the tendency away from zero on half‑LSB cases

Example C: Edge overflow with many +0x7FFF values and SAT=0 vs SAT=1
- Long runs of +0x7FFF can push intermediates beyond Q1.15 during the average step (depending on input sequence)
- SAT=1 clamps to +0x7FFF (32767)
- SAT=0 wraps, producing a signed 16‑bit wraparound value

## 8) Latency and valid timing (summary)

- The average can only be produced once the window is full: first valid at index n = TAPS−1 (for continuous input valid)
- The DUT adds fixed output latency of (1 + PIPELINE) cycles after the window is full
- The golden model emits valid immediately once the window is full; the testbench offsets expected samples to align with DUT latency

See:
- Hardware spec: [docs/hw_spec.md](docs/hw_spec.md)
- Testbench details: [sim/cocotb/test_fir8.py](sim/cocotb/test_fir8.py)

## 9) Practical guidance

- Use ROUND=1 (symmetric rounding) for most use‑cases to reduce bias in averaged results
- Use SAT=1 when you need predictable clipping at the Q1.15 limits and want to avoid wraparound artifacts
- Keep TAPS in {4,8,16,32} so division is a shift (saves resources and simplifies timing)

## 10) Implementation pointers

- Golden model implements the numeric semantics described above:
  - [sim/golden/fir_model.py](sim/golden/fir_model.py)
- cocotb tests exercise impulses, steps, random runs, alternating extremes, ramps, and edge cases, including optional valid gaps where supported:
  - [sim/cocotb/test_fir8.py](sim/cocotb/test_fir8.py)

## 11) Related documentation

- Hardware details (ports, parameter checks, top integration):
  - [docs/hw_spec.md](docs/hw_spec.md)
  - RTL: [src/rtl/fir8.v](src/rtl/fir8.v), [src/rtl/fir8_top.v](src/rtl/fir8_top.v)
- Simulation flow and coverage:
  - [docs/simulation.md](docs/simulation.md)
- Synthesis/PnR flow:
  - [docs/synthesis.md](docs/synthesis.md)