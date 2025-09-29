# iCEBreaker (iCE40UP5K-SG48) Phase 1 build orchestration
# - Synthesis: Yosys (json netlist)
# - PnR: nextpnr-ice40 (+ icetime timing estimate)
# - Pack: icepack to .bin
# - Sim: reserved for cocotb/pytest (added later)
# Tools required: yosys, nextpnr-ice40, icetime, icepack, bash

TOP             ?= fir8_top
YOSYS_SCRIPT    ?= synth/ice40/yosys_ice40.ys
NEXTPNR_SCRIPT  ?= synth/ice40/nextpnr_ice40.sh
ICEPACK_SCRIPT  ?= synth/ice40/icestorm_pack.sh
PCF             ?= constraints/icebreaker.pcf

BUILD_DIR       ?= build
JSON            ?= $(BUILD_DIR)/$(TOP).json
ASC             ?= $(BUILD_DIR)/$(TOP).asc
BIN             ?= $(BUILD_DIR)/$(TOP).bin

# Default target
.PHONY: all
all: synth pnr pack

# Ensure build directory exists
$(BUILD_DIR):
	@mkdir -p $(BUILD_DIR)

# Synthesis with Yosys
.PHONY: synth
synth: $(BUILD_DIR)
	@echo "[yosys] Synthesizing $(TOP) -> $(JSON)"
	yosys -c $(YOSYS_SCRIPT)

# Place-and-route with nextpnr and timing estimate with icetime
.PHONY: pnr
pnr: synth
	@echo "[nextpnr] PnR for $(TOP)"
	bash $(NEXTPNR_SCRIPT)

# Pack ASC to BIN for programming
.PHONY: pack
pack: pnr
	@echo "[icepack] Packing ASC -> BIN"
	bash $(ICEPACK_SCRIPT)

# Clean build artifacts
.PHONY: clean
clean:
	@echo "[clean] Removing $(BUILD_DIR)"
	rm -rf $(BUILD_DIR)

# Placeholder simulation target (cocotb/pytest will be added later)
.PHONY: sim
sim:
	@echo "[sim] Simulation not yet wired; will run cocotb/pytest in Phase 1"
	@exit 0

# Convenience: full rebuild
.PHONY: rebuild
rebuild: clean all

# Formal verification (SymbiYosys)
.PHONY: formal
formal:
	@echo "[formal] Running SymbiYosys"
	sby -f formal/fir8.sby