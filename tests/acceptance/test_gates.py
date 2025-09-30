"""
Acceptance tests for orchestration gates.

These tests validate the “promote late” policy:
- If simulation fails for a variant, synthesis and hardware must be skipped.
- If synthesis fails for a variant, hardware must be skipped.
- Hardware is executed only when with_hardware=True AND software gates (sim then synth) have succeeded.

Rationale
- Hardware is a scarce, expensive resource. This suite ensures the orchestrator enforces safety gates
  and backpressure by preventing unvalidated designs from reaching the board.

See also
- Orchestrator step-by-step gating: run_phase1() in orchestrator/crew.py
- Design philosophy and wind-tunnel approach: docs/windtunnel.md
"""

import types
import pytest

# Import orchestrator flow
import orchestrator.crew as crew  # noqa: E402


def _args(variants, with_hw=False):
    return types.SimpleNamespace(
        variants=variants,
        with_hardware=with_hw,
        sim="verilator",
        cooldown=0.01,
        verbose=0,
        log_level=None,
    )


def test_no_board_when_sim_fails(monkeypatch):
    calls = {"board": 0, "sim": 0, "synth": 0, "analysis": 0}

    monkeypatch.setattr(crew, "run_designer", lambda: 0)

    def _sim_ok(name, sim="verilator"):
        calls["sim"] += 1
        return 1  # fail simulation

    def _synth(name):
        calls["synth"] += 1
        return 0

    def _board(name, cooldown=0.01):
        calls["board"] += 1
        return 0

    def _analysis():
        calls["analysis"] += 1
        return 0

    monkeypatch.setattr(crew, "run_sim", _sim_ok)
    monkeypatch.setattr(crew, "run_synth", _synth)
    monkeypatch.setattr(crew, "run_board", _board)
    monkeypatch.setattr(crew, "run_analysis", _analysis)

    rc = crew.local_orchestrate(_args(["baseline8"], with_hw=True))
    assert rc == 0
    assert calls["sim"] == 1
    assert calls["synth"] == 0, "Synthesis must be skipped when simulation fails"
    assert calls["board"] == 0, "Board must not run when simulation fails"
    assert calls["analysis"] == 1


def test_no_board_when_synth_fails(monkeypatch):
    calls = {"board": 0, "sim": 0, "synth": 0, "analysis": 0}

    monkeypatch.setattr(crew, "run_designer", lambda: 0)

    def _sim_ok(name, sim="verilator"):
        calls["sim"] += 1
        return 0

    def _synth_fail(name):
        calls["synth"] += 1
        return 1  # fail synthesis

    def _board(name, cooldown=0.01):
        calls["board"] += 1
        return 0

    def _analysis():
        calls["analysis"] += 1
        return 0

    monkeypatch.setattr(crew, "run_sim", _sim_ok)
    monkeypatch.setattr(crew, "run_synth", _synth_fail)
    monkeypatch.setattr(crew, "run_board", _board)
    monkeypatch.setattr(crew, "run_analysis", _analysis)

    rc = crew.local_orchestrate(_args(["baseline8"], with_hw=True))
    assert rc == 0
    assert calls["sim"] == 1
    assert calls["synth"] == 1
    assert calls["board"] == 0, "Board must not run when synthesis fails"
    assert calls["analysis"] == 1


def test_board_runs_only_when_with_hardware_true(monkeypatch):
    calls = {"board": 0, "sim": 0, "synth": 0, "analysis": 0}

    monkeypatch.setattr(crew, "run_designer", lambda: 0)

    def _sim_ok(name, sim="verilator"):
        calls["sim"] += 1
        return 0

    def _synth_ok(name):
        calls["synth"] += 1
        return 0

    def _board(name, cooldown=0.01):
        calls["board"] += 1
        return 0

    def _analysis():
        calls["analysis"] += 1
        return 0

    monkeypatch.setattr(crew, "run_sim", _sim_ok)
    monkeypatch.setattr(crew, "run_synth", _synth_ok)
    monkeypatch.setattr(crew, "run_board", _board)
    monkeypatch.setattr(crew, "run_analysis", _analysis)

    # with_hardware=False -> board should NOT be called
    rc = crew.local_orchestrate(_args(["baseline8"], with_hw=False))
    assert rc == 0
    assert calls["board"] == 0

    # with_hardware=True -> board SHOULD be called
    rc = crew.local_orchestrate(_args(["baseline8"], with_hw=True))
    assert rc == 0
    assert calls["board"] == 1, "Board should run when sim and synth pass and with_hardware=True"