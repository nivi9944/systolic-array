#!/usr/bin/env python3
"""Run the full LibreLane flow at several clock periods -> results/clock_sweep.json.

Run inside the LibreLane nix-shell (or with --dockerized, see --librelane):

    python3 scripts/sweep_clock.py                    # 20, 15, 12, 10, 8 ns
    python3 scripts/sweep_clock.py --periods 20       # single run at 50 MHz
    python3 scripts/sweep_clock.py --periods 10 9 8 --keep-going

Periods are tried from slowest to fastest. By default the sweep stops at the
first period that fails timing or does not finish. The fastest period that
finished DRC/LVS clean with timing met is the "best" point; its metrics are saved
to results/openlane.json and results/power.json, and its layout image is copied
to docs/layout.png if the flow rendered one.
"""

import argparse
import json
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_openlane import summarize_run, save  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OL = ROOT / "openlane"
RESULTS = ROOT / "results"


def run_flow(period, librelane_cmd, extra):
    tag = f"clk_{period:g}".replace(".", "p")
    cfg = json.loads((OL / "config.json").read_text())
    cfg["CLOCK_PERIOD"] = float(period)
    cfg_path = OL / f"config_{tag}.json"
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")
    cmd = shlex.split(librelane_cmd) + [cfg_path.name, "--run-tag", tag, "--overwrite"] + extra
    log = OL / "runs" / f"{tag}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    print(f"\n=== {period} ns ({1000 / period:.1f} MHz): {' '.join(cmd)}")
    t0 = time.time()
    with open(log, "w") as fh:
        rc = subprocess.run(cmd, cwd=OL, stdout=fh, stderr=subprocess.STDOUT).returncode
    minutes = round((time.time() - t0) / 60, 1)
    cfg_path.unlink(missing_ok=True)
    run_dir = OL / "runs" / tag
    point = {"clock_period_ns": period, "clock_mhz": round(1000 / period, 2),
             "exit_code": rc, "runtime_min": minutes, "log": str(log.relative_to(ROOT))}
    if run_dir.exists():
        try:
            point.update(summarize_run(run_dir, period))
        except FileNotFoundError as err:
            point["error"] = str(err)
    point["passed"] = bool(rc == 0 and point.get("flow_completed") and point.get("timing_met")
                           and point.get("drc_lvs_clean"))
    status = "PASS" if point["passed"] else "FAIL"
    print(f"    {status}: exit={rc} wns={point.get('setup_wns_ns')} "
          f"drc={point.get('drc_errors')} lvs={point.get('lvs_errors')} ({minutes} min)")
    return point, run_dir


def copy_layout(run_dir):
    pngs = sorted(Path(run_dir).rglob("*.png"), key=lambda p: p.stat().st_size, reverse=True)
    if pngs:
        (ROOT / "docs").mkdir(exist_ok=True)
        shutil.copy(pngs[0], ROOT / "docs" / "layout.png")
        print(f"copied {pngs[0].relative_to(ROOT)} -> docs/layout.png")
    else:
        print("no rendered PNG in the run; use scripts/render_layout.py to make docs/layout.png")


def keep_final_reports(run_dir):
    """Copy the small signoff files of the best run to openlane/final/ (tracked in git)."""
    dest = OL / "final"
    dest.mkdir(exist_ok=True)
    run_dir = Path(run_dir)
    wanted = {
        "metrics.json": run_dir / "final" / "metrics.json",
        "metrics.csv": run_dir / "final" / "metrics.csv",
        "sta_signoff_summary.rpt": next(iter(sorted(run_dir.glob("*-openroad-stapostpnr/summary.rpt"))), None),
        "drc_magic.rpt": next(iter(sorted(run_dir.glob("*-magic-drc/reports/drc.magic.rpt"))), None),
        "drc_klayout.json": next(iter(sorted(run_dir.glob("*-klayout-drc/reports/drc.klayout.json"))), None),
        "lvs_netgen.rpt": next(iter(sorted(run_dir.glob("*-netgen-lvs/reports/lvs.netgen.rpt"))), None),
    }
    for name, src in wanted.items():
        if src is not None and Path(src).exists():
            shutil.copy(src, dest / name)
    print(f"kept signoff reports in {dest.relative_to(ROOT)}/")


def plot(points):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not available here; summarize.py will draw the plot later")
        return
    ok = [p for p in points if p.get("stdcell_area_mm2")]
    if not ok:
        return
    fig, ax = plt.subplots(figsize=(5, 3.2), dpi=150)
    ax.plot([p["clock_mhz"] for p in ok], [p["stdcell_area_mm2"] for p in ok], "o-")
    for p in ok:
        ax.annotate("met" if p["passed"] else "fail", (p["clock_mhz"], p["stdcell_area_mm2"]),
                    textcoords="offset points", xytext=(4, 4), fontsize=7)
    ax.set_xlabel("target clock (MHz)")
    ax.set_ylabel("std-cell area (mm²)")
    ax.set_title("Area vs clock target (Sky130 HD)")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(ROOT / "docs" / "clock_sweep.png")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--periods", type=float, nargs="+", default=[20, 15, 12, 10, 8])
    ap.add_argument("--librelane", default="librelane",
                    help='command that runs the flow, e.g. "librelane" or "librelane --dockerized"')
    ap.add_argument("--keep-going", action="store_true", help="do not stop at the first failure")
    ap.add_argument("extra", nargs="*", help="extra arguments passed to librelane")
    args = ap.parse_args()

    points, best, best_dir = [], None, None
    for period in sorted(args.periods, reverse=True):
        point, run_dir = run_flow(period, args.librelane, args.extra)
        points.append(point)
        if point["passed"]:
            best, best_dir = point, run_dir
        elif not args.keep_going:
            print("stopping sweep at first failure (use --keep-going to continue)")
            break

    RESULTS.mkdir(exist_ok=True)
    sweep_file = RESULTS / "clock_sweep.json"
    old = json.loads(sweep_file.read_text()) if sweep_file.exists() else {"points": []}
    merged = {p["clock_period_ns"]: p for p in old.get("points", [])}
    merged.update({p["clock_period_ns"]: p for p in points})
    all_points = sorted(merged.values(), key=lambda p: -p["clock_period_ns"])
    passing = [p for p in all_points if p["passed"]]
    summary = {
        **{k: v for k, v in old.items() if k not in ("points", "best_passing_period_ns")},
        "points": all_points,
        "best_passing_period_ns": min((p["clock_period_ns"] for p in passing), default=None),
    }
    sweep_file.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"wrote {sweep_file.relative_to(ROOT)}")
    plot(all_points)

    if best is not None and best["clock_period_ns"] == summary["best_passing_period_ns"]:
        save(summarize_run(best_dir, best["clock_period_ns"]))
        copy_layout(best_dir)
        keep_final_reports(best_dir)
        print(f"best passing clock: {best['clock_mhz']} MHz -> results/openlane.json, results/power.json")
    elif not passing:
        print("no passing run yet: check the logs in openlane/runs/")
        sys.exit(1)


if __name__ == "__main__":
    main()
