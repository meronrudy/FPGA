"""
Golden models for a parameterized Q1.15 moving-average FIR.

Public API:
- fir_mavg_q15(samples, taps, do_round=True, do_sat=True) -> (outs, valids)
- impulse_response_q15(taps, length=64) -> list[int]

Behavior:
- Average: (sum + bias) >>> SHIFT, where SHIFT=log2(taps)
- Rounding (ROUND=1): symmetric round-to-nearest with ties away from zero:
  bias = +2^(SHIFT-1) if sum >= 0 else -2^(SHIFT-1)
- Truncate (ROUND=0): bias = 0 (arithmetic right shift)
- Saturation (SAT=1): clamp to Q15 range [-32768, 32767]
- Wrap (SAT=0): two's-complement wrap to 16 bits

Latency:
- No pipeline latency is modeled here; tests apply any DUT latency externally.

This module is import-side-effect free.
"""

from typing import Iterable, List, Sequence, Tuple

__all__ = ["Q15_MAX", "Q15_MIN", "fir_mavg_q15", "impulse_response_q15"]

Q15_MAX = 32767
Q15_MIN = -32768
_ALLOWED_TAPS = {4, 8, 16, 32}


def q15_wrap(v: int) -> int:
    """Wrap an integer to signed 16-bit Q1.15 range using two's complement."""
    v &= 0xFFFF
    if v & 0x8000:
        v -= 0x10000
    return v


def q15_saturate(v: int) -> int:
    """Saturate an integer to the Q1.15 range [-32768, 32767]."""
    if v > Q15_MAX:
        return Q15_MAX
    if v < Q15_MIN:
        return Q15_MIN
    return v


def _arith_shift_round(value: int, shift: int, do_round: bool) -> int:
    """Arithmetic right shift with optional symmetric rounding.

    If do_round:
      add +2^(shift-1) for non-negative values and -2^(shift-1) for negative values
      before shifting, achieving symmetric round-to-nearest with ties away from zero.
    If not do_round:
      perform arithmetic shift (truncate toward -inf for negatives due to Python semantics).
    """
    if shift <= 0:
        return value
    if do_round:
        half = 1 << (shift - 1)
        bias = half if value >= 0 else -half
        return (value + bias) >> shift
    else:
        return value >> shift


# Backward-compat private helpers retained (delegate to documented functions)
def _q15_wrap(v: int) -> int:
    """Backward-compat wrapper for internal usage; prefer q15_wrap."""
    return q15_wrap(v)


def _q15_sat(v: int) -> int:
    """Backward-compat wrapper for internal usage; prefer q15_saturate."""
    return q15_saturate(v)


def _fir_q15(
    samples: Iterable[int],
    coeffs_q15: Sequence[int],
    do_round: bool = True,
    do_sat: bool = True,
) -> Tuple[List[int], List[bool]]:
    """Generic Q15 FIR filter helper (internal).

    Args:
      samples: iterable of input Q1.15 integers.
      coeffs_q15: FIR coefficients in Q1.15 as integers (length N).
      do_round: enable symmetric rounding on the final Q1.15 result.
      do_sat: when True, saturate to Q15; otherwise wrap to 16-bit.

    Returns:
      (outs, valids) where outs are Q1.15 ints and valids is True once the
      N-sample window is filled.

    Notes:
      - Multiplication of Q1.15 by Q1.15 yields Q2.30. We accumulate in Python
        ints (arbitrary precision) and finally shift right by 15 with optional
        symmetric rounding before post-processing (sat/wrap).
      - No pipeline/latency modeling here; the test layer applies it.
    """
    ntaps = len(coeffs_q15)
    if ntaps <= 0:
        return [], []

    window: List[int] = []
    outs: List[int] = []
    valids: List[bool] = []

    for x in samples:
        x = q15_wrap(int(x))
        window.insert(0, x)
        if len(window) > ntaps:
            window.pop()

        if len(window) < ntaps:
            outs.append(0)
            valids.append(False)
            continue

        acc = 0
        for s, c in zip(window, coeffs_q15):
            acc += int(s) * int(c)  # Q2.30 accumulate

        y = _arith_shift_round(acc, 15, do_round)  # back to Q1.15

        if do_sat:
            y = q15_saturate(y)
        else:
            y = q15_wrap(y)

        outs.append(y)
        valids.append(True)

    return outs, valids


def fir_mavg_q15(
    samples: Iterable[int],
    taps: int,
    do_round: bool = True,
    do_sat: bool = True,
) -> Tuple[List[int], List[bool]]:
    """Compute a moving-average FIR of length 'taps' over signed Q1.15 samples.

    Args:
      samples: iterable of input Q1.15 integers.
      taps: number of taps in {4, 8, 16, 32}; must be power-of-two.
      do_round: when True, symmetric round-to-nearest with ties away from zero.
      do_sat: when True, clamp to Q1.15 range; otherwise wrap to 16-bit.

    Returns:
      (outs, valids)
        outs   : list of Q1.15 ints per input sample (sat/wrap applied)
        valids : list of booleans; True once the window is full (i >= taps-1)

    Implementation details:
      - SHIFT = log2(taps)
      - average = (sum_window + bias) >>> SHIFT
      - bias = ±2^(SHIFT-1) per symmetric rounding when do_round=True
      - No latency/pipeline delay is included here.
    """
    if taps not in _ALLOWED_TAPS:
        raise ValueError(f"taps must be one of {_ALLOWED_TAPS}, got {taps}")
    if taps & (taps - 1) != 0:
        raise ValueError("taps must be power-of-two")

    SHIFT = taps.bit_length() - 1  # log2(taps), since taps in power-of-two set

    window: List[int] = []
    outs: List[int] = []
    valids: List[bool] = []

    for x in samples:
        # Wrap incoming to 16-bit signed just like a typical RTL input port
        xi = q15_wrap(int(x))
        window.insert(0, xi)
        if len(window) > taps:
            window.pop()

        if len(window) < taps:
            outs.append(0)
            valids.append(False)
            continue

        s = sum(window)  # Python int, arbitrary precision
        avg = _arith_shift_round(s, SHIFT, do_round)

        y = q15_saturate(avg) if do_sat else q15_wrap(avg)

        outs.append(y)
        valids.append(True)

    return outs, valids


def impulse_response_q15(taps: int, length: int = 64) -> List[int]:
    """Generate the impulse response of the moving-average filter for Q1.15.

    An impulse of amplitude 0x7FFF is applied at n=0, zeros thereafter.
    The response is computed using fir_mavg_q15 with rounding+sat enabled.
    This function does not include pipeline latency.
    """
    if length <= 0:
        return []
    impulse = [Q15_MAX] + [0] * (length - 1)
    outs, _valids = fir_mavg_q15(impulse, taps=taps, do_round=True, do_sat=True)
    return outs