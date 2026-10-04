# cocotb + Icarus Verilog testbench makefile
#
#   make ACC_W=22             # sa_top as built on the chip, 10,000 random matrices
#   make TB=pe                # PE unit tests
#   make TB=baseline          # single-MAC baseline (500 random matrices)
#   make TB=sa_top N=4 ACC_W=24 NUM_RANDOM=2000
#   make TB=sa_top PIPE=0 ISO=0   # single-cycle MAC variant without the operand copy
#   make all_tests            # PE + sa_top (N = 2, 4, 8) + baseline
#   make clean

SIM           ?= icarus
TOPLEVEL_LANG  = verilog
TB            ?= sa_top
N             ?= 8
ACC_W         ?= 32
K_MAX         ?= 64
PIPE          ?= 1
ISO           ?= 1
NUM_RANDOM    ?= 10000
SEED          ?= 2027

RTL_DIR := $(abspath ../rtl)
export N ACC_W K_MAX PIPE ISO NUM_RANDOM SEED
export PYTHONPATH := $(CURDIR):$(PYTHONPATH)
export RESULTS_DIR ?= $(abspath ../results)

ifeq ($(TB),gls)
  # Gate-level simulation of a routed netlist (GLS_NETLIST) with the PDK cell models.
  PDK_VERILOG        ?= $(PDK_ROOT)/sky130A/libs.ref/sky130_fd_sc_hd/verilog
  COCOTB_TOPLEVEL     = sa_top
  COCOTB_TEST_MODULES = test_gls
  VERILOG_SOURCES     = $(PDK_VERILOG)/primitives.v $(PDK_VERILOG)/sky130_fd_sc_hd.v \
                        $(GLS_NETLIST) $(CURDIR)/gls_dump.v
  COMPILE_ARGS       += -DFUNCTIONAL -DUNIT_DELAY=\#0 -s gls_dump
  export DESIGN = gls
  export GLS_NETLIST
  ifeq ($(GLS_POWER),1)
    PLUSARGS += +dump
  endif
else ifeq ($(TB),pe)
  COCOTB_TOPLEVEL     = pe
  COCOTB_TEST_MODULES = test_pe
  VERILOG_SOURCES     = $(RTL_DIR)/pe.v
  COMPILE_ARGS       += -Ppe.ACC_W=$(ACC_W) -Ppe.PIPE=$(PIPE) -Ppe.ISO=$(ISO)
else ifeq ($(TB),baseline)
  COCOTB_TOPLEVEL     = seq_mac_baseline
  COCOTB_TEST_MODULES = test_baseline
  VERILOG_SOURCES     = $(RTL_DIR)/seq_mac_baseline.v
  COMPILE_ARGS       += -Pseq_mac_baseline.N=$(N) -Pseq_mac_baseline.ACC_W=$(ACC_W) \
                        -Pseq_mac_baseline.K_MAX=$(K_MAX)
  export DESIGN = baseline
else
  COCOTB_TOPLEVEL     = sa_top
  COCOTB_TEST_MODULES = test_sa_top
  VERILOG_SOURCES     = $(RTL_DIR)/pe.v $(RTL_DIR)/skew.v $(RTL_DIR)/systolic_array.v \
                        $(RTL_DIR)/controller.v $(RTL_DIR)/sa_top.v
  COMPILE_ARGS       += -Psa_top.N=$(N) -Psa_top.ACC_W=$(ACC_W) -Psa_top.K_MAX=$(K_MAX) \
                        -Psa_top.PIPE=$(PIPE) -Psa_top.ISO=$(ISO)
  export DESIGN = systolic
endif

# Legacy names, for cocotb versions older than 2.0.
TOPLEVEL = $(COCOTB_TOPLEVEL)
MODULE   = $(COCOTB_TEST_MODULES)

# One build folder per configuration so parameter changes always recompile.
SIM_BUILD    = sim_build/$(TB)_N$(N)_ACC$(ACC_W)_P$(PIPE)_I$(ISO)$(GLS_TAG)
COCOTB_RESULTS_FILE = $(SIM_BUILD)/results.xml

include $(shell cocotb-config --makefiles)/Makefile.sim

.PHONY: all_tests
all_tests:
	$(MAKE) TB=pe ACC_W=22
	$(MAKE) TB=pe PIPE=0 ISO=0
	$(MAKE) TB=pe ISO=0
	$(MAKE) TB=sa_top N=8 ACC_W=22
	$(MAKE) TB=sa_top N=8 ACC_W=32 NUM_RANDOM=2000
	$(MAKE) TB=sa_top N=2 ACC_W=22 NUM_RANDOM=2000
	$(MAKE) TB=sa_top N=4 ACC_W=22 NUM_RANDOM=2000
	$(MAKE) TB=sa_top N=8 ACC_W=22 PIPE=0 ISO=0 NUM_RANDOM=2000
	$(MAKE) TB=baseline N=8 NUM_RANDOM=500

clean::
	rm -rf sim_build results.xml __pycache__
