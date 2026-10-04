#!/usr/bin/env bash
# One command for the whole flow:
#   lint -> formal -> cocotb tests -> Yosys sweep -> (LibreLane clock sweep) -> summarize
#
#   bash scripts/run_all.sh              # everything except the physical design flow
#   bash scripts/run_all.sh --quick      # fewer random matrices, for a fast check
#   bash scripts/run_all.sh --openlane   # also run the LibreLane clock sweep
#                                        # (run this one inside the LibreLane nix-shell)
set -euo pipefail
cd "$(dirname "$0")/.."

QUICK=0
OPENLANE=0
for arg in "$@"; do
  case "$arg" in
    --quick) QUICK=1 ;;
    --openlane) OPENLANE=1 ;;
    *) echo "unknown option: $arg"; exit 2 ;;
  esac
done

RTL="rtl/pe.v rtl/skew.v rtl/systolic_array.v rtl/controller.v rtl/sa_top.v"
mkdir -p results

step() { printf '\n==== %s ====\n' "$1"; }

step "1/6 Verilator lint (-Wall) for N in {2,4,8}, ACC_W in {20,22,24,32}"
for n in 2 4 8; do
  for w in 20 22 24 32; do
    for cfg in "1 1" "0 0"; do
      set -- $cfg
      verilator --lint-only -Wall -GN=$n -GACC_W=$w -GPIPE=$1 -GISO=$2 --top-module sa_top $RTL
    done
  done
done
verilator --lint-only -Wall --top-module seq_mac_baseline rtl/seq_mac_baseline.v
echo "lint clean"

step "2/6 Formal proof of the PE (Yosys SAT, k-induction)"
prove() {  # PIPE ISO ACC_W
  yosys -q -p "read_verilog -formal rtl/pe.v formal/pe_formal.v; \
               chparam -set PIPE $1 -set ISO $2 -set ACC_W $3 pe_formal; prep -top pe_formal; flatten; \
               async2sync; sat -tempinduct -prove-asserts -set-init-zero -seq 1 -verify"
}
if prove 1 1 22 > results/formal.log 2>&1 && prove 1 1 32 >> results/formal.log 2>&1 \
   && prove 0 0 32 >> results/formal.log 2>&1; then
  echo '{"target": "pe", "method": "yosys sat -tempinduct", "properties": 4, "configs": ["PIPE=1 ISO=1 ACC_W=22 (chip)", "PIPE=1 ISO=1 ACC_W=32", "PIPE=0 ISO=0 ACC_W=32"], "proven": true}' > results/formal.json
  echo "PE properties proven"
else
  echo '{"target": "pe", "method": "yosys sat -tempinduct", "properties": 4, "proven": false}' > results/formal.json
  echo "formal proof FAILED, see results/formal.log"; exit 1
fi
rm -f results/formal.log

step "3/6 cocotb tests (Icarus Verilog)"
if [ "$QUICK" = 1 ]; then
  make -C tb TB=pe
  make -C tb TB=sa_top N=8 ACC_W=22 NUM_RANDOM=300
  make -C tb TB=baseline N=8 NUM_RANDOM=20
else
  make -C tb all_tests
fi
# cocotb returns 0 even when a test fails, so check the result files too.
if grep -l "<failure" tb/sim_build/*/results.xml >/dev/null 2>&1; then
  echo "a cocotb test failed:"; grep -l "<failure" tb/sim_build/*/results.xml; exit 1
fi

step "4/6 Yosys synthesis sweep"
python3 scripts/sweep_params.py

if [ "$OPENLANE" = 1 ]; then
  step "5/6 LibreLane clock sweep (Sky130 HD)"
  python3 scripts/sweep_clock.py
else
  step "5/6 LibreLane skipped (pass --openlane inside the LibreLane nix-shell)"
fi

step "6/6 Summarize"
python3 scripts/summarize.py
