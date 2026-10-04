#!/usr/bin/env python3
"""results/*.json -> throughput.json, README results table and plots.

    python3 scripts/summarize.py            # update the README table and docs plots
    python3 scripts/summarize.py --check    # also fail if a measurement is missing

Rule: every number printed here comes from a results/*.json file. If a
measurement is missing, its row says "pending".
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
DOCS = ROOT / "docs"
README = ROOT / "README.md"
N = 8
ACC_W = 22   # accumulator width built on the chip (safe for K <= 64)
START, END = "<!-- RESULTS:START -->", "<!-- RESULTS:END -->"


def load(name):
    p = RESULTS / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def fmt(x, nd=1):
    if x is None:
        return "pending"
    if isinstance(x, float):
        return f"{x:,.{nd}f}"
    return f"{x:,}"


def compute_throughput(cycles, openlane):
    """Peak = 2 ops (multiply + add) x N^2 PEs x f. Effective = peak x measured utilization."""
    if not openlane or not openlane.get("clock_mhz") or not openlane.get("timing_met"):
        return None
    f = openlane["clock_mhz"]
    peak = 2 * N * N * f / 1000.0
    out = {"N": N, "clock_mhz": f, "peak_gops": round(peak, 3), "effective_gops": {}}
    sa = (cycles or {}).get(f"systolic_N{N}", {})
    for k, v in sa.items():
        out["effective_gops"][k] = round(peak * v["utilization_pct"] / 100.0, 3)
    (RESULTS / "throughput.json").write_text(json.dumps(out, indent=2) + "\n")
    return out


def plots(cycles, synth):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("(matplotlib not installed: skipping plots)")
        return
    DOCS.mkdir(exist_ok=True)
    blue, orange, grey = "#2a6fdb", "#e8833a", "#8a8f98"

    if cycles and f"systolic_N{N}" in cycles and f"baseline_N{N}" in cycles:
        sa, bl = cycles[f"systolic_N{N}"], cycles[f"baseline_N{N}"]
        ks = [k for k in sa if k in bl]
        fig, ax = plt.subplots(figsize=(5.2, 3.2), dpi=150)
        x = range(len(ks))
        ax.bar([i - 0.2 for i in x], [bl[k]["cycles"] for k in ks], 0.4, label="single-MAC baseline", color=grey)
        ax.bar([i + 0.2 for i in x], [sa[k]["cycles"] for k in ks], 0.4, label=f"{N}x{N} systolic array", color=blue)
        for i, k in enumerate(ks):
            ax.annotate(f"{bl[k]['cycles'] / sa[k]['cycles']:.1f}x", (i + 0.2, sa[k]["cycles"]),
                        textcoords="offset points", xytext=(0, 3), ha="center", fontsize=8)
        ax.set_yscale("log")
        ax.set_xticks(list(x), [k.replace("K", "K = ") for k in ks])
        ax.set_ylabel("cycles, start to done (log)")
        ax.set_title("Measured latency for an 8 x K x 8 matrix multiply")
        ax.legend(fontsize=8, frameon=False)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()
        fig.savefig(DOCS / "cycles.png")
        plt.close(fig)

    if synth and synth.get("points") and synth.get("mode") == "sky130_fd_sc_hd":
        pts = sorted((p for p in synth["points"] if p["N"] == N), key=lambda p: p["ACC_W"])
        ref = next(p["area_um2"] for p in pts if p["ACC_W"] == 32)
        safe = synth.get("min_safe_acc_w_for_k_max")
        fig, ax = plt.subplots(figsize=(5.6, 3.2), dpi=150)
        xs = range(len(pts))
        colors = [blue if p["ACC_W"] == safe else "#b9c7da" for p in pts]
        ax.bar(list(xs), [p["area_um2"] / 1000 for p in pts], width=0.56, color=colors)
        for x, p in zip(xs, pts):
            d = 100 * (p["area_um2"] - ref) / ref
            tag = "baseline" if p["ACC_W"] == 32 else f"{d:.1f}%"
            ax.text(x, p["area_um2"] / 1000 + 4, tag, ha="center", va="bottom", fontsize=8.5)
        ax.set_xticks(list(xs), [f"{p['ACC_W']}-bit" + ("\n(chip)" if p["ACC_W"] == safe else
                                                   "\n(can overflow)" if p["ACC_W"] < safe else "") for p in pts])
        ax.set_ylabel("std-cell area (x1000 um²)")
        ax.set_ylim(0, ref / 1000 * 1.18)
        ax.set_title(f"Accumulator sizing, {N}x{N} array (Yosys, Sky130 HD cells)", loc="left", fontsize=10)
        ax.grid(axis="y", color="#e4e3df", lw=0.6)
        ax.set_axisbelow(True)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()
        fig.savefig(DOCS / "synth_sweep.png")
        plt.close(fig)


def build_rows(ver, cycles, synth, ol, power, thr, formal, pm=None, gls=None):
    v = (ver or {}).get(f"systolic_N{N}_ACC{ACC_W}", {})
    v22 = (ver or {}).get(f"systolic_N{N}_ACC32", {})
    vp0 = (ver or {}).get(f"systolic_N{N}_ACC{ACC_W}_P0I0", {})
    sa = (cycles or {}).get(f"systolic_N{N}", {})
    sp = (cycles or {}).get(f"speedup_N{N}", {})
    rs = (synth or {}).get("right_sizing_savings", {}).get(f"N{N}", {})
    rows = [
        (f"Random matrices checked vs NumPy (N = 8, ACC_W = {ACC_W}, as built)",
         fmt(v.get("random_matrices")), "verification.json"),
        ("Output elements checked / mismatches",
         f"{fmt(v.get('outputs_checked'))} / {fmt(v.get('element_mismatches'))}", "verification.json"),
        ("Directed corner-case tests passed", fmt(v.get("directed_tests_passed")), "verification.json"),
    ]
    if v22:
        rows.append((f"Reference ACC_W = {v22.get('ACC_W')} build: random matrices / mismatches",
                     f"{fmt(v22.get('random_matrices'))} / {fmt(v22.get('element_mismatches'))}",
                     "verification.json"))
    if vp0:
        rows.append(("Single-cycle-MAC variant (PIPE = 0, ISO = 0): random matrices / mismatches",
                     f"{fmt(vp0.get('random_matrices'))} / {fmt(vp0.get('element_mismatches'))}",
                     "verification.json"))
    if formal:
        rows.append(("PE properties proven (k-induction, all inputs)",
                     "pass" if formal.get("proven") else "fail", "formal.json"))
    for k in ("K8", "K16", "K64"):
        if k in sa:
            rows.append((f"Latency, K = {k[1:]} (cycles) / utilization",
                         f"{sa[k]['cycles']} / {sa[k]['utilization_pct']}%", "cycles.json"))
    if "K64" in sp:
        rows.append(("Speedup vs single-MAC baseline, K = 64", f"{sp['K64']}x", "cycles.json"))
    if rs:
        unit = "Sky130 cell area" if rs.get("metric") == "area_um2" else "cell count"
        rows.append((f"Accumulator right-sizing 32 -> {synth['min_safe_acc_w_for_k_max']} bits ({unit}, N = 8)",
                     f"-{rs['saved_pct']}%", "synth_sweep.json"))
    p0 = (synth or {}).get("no_pipeline_reference")
    full = next((p for p in (synth or {}).get("points", [])
                 if p0 and p["N"] == N and p["ACC_W"] == p0.get("ACC_W")), None)
    if p0 and full and "area_um2" in p0:
        rows.append(("Area cost of the PE product register (synthesis)",
                     f"+{100 * (full['area_um2'] - p0['area_um2']) / p0['area_um2']:.1f}%", "synth_sweep.json"))
    if ol:
        rows += [
            ("Clock closed on Sky130 HD, all 9 corners (worst setup slack)",
             f"{fmt(ol.get('clock_mhz'))} MHz ({fmt(ol.get('setup_wns_ns'), 3)} ns)", "openlane.json"),
            ("Setup slack at the typical corner (tt, 25C, 1.80V) / Fmax estimate there",
             f"{fmt(ol.get('setup_wns_tt_ns'), 3)} ns / {fmt(ol.get('fmax_tt_estimate_mhz'))} MHz", "openlane.json"),
            ("Die / std-cell area", f"{fmt(ol.get('die_area_mm2'), 3)} / {fmt(ol.get('stdcell_area_mm2'), 3)} mm²",
             "openlane.json"),
            ("Std cells / utilization", f"{fmt(ol.get('stdcell_count'))} / {fmt(ol.get('utilization'), 2)}",
             "openlane.json"),
            ("DRC errors / LVS errors", f"{fmt(ol.get('drc_errors'))} / {fmt(ol.get('lvs_errors'))}",
             "openlane.json"),
        ]
    else:
        rows.append(("Physical design (Sky130, LibreLane)", "pending", "openlane.json"))
    if thr:
        rows.append(("Peak / effective (K = 64) throughput",
                     f"{thr['peak_gops']} / {thr['effective_gops'].get('K64', 'n/a')} GOPS", "throughput.json"))
    if gls:
        # the chip in openlane.json is the one whose netlist was simulated
        want = (ol or {}).get('run_dir', '')
        key = next((k for k, v in gls.items() if want and want in v.get('netlist', '')), None)
        g = gls.get(key or sorted(gls)[-1])
        rows.append(("Gate-level simulation of the routed netlist: jobs / mismatches",
                     f"{fmt(g.get('random_matrices'))} / {fmt(g.get('element_mismatches'))}", "gls.json"))
    if pm and pm.get("power_mw") is not None:
        rows.append(("Power, measured activity (busy random INT8 workload, typical corner)",
                     f"{pm['power_mw']:.1f} mW", "power_measured.json"))
        rows.append(("Efficiency at peak / energy per MAC",
                     f"{fmt(pm.get('gops_per_w_at_peak'))} GOPS/W / {pm.get('energy_pj_per_mac_at_peak')} pJ",
                     "power_measured.json"))
    elif power and power.get("power_mw") is not None:
        rows.append(("Power (estimated, vectorless) / efficiency at peak",
                     f"{power['power_mw']} mW / {fmt(power.get('gops_per_w_at_peak'))} GOPS/W", "power.json"))
    return rows


def update_readme(rows):
    table = ["| Metric | Value | Source |", "|---|---|---|"]
    table += [f"| {a} | {b} | `results/{c}` |" for a, b, c in rows]
    block = f"{START}\n" + "\n".join(table) + f"\n{END}"
    if not README.exists():
        print("README.md not found; table:\n" + block)
        return
    text = README.read_text()
    if START in text and END in text:
        text = re.sub(re.escape(START) + ".*?" + re.escape(END), block, text, flags=re.S)
        README.write_text(text)
        print("README results table updated")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    ver, cycles, synth = load("verification.json"), load("cycles.json"), load("synth_sweep.json")
    ol, power, formal = load("openlane.json"), load("power.json"), load("formal.json")
    pm, gls = load("power_measured.json"), load("gls.json")
    thr = compute_throughput(cycles, ol)

    rows = build_rows(ver, cycles, synth, ol, power, thr, formal, pm, gls)
    width = max(len(r[0]) for r in rows)
    print("\nRESULTS")
    for a, b, c in rows:
        print(f"  {a:<{width}}  {b:<28} results/{c}")
    update_readme(rows)
    plots(cycles, synth)

    if args.check and any(r[1] == "pending" for r in rows):
        sys.exit("some measurements are still pending")


if __name__ == "__main__":
    main()
