#!/usr/bin/env python3
"""Read the metrics of one LibreLane / OpenLane 2 run and return clean numbers.

    python3 scripts/collect_openlane.py openlane/runs/clk_20      # print a summary
    python3 scripts/collect_openlane.py openlane/runs/clk_20 --save   # also write
                                              # results/openlane.json + results/power.json

Only the Python standard library is used, so this runs inside the LibreLane
nix-shell as well as in a normal venv. Metric names differ slightly between
LibreLane versions, so every lookup tries several names and the raw key that was
used is recorded next to each value.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
NOM_CORNER = "nom_tt_025C_1v80"


def load_metrics(run_dir):
    run_dir = Path(run_dir)
    for cand in [run_dir / "final" / "metrics.json", *sorted(run_dir.glob("*/metrics.json"))[-1:]]:
        if cand.exists():
            return json.loads(cand.read_text()), cand
    raise FileNotFoundError(f"no metrics.json under {run_dir}")


def pick(metrics, *names, corner=None):
    """First metric found among names (optionally the corner-specific variant)."""
    for name in names:
        if corner and f"{name}__corner:{corner}" in metrics:
            return metrics[f"{name}__corner:{corner}"], f"{name}__corner:{corner}"
        if name in metrics:
            return metrics[name], name
    return None, None


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def read_config_period(run_dir):
    """Clock period actually used by the run (from its resolved config)."""
    for cand in [Path(run_dir) / "resolved.json", *Path(run_dir).glob("*/config.json")]:
        if cand.exists():
            try:
                cfg = json.loads(cand.read_text())
                if "CLOCK_PERIOD" in cfg:
                    return float(cfg["CLOCK_PERIOD"])
            except (json.JSONDecodeError, ValueError):
                pass
    return None


def read_synth_params(run_dir):
    cand = Path(run_dir) / "resolved.json"
    if cand.exists():
        try:
            return json.loads(cand.read_text()).get("SYNTH_PARAMETERS")
        except json.JSONDecodeError:
            return None
    return None


def tt_power_from_report(run_dir, stage_dirs=()):
    """Power at the typical corner from the post-route STA report (watts), or None.

    metrics.json only carries one 'power__total' value, which LibreLane takes from
    a different corner, so the typical-corner report is read directly.
    """
    reps = []
    for d in (run_dir, *stage_dirs):
        reps = reps or sorted(Path(d).glob(f"*-openroad-stapostpnr/{NOM_CORNER}/power.rpt"))
    if not reps:
        return None
    vals = {}
    for line in reps[-1].read_text().splitlines():
        parts = line.split()
        if parts and parts[0] in ("Sequential", "Combinational", "Clock", "Total") and len(parts) >= 5:
            try:
                vals[parts[0]] = [float(x) for x in parts[1:5]]
            except ValueError:
                pass
    if "Total" not in vals:
        return None
    internal, switching, leakage, total = vals["Total"]
    return {"total": total, "internal": internal, "switching": switching, "leakage": leakage,
            "groups": {k: v[3] for k, v in vals.items() if k != "Total"}}


def rel(d):
    d = Path(d).resolve()
    return str(d.relative_to(ROOT)) if d.is_relative_to(ROOT) else str(d)


def summarize_run(run_dir, period_ns=None, n=8, stage_dirs=()):
    """stage_dirs: earlier runs of the same chip when the flow was resumed in stages
    (their step reports are searched when a report is not in run_dir)."""
    m, path = load_metrics(run_dir)
    period_ns = period_ns or read_config_period(run_dir)
    used = {}

    def get(label, *names, corner=None):
        val, key = pick(m, *names, corner=corner)
        if key:
            used[label] = key
        return num(val)

    setup_ws = get("setup_wns_ns", "timing__setup__ws")
    setup_tt = get("setup_wns_tt_ns", f"timing__setup__ws__corner:{NOM_CORNER}")
    setup_ss = get("setup_wns_ss_ns", "timing__setup__ws__corner:max_ss_100C_1v60")
    slew_vio = get("max_slew_violations", "design__max_slew_violation__count")
    cap_vio = get("max_cap_violations", "design__max_cap_violation__count")
    setup_tns = get("setup_tns_ns", "timing__setup__tns")
    hold_ws = get("hold_wns_ns", "timing__hold__ws")
    setup_vio = get("setup_violations", "timing__setup_vio__count")
    hold_vio = get("hold_violations", "timing__hold_vio__count")
    die_area = get("die_area_um2", "design__die__area")
    core_area = get("core_area_um2", "design__core__area")
    cell_area = get("stdcell_area_um2", "design__instance__area__stdcell", "design__instance__area")
    cells = get("stdcell_count", "design__instance__count__stdcell", "design__instance__count")
    util = get("utilization", "design__instance__utilization__stdcell", "design__instance__utilization")
    magic_drc = get("magic_drc_errors", "magic__drc_error__count")
    klayout_drc = get("klayout_drc_errors", "klayout__drc_error__count")
    route_drc = get("route_drc_errors", "route__drc_errors")
    lvs = get("lvs_errors", "design__lvs_error__count")
    antenna = get("antenna_violating_nets", "antenna__violating__nets")
    tt = tt_power_from_report(run_dir, stage_dirs)
    if tt:
        p_total, p_int, p_sw, p_leak = tt["total"], tt["internal"], tt["switching"], tt["leakage"]
        used["power_w"] = f"{NOM_CORNER}/power.rpt (post-route STA)"
    else:
        p_total = get("power_total_w", "power__total", corner=NOM_CORNER)
        p_int = get("power_internal_w", "power__internal__total", corner=NOM_CORNER)
        p_sw = get("power_switching_w", "power__switching__total", corner=NOM_CORNER)
        p_leak = get("power_leakage_w", "power__leakage__total", corner=NOM_CORNER)

    drc_values = [v for v in (magic_drc, klayout_drc, route_drc) if v is not None]
    gds = list(Path(run_dir).glob("final/gds/*.gds")) or list(Path(run_dir).glob("final/*/*.gds"))
    timing_met = (setup_ws is not None and setup_ws >= 0 and
                  (hold_ws is None or hold_ws >= 0))

    out = {
        "run_dir": str(Path(run_dir).resolve().relative_to(ROOT)) if Path(run_dir).resolve().is_relative_to(ROOT) else str(run_dir),
        "metrics_file": str(path.name),
        "stage_dirs": [rel(d) for d in stage_dirs],
        "synth_parameters": read_synth_params(run_dir),
        "flow_completed": bool(gds),
        "clock_period_ns": period_ns,
        "clock_mhz": round(1000.0 / period_ns, 2) if period_ns else None,
        "setup_wns_ns": setup_ws,
        "setup_tns_ns": setup_tns,
        "setup_wns_tt_ns": setup_tt,
        "setup_wns_ss_ns": setup_ss,
        "timing_corners": "worst of 9 corners (ss/tt/ff x min/nom/max RC); tt = typical 25C 1.80V, ss = slow 100C 1.60V",
        "hold_wns_ns": hold_ws,
        "setup_violations": setup_vio,
        "hold_violations": hold_vio,
        "timing_met": timing_met,
        # Estimate only: the period could shrink by the positive setup slack.
        "fmax_estimate_mhz": (round(1000.0 / (period_ns - setup_ws), 1)
                              if period_ns and setup_ws is not None and period_ns - setup_ws > 0 else None),
        "fmax_tt_estimate_mhz": (round(1000.0 / (period_ns - setup_tt), 1)
                                 if period_ns and setup_tt is not None and period_ns - setup_tt > 0 else None),
        "max_slew_violations": int(slew_vio) if slew_vio is not None else None,
        "max_cap_violations": int(cap_vio) if cap_vio is not None else None,
        "die_area_mm2": round(die_area / 1e6, 4) if die_area else None,
        "core_area_mm2": round(core_area / 1e6, 4) if core_area else None,
        "stdcell_area_mm2": round(cell_area / 1e6, 4) if cell_area else None,
        "stdcell_count": int(cells) if cells is not None else None,
        "utilization": util,
        "drc_errors": int(sum(drc_values)) if drc_values else None,
        "lvs_errors": int(lvs) if lvs is not None else None,
        "antenna_violating_nets": int(antenna) if antenna is not None else None,
        "drc_lvs_clean": bool(gds) and bool(drc_values) and sum(drc_values) == 0 and lvs == 0,
        "power_w": {"total": p_total, "internal": p_int, "switching": p_sw, "leakage": p_leak},
        "metric_keys_used": used,
    }
    missing = [k for k in ("setup_wns_ns", "die_area_mm2", "lvs_errors", "power_w") if out.get(k) in (None, {})]
    if missing:
        out["warning"] = f"missing metrics: {missing}; check {path} key names"
    return out


def save(summary, n=8):
    RESULTS.mkdir(exist_ok=True)
    ol = {k: v for k, v in summary.items() if k != "power_w"}
    (RESULTS / "openlane.json").write_text(json.dumps(ol, indent=2) + "\n")
    p = summary["power_w"]["total"]
    f_mhz = summary["clock_mhz"]
    power = {
        "source": "OpenROAD/OpenSTA power report at signoff, nominal corner (tt, 25C, 1.80V)",
        "activity": "vectorless: default switching activity assumed by the tool, no simulation VCD",
        "label": "estimated",
        "clock_mhz": f_mhz,
        "power_mw": round(p * 1000, 3) if p is not None else None,
        "internal_mw": round(summary["power_w"]["internal"] * 1000, 3) if summary["power_w"]["internal"] is not None else None,
        "switching_mw": round(summary["power_w"]["switching"] * 1000, 3) if summary["power_w"]["switching"] is not None else None,
        "leakage_mw": round(summary["power_w"]["leakage"] * 1000, 6) if summary["power_w"]["leakage"] is not None else None,
    }
    if p and f_mhz:
        peak_gops = 2 * n * n * f_mhz / 1000.0
        power["peak_gops"] = round(peak_gops, 3)
        power["gops_per_w_at_peak"] = round(peak_gops / p, 1)
    (RESULTS / "power.json").write_text(json.dumps(power, indent=2) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--period", type=float, default=None, help="clock period in ns, if not in the run config")
    ap.add_argument("--stages", nargs="*", default=[], help="earlier runs of the same chip (resumed flow)")
    ap.add_argument("--save", action="store_true", help="write results/openlane.json and results/power.json")
    args = ap.parse_args()
    s = summarize_run(args.run_dir, args.period, stage_dirs=args.stages)
    print(json.dumps(s, indent=2))
    if args.save:
        if not s["flow_completed"]:
            sys.exit("flow did not complete (no final GDS); not saving")
        save(s)
        print("saved results/openlane.json and results/power.json")


if __name__ == "__main__":
    main()
