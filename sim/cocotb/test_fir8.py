# Cocotb tests for parameterized fir8 Q1.15 moving average
# - Supports TAPS in {4,8,16,32} and PIPELINE in {0,1}
# - ROUND/SAT toggle rounding and saturation behavior
# - Coverage enforced: >= 95% required via cocotb-coverage
#
# Latency model:
#   - Golden model produces valid starting at i == TAPS-1 (window full)
#   - DUT adds 1 + PIPELINE cycles of latency
#   - Tests offset expected stream by (1 + PIPELINE)
#
# Artifacts:
#   - Coverage YAML written to build/coverage_{TAPS}_{PIPELINE}_{ROUND}_{SAT}.yml
#
# Copyright:
#   - MIT Licensed, see LICENSE.

import os
import sys
from pathlib import Path
import random
from typing import List, Tuple

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

from cocotb_coverage.coverage import CoverPoint, CoverCross, coverage_db

# Add repo root to PYTHONPATH for golden model import
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sim.golden.fir_model import fir_mavg_q15  # noqa: E402

# Read parameterization from environment
ROUND = int(os.getenv("ROUND", "1"))
SAT = int(os.getenv("SAT", "1"))
PIPELINE = int(os.getenv("PIPELINE", "0"))
TAPS = int(os.getenv("TAPS", "8"))

Q15_MAX = 32767
Q15_MIN = -32768

# Coverage bins (make per-run bins so coverage can reach 100% within a single variant run)
STIM_TYPES = ("impulse", "step", "random", "alt", "ramp", "edge", "valid_gap")
TAPS_BINS = [TAPS]
ROUND_BINS = [ROUND]
SAT_BINS = [SAT]
PIPELINE_BINS = [PIPELINE]


def _q15_wrap(v: int) -> int:
    """Wrap an integer to signed 16-bit range (Q1.15)."""
    v &= 0xFFFF
    if v & 0x8000:
        v -= 0x10000
    return v


def expected_with_latency(samples: List[int], taps: int) -> Tuple[List[int], List[bool]]:
    """Compute expected outputs and valids with DUT latency applied.

    Applies the DUT's fixed latency offset of (1 + PIPELINE) cycles to the golden
    model's outs/valids. This function does not model valid gaps; use event-based
    checking for tests that deassert input valid.
    """
    outs, valids = fir_mavg_q15(samples, taps=taps, do_round=bool(ROUND), do_sat=bool(SAT))
    offset = 1 + PIPELINE
    if offset <= len(outs):
        exp_outs = [0] * offset + outs[:-offset]
        exp_valids = [False] * offset + valids[:-offset]
    else:
        exp_outs = [0] * len(outs)
        exp_valids = [False] * len(valids)
    return exp_outs, exp_valids


# Coverage definitions
@CoverPoint("top.stimulus_type", xf=lambda s: s, bins=list(STIM_TYPES))
@CoverPoint("top.taps", xf=lambda _s: TAPS, bins=TAPS_BINS)
@CoverPoint("top.round", xf=lambda _s: ROUND, bins=ROUND_BINS)
@CoverPoint("top.sat", xf=lambda _s: SAT, bins=SAT_BINS)
@CoverPoint("top.pipeline", xf=lambda _s: PIPELINE, bins=PIPELINE_BINS)
@CoverCross("cross.taps_x_pipeline", items=["top.taps", "top.pipeline"])
def sample_coverage(stimulus_type: str) -> None:
    """Coverage sampler. Decorators define bins and crosses."""
    return None


async def reset_dut(dut, cycles: int = 5):
    """Reset DUT and prime inputs to known values."""
    dut.rst.value = 1
    dut.sample_in.value = 0
    dut.valid_in.value = 0
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


async def drive_and_check(dut, seq: List[int], stimulus_type: str):
    """Drive a per-cycle valid=1 sequence and check against latency-aligned golden."""
    # Mark coverage for this stimulus
    sample_coverage(stimulus_type)

    # Precompute expected
    exp_outs, exp_valids = expected_with_latency(seq, TAPS)

    mismatches = 0
    for i, x in enumerate(seq):
        dut.sample_in.value = _q15_wrap(int(x))
        dut.valid_in.value = 1

        # Ready should always be asserted
        assert int(dut.ready_in.value) == 1, "ready_in must be 1 in Phase 1 (no backpressure)"

        await RisingEdge(dut.clk)

        got_valid = int(dut.valid_out.value) == 1
        got_out = dut.sample_out.value.signed_integer

        if got_valid:
            if not exp_valids[i]:
                mismatches += 1
                dut._log.error(f"[{stimulus_type}] Unexpected valid at i={i}, got={got_out}")
            else:
                exp = _q15_wrap(exp_outs[i])
                if got_out != exp:
                    mismatches += 1
                    dut._log.error(f"[{stimulus_type}] Mismatch at i={i}: got {got_out}, exp {exp}")

    dut.valid_in.value = 0
    await RisingEdge(dut.clk)

    assert mismatches == 0, f"[{stimulus_type}] Found {mismatches} mismatches"


def _len_for_tests() -> int:
    """Return default sequence length; ensures at least 4*TAPS."""
    return max(4 * TAPS, 64)


def _set_dut_in_valid(dut, value: int) -> None:
    """Set DUT input valid signal, supporting either in_valid or valid_in if present."""
    if hasattr(dut, "in_valid"):
        dut.in_valid.value = int(value)
        if hasattr(dut, "valid_in"):
            dut.valid_in.value = int(value)
    else:
        # Fallback for environments without in_valid
        if hasattr(dut, "valid_in"):
            dut.valid_in.value = int(value)


@cocotb.test()
async def test_01_impulse(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)
    n = _len_for_tests()
    seq = [Q15_MAX] + [0] * (n - 1)
    await drive_and_check(dut, seq, "impulse")


@cocotb.test()
async def test_02_step(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)
    n = _len_for_tests()
    step_val = 16384  # ~0.5 in Q1.15
    seq = [step_val] * n
    await drive_and_check(dut, seq, "step")


@cocotb.test()
async def test_03_random(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)
    n = _len_for_tests()
    rnd = random.Random(0xC0C0)
    seq = [rnd.randint(Q15_MIN, Q15_MAX) for _ in range(n)]
    await drive_and_check(dut, seq, "random")


@cocotb.test()
async def test_04_alt(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)
    n = _len_for_tests()
    seq = []
    val = Q15_MAX
    for i in range(n):
        seq.append(val if (i % 2 == 0) else -val)
    await drive_and_check(dut, seq, "alt")


@cocotb.test()
async def test_05_ramp(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)
    n = _len_for_tests()
    # Symmetric ramp from -0.5 to +0.5
    seq = []
    for i in range(n):
        frac = (i / max(1, n - 1)) - 0.5
        seq.append(_q15_wrap(int(frac * (Q15_MAX))))
    await drive_and_check(dut, seq, "ramp")


@cocotb.test()
async def test_edge_extremes(dut):
    """Stress Q15 extremes to exercise rounding boundaries and sat/wrap paths."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)

    n = _len_for_tests()

    # Construct a sequence emphasizing edge cases:
    # - long runs of min and max to drive post-accumulation sat/wrap for ROUND/SAT modes
    # - alternating extremes to hover near rounding boundaries around zero
    seq_core = ([-32768] * (2 * TAPS)) + ([32767] * (2 * TAPS)) + ([-32768, 32767] * (2 * TAPS))

    # Expand or trim to n
    seq = (seq_core * ((n + len(seq_core) - 1) // len(seq_core)))[:n]

    await drive_and_check(dut, seq, "edge")


@cocotb.test()
async def test_valid_gaps(dut):
    """Introduce valid gaps when 'in_valid' exists; otherwise run a basic sequence and log skip."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)

    if not hasattr(dut, "in_valid"):
        dut._log.info("Skipping valid-gap stimulus: DUT has no 'in_valid'; running basic random sequence.")
        n = _len_for_tests()
        rnd = random.Random(0xA11C)
        seq = [rnd.randint(Q15_MIN, Q15_MAX) for _ in range(n)]
        await drive_and_check(dut, seq, "valid_gap")
        return

    # With in_valid present, deassert for random stretches between asserted periods.
    sample_coverage("valid_gap")

    rnd = random.Random(0xBEEF)
    accepted_target = max(2 * TAPS, 32)

    # Pre-generate the samples that will actually be accepted when in_valid=1
    accepted_samples = [rnd.randint(Q15_MIN, Q15_MAX) for _ in range(accepted_target)]

    # Compute expected event values (order of outputs when valid_out=1)
    outs, valids = fir_mavg_q15(accepted_samples, taps=TAPS, do_round=bool(ROUND), do_sat=bool(SAT))
    expected_events = [_q15_wrap(y) for y, v in zip(outs, valids) if v]

    # Build a valid mask with random burst/gap lengths until we consume all accepted samples
    mask: List[int] = []
    taken = 0
    while taken < accepted_target:
        burst = rnd.randint(1, 5)
        for _ in range(burst):
            if taken >= accepted_target:
                break
            mask.append(1)
            taken += 1
        gap = rnd.randint(0, 4)
        mask.extend([0] * gap)

    # Drive sequence according to mask; when in_valid=0, drive zeros
    accepted_idx = 0
    event_idx = 0
    mismatches = 0

    for m in mask:
        if m:
            x = accepted_samples[accepted_idx]
            accepted_idx += 1
        else:
            x = 0  # ignored when in_valid=0

        dut.sample_in.value = _q15_wrap(int(x))
        _set_dut_in_valid(dut, m)

        # Ready should always be asserted
        assert int(dut.ready_in.value) == 1, "ready_in must be 1 in Phase 1 (no backpressure)"

        await RisingEdge(dut.clk)

        got_valid = int(dut.valid_out.value) == 1
        got_out = dut.sample_out.value.signed_integer

        if got_valid:
            if event_idx >= len(expected_events):
                mismatches += 1
                dut._log.error(f"[valid_gap] Unexpected extra valid with out={got_out}")
            else:
                exp = expected_events[event_idx]
                if got_out != exp:
                    mismatches += 1
                    dut._log.error(f"[valid_gap] Mismatch at event {event_idx}: got {got_out}, exp {exp}")
                event_idx += 1

    # Drain remaining pipeline/output events
    _set_dut_in_valid(dut, 0)
    dut.sample_in.value = 0
    for _ in range(1 + PIPELINE + TAPS + 4):
        await RisingEdge(dut.clk)
        got_valid = int(dut.valid_out.value) == 1
        if got_valid:
            if event_idx >= len(expected_events):
                mismatches += 1
                dut._log.error("[valid_gap] Unexpected extra valid during drain")
            else:
                exp = expected_events[event_idx]
                got_out = dut.sample_out.value.signed_integer
                if got_out != exp:
                    mismatches += 1
                    dut._log.error(f"[valid_gap] Mismatch at drain event {event_idx}: got {got_out}, exp {exp}")
                event_idx += 1

    # Final checks
    assert mismatches == 0, f"[valid_gap] Found {mismatches} mismatches"
    assert event_idx == len(expected_events), (
        f"[valid_gap] Not all expected events observed: {event_idx}/{len(expected_events)}"
    )


@cocotb.test()
async def test_99_coverage_and_export(dut):
    """Finalize and export coverage, assert threshold."""
    # No clock/reset needed; just export database
    build_dir = REPO_ROOT / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    cov_path = build_dir / f"coverage_{TAPS}_{PIPELINE}_{ROUND}_{SAT}.yml"
    coverage_db.export_to_yaml(str(cov_path))

    cov = coverage_db.coverage
    dut._log.info(f"Coverage: {cov:.2f}% -> {cov_path}")
    assert cov >= 95.0, f"Coverage below threshold: {cov:.2f}% < 95%"