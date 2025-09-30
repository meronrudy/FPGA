"""
Agents package.

Modules:
- designer: load/validate variants and emit normalized JSON
- sim: drive cocotb testbench via Make
- synth: synth/place/route and aggregate reports
- analysis: generate Phase 1 report (includes hardware smoke section if present)
- board: reserve iCEBreaker, flash bitstream (SRAM), basic smoke test
"""

__all__ = ["designer", "sim", "synth", "analysis", "board"]