# Quick Yosys synthesis of sa_top for one (N, ACC_W) point.
#
# Usage (from the repo root):
#   N=8 ACC_W=32 yosys -c synth/yosys.tcl
#   N=8 ACC_W=32 SKY130_LIB=/path/to/sky130_fd_sc_hd__tt_025C_1v80.lib yosys -c synth/yosys.tcl
#
# With SKY130_LIB set, the design is mapped to real Sky130 HD standard cells and
# the report contains the cell area in um^2. Without it, Yosys maps to generic
# gates and reports a CMOS transistor-count estimate (useful for relative
# comparisons only). Reports go to synth/out/.

yosys -import

proc env_or {name default} {
    if {[info exists ::env($name)] && $::env($name) ne ""} { return $::env($name) }
    return $default
}

set N      [env_or N 8]
set ACC_W  [env_or ACC_W 32]
set K_MAX  [env_or K_MAX 64]
set PIPE   [env_or PIPE 1]
set LIB    [env_or SKY130_LIB ""]
set TOP    [env_or TOP sa_top]
set OUT    [env_or OUT_DIR synth/out]
set TAG    "${TOP}_N${N}_ACC${ACC_W}_P${PIPE}"

file mkdir $OUT

foreach f {pe.v skew.v systolic_array.v controller.v sa_top.v} {
    read_verilog -defer rtl/$f
}
chparam -set N $N -set ACC_W $ACC_W -set K_MAX $K_MAX -set PIPE $PIPE $TOP
hierarchy -check -top $TOP
synth -top $TOP -flatten

if {$LIB ne ""} {
    dfflibmap -liberty $LIB
    abc -liberty $LIB
    opt_clean -purge
    tee -o $OUT/$TAG.stat.txt stat -liberty $LIB
    tee -q -o $OUT/$TAG.stat.json stat -json -liberty $LIB
} else {
    abc -g AND,NAND,OR,NOR,XOR,XNOR,ANDNOT,ORNOT,MUX
    opt_clean -purge
    tee -o $OUT/$TAG.stat.txt stat -tech cmos
    tee -q -o $OUT/$TAG.stat.json stat -json -tech cmos
}
