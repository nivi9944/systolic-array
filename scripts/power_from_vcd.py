#!/usr/bin/env python3
"""Activity-based power of a routed chip: gate-level VCD -> OpenSTA report_power.

    python3 scripts/power_from_vcd.py openlane/runs/clk_16 --vcd tb/gls.vcd --period 16

Needs OpenSTA (`sta`, part of the LibreLane toolchain) and PDK_ROOT. Reads the
final netlist, SDC and nominal SPEF of the run, annotates switching activity from
the VCD of a gate-level simulation (tb/test_gls.py with GLS_POWER=1), and writes
results/power_measured.json. The same report without the VCD (the tool's default
activity) is included for comparison.
"""

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = "sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"


def run_sta(run_dir, vcd, scope):
    pdk = os.environ.get("PDK_ROOT", "")
    fin = Path(run_dir) / "final"
    tcl = f"""
read_liberty {pdk}/{LIB}
read_verilog {fin}/nl/sa_top.nl.v
link_design sa_top
read_sdc {fin}/sdc/sa_top.sdc
read_spef {fin}/spef/nom/sa_top.nom.spef
{"read_vcd -scope " + scope + " " + str(vcd) if vcd else ""}
report_power
"""
    with tempfile.NamedTemporaryFile("w", suffix=".tcl", delete=False) as fh:
        fh.write(tcl)
        path = fh.name
    out = subprocess.run(["sta", "-no_splash", "-exit", path], capture_output=True, text=True).stdout
    os.unlink(path)
    groups = {}
    for line in out.splitlines():
        m = re.match(r"^(Sequential|Combinational|Clock|Macro|Pad|Total)\s+([-\d.e+]+)\s+([-\d.e+]+)\s+([-\d.e+]+)\s+([-\d.e+]+)", line)
        if m:
            groups[m.group(1)] = [float(m.group(i)) for i in range(2, 6)]
    if "Total" not in groups:
        raise SystemExit("could not parse report_power output:\n" + out[-3000:])
    anno = re.search(r"Annotated\s+(\d+)\s+pin activities", out)
    return groups, out, anno


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--vcd", required=True)
    ap.add_argument("--period", type=float, required=True, help="clock period of the run and of the simulation (ns)")
    ap.add_argument("--scope", default="sa_top")
    ap.add_argument("--workload", default="back-to-back K = 64 jobs of uniform random INT8 data at full throughput")
    ap.add_argument("--out", default=str(ROOT / "results" / "power_measured.json"))
    args = ap.parse_args()

    g_act, out_act, anno = run_sta(args.run_dir, args.vcd, args.scope)
    g_def, _, _ = run_sta(args.run_dir, None, args.scope)
    f_mhz = 1000.0 / args.period
    peak_gops = 2 * 64 * f_mhz / 1000.0
    total = g_act["Total"][3]
    res = {
        "run_dir": str(Path(args.run_dir)),
        "corner": "nom_tt_025C_1v80 (typical, 25C, 1.80V), nominal parasitics",
        "clock_mhz": round(f_mhz, 2),
        "workload": args.workload,
        "activity_source": "gate-level simulation VCD of the routed netlist (read_vcd)",
        "power_mw": round(total * 1000, 3),
        "groups_mw": {k: round(v[3] * 1000, 3) for k, v in g_act.items() if k in ("Sequential", "Combinational", "Clock")},
        "internal_mw": round(g_act["Total"][0] * 1000, 3),
        "switching_mw": round(g_act["Total"][1] * 1000, 3),
        "leakage_mw": round(g_act["Total"][2] * 1000, 6),
        "default_activity_power_mw": round(g_def["Total"][3] * 1000, 3),
        "peak_gops": round(peak_gops, 3),
        "gops_per_w_at_peak": round(peak_gops / total, 1),
        "energy_pj_per_mac_at_peak": round(total / (64 * f_mhz * 1e6) * 1e12, 2),
    }
    if anno:
        res["annotated_pin_activities"] = int(anno.group(1))
    Path(args.out).write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
