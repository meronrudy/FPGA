# Cocotb simulation Makefile for parameterized fir8
# Usage examples:
#   make SIM=verilator
#   make SIM=icarus
# Environment (overridable):
#   ROUND?=1  SAT?=1  PIPELINE?=0  TAPS?=8
#
# Verilator parameters are passed via -G flags; Icarus via -P module.param=value.
# PYTHONPATH is set to the repo root so tests can import the golden model.

TOPLEVEL_LANG ?= verilog
SIM           ?= verilator

# FIR parameters (overridable via environment)
ROUND    ?= 1
SAT      ?= 1
PIPELINE ?= 0
TAPS     ?= 8

# DUT sources
VERILOG_SOURCES := \
  $(abspath ../../src/rtl/fir8.v)

# Top-level of DUT for simulation
TOPLEVEL := fir8

# Python test module name (without .py)
MODULE := test_fir8

# Extra compile options for simulators
EXTRA_ARGS :=

# For Verilator, enable trace and pass parameters
ifeq ($(SIM),verilator)
  EXTRA_ARGS += --trace
  EXTRA_ARGS += -GROUND=$(ROUND) -GSAT=$(SAT) -GPIPELINE=$(PIPELINE) -GTAPS=$(TAPS)
endif

# For Icarus, pass parameters with -P
ifeq ($(SIM),icarus)
  EXTRA_ARGS += -Pfir8.ROUND=$(ROUND) -Pfir8.SAT=$(SAT) -Pfir8.PIPELINE=$(PIPELINE) -Pfir8.TAPS=$(TAPS)
endif

# Export to cocotb make system
export TOPLEVEL_LANG
export SIM
export VERILOG_SOURCES
export TOPLEVEL
export MODULE
export EXTRA_ARGS
export ROUND
export SAT
export PIPELINE
export TAPS

# Ensure cocotb can import the golden model relative to repo root
export PYTHONPATH := $(abspath ../..):$(PYTHONPATH)

# Include cocotb's simulation makefile
include $(shell cocotb-config --makefiles)/Makefile.sim