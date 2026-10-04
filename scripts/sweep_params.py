#!/usr/bin/env python3
"""Yosys synthesis sweep over N and ACC_W -> results/synth_sweep.json.

    python3 scripts/sweep_params.py                     # generic gates
    SKY130_LIB=/path/to/sky130_fd_sc_hd__tt_025C_1v80.lib python3 scripts/sweep_params.py

If SKY130_LIB is not set, the script looks for the liberty file inside the usual
PDK install folders (~/.ciel, ~/.volare, $PDK_ROOT). With a liberty file the
sweep reports real Sky130 HD cell area in um^2; without one it reports generic
gate counts and flip-flop counts, which are only good for relative comparison.
"""

import glob
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
N_VALUES = [2, 4, 8]
ACC_VALUES = [20, 22, 24, 32]
K_MAX = 64
LIB_NAME = "sky130_fd_sc_hd__tt_025C_1v80.lib"


def find_liberty():
    if os.environ.get("SKY130_LIB"):
        return os.environ["SKY130_LIB"]
    roots = [os.environ.get("PDK_ROOT", ""), "~/.ciel", "~/.volare", "/usr/local/share/pdk"]
    for root in roots:
        if not root:
            continue
        hits = glob.glob(os.path.expanduser(f"{root}/**/{LIB_NAME}"), recursive=True)
        if hits:
            return sorted(hits)[0]
    return ""


def min_safe_acc_w(k):
    worst_pos = k * (1 << 14)
    w = 2
    while worst_pos > (1 << (w - 1)) - 1:
        w += 1
    return w


def run_point(n, acc_w, lib, pipe=1):
    env = dict(os.environ, N=str(n), ACC_W=str(acc_w), K_MAX=str(K_MAX), PIPE=str(pipe),
               SKY130_LIB=lib, OUT_DIR=str(ROOT / "synth" / "out"))
    t0 = time.time()
    proc = subprocess.run(["yosys", "-q", "-c", "synth/yosys.tcl"], cwd=ROOT, env=env,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout[-2000:], proc.stderr[-2000:], file=sys.stderr)
        raise RuntimeError(f"yosys failed for N={n} ACC_W={acc_w}")
    stat = json.loads((ROOT / "synth" / "out" / f"sa_top_N{n}_ACC{acc_w}_P{pipe}.stat.json").read_text())
    mod = next(iter(stat["modules"].values()))
    cells = mod["num_cells_by_type"]
    dffs = sum(v for k, v in cells.items() if "DFF" in k.upper() or "dfrtp" in k or "dfxtp" in k
               or "edfxtp" in k or "dfstp" in k)
    point = {
        "N": n, "ACC_W": acc_w, "PIPE": pipe,
        "cells": mod["num_cells"],
        "flip_flops": dffs,
        "synth_seconds": round(time.time() - t0, 1),
    }
    if lib:
        point["area_um2"] = round(float(mod["area"]), 1)
    else:
        point["comb_transistor_estimate"] = mod.get("estimated_num_transistors")
    return point


def main():
    lib = find_liberty()
    mode = "sky130_fd_sc_hd" if lib else "generic_gates"
    print(f"synthesis sweep mode: {mode}" + (f" ({lib})" if lib else ""))
    points = []
    for n in N_VALUES:
        for acc_w in ACC_VALUES:
            p = run_point(n, acc_w, lib)
            points.append(p)
            metric = f"{p['area_um2']} um2" if lib else f"{p['cells']} cells"
            print(f"  N={n:<2} ACC_W={acc_w:<2}  {metric:>14}  FFs={p['flip_flops']}")

    # Cost of the product pipeline register: same 8x8 / 32-bit point without it.
    p0 = run_point(8, 32, lib, pipe=0)
    metric = f"{p0['area_um2']} um2" if lib else f"{p0['cells']} cells"
    print(f"  N=8  ACC_W=32 PIPE=0 {metric:>14}  FFs={p0['flip_flops']}")

    yosys_version = subprocess.run(["yosys", "-V"], capture_output=True, text=True).stdout.strip()
    out = {
        "mode": mode,
        "yosys": yosys_version.split(" (")[0],
        "note_on_versions": "cell areas depend on the Yosys/ABC version; these match the LibreLane toolchain",
        "liberty": os.path.basename(lib) if lib else None,
        "k_max": K_MAX,
        "min_safe_acc_w_for_k_max": min_safe_acc_w(K_MAX),
        "note": ("ACC_W below min_safe_acc_w can overflow for worst-case inputs at K = K_MAX; "
                 "the RTL clamps K to K_MAX so the safe width is a hard guarantee."),
        "points": points,
        "no_pipeline_reference": p0,
    }
    # Area saved by right-sizing the accumulator from 32 bits to the minimum safe width.
    key = "area_um2" if lib else "cells"
    safe = out["min_safe_acc_w_for_k_max"]
    savings = {}
    for n in N_VALUES:
        full = next((p for p in points if p["N"] == n and p["ACC_W"] == 32), None)
        right = next((p for p in points if p["N"] == n and p["ACC_W"] == safe), None)
        if full and right:
            savings[f"N{n}"] = {
                "metric": key,
                "acc32": full[key],
                f"acc{safe}": right[key],
                "saved_pct": round(100.0 * (full[key] - right[key]) / full[key], 1),
            }
    out["right_sizing_savings"] = savings
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "synth_sweep.json").write_text(json.dumps(out, indent=2) + "\n")
    print(f"wrote {RESULTS / 'synth_sweep.json'}")


if __name__ == "__main__":
    main()
