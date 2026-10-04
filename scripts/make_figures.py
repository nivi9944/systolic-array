#!/usr/bin/env python3
"""Figures for the README from the signoff reports and results/*.json.

    python3 scripts/make_figures.py                     # timing and closure plots
    python3 scripts/make_figures.py --layout FULL DETAIL # also the layout figure

FULL and DETAIL are PNG renders made with scripts/render_layout.py:
    klayout -b -r scripts/render_layout.py -rd gds=<gds> -rd out=full.png \
        -rd width=1600 -rd zoom=0,0,<die_w>,<die_h>
    klayout -b -r scripts/render_layout.py -rd gds=<gds> -rd out=detail.png \
        -rd width=1200 -rd cells=1 -rd zoom=600,600,660,640
"""

import argparse
import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
RES = ROOT / "results"

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"

plt.rcParams.update({
    "font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK2, "axes.titlecolor": INK,
    "axes.titlesize": 10, "axes.titleweight": "bold",
})


def corners():
    """Per-corner (hold, setup) worst slack from the signoff STA summary."""
    rows = []
    for line in (ROOT / "openlane/final/sta_signoff_summary.rpt").read_text().splitlines():
        cells = [c.strip() for c in re.split(r"[│┃]", line) if c.strip()]
        if len(cells) >= 7 and re.match(r"(nom|min|max)_(tt|ss|ff)_", cells[0]):
            rows.append((cells[0], float(cells[1]), float(cells[6])))
    return rows


def label(corner):
    rc, proc = corner.split("_")[0], corner.split("_")[1]
    names = {"tt": "typical", "ss": "slow", "ff": "fast"}
    return f"{names[proc]}, {rc} RC"


def slack_plot():
    rows = corners()
    order = sorted(rows, key=lambda r: r[2])
    ys = range(len(order))
    ol = json.loads((RES / "openlane.json").read_text())
    fig, (a, b) = plt.subplots(1, 2, figsize=(8.6, 3.4), dpi=160, sharey=True)
    for ax, idx, color, title in ((a, 2, BLUE, "Setup slack (ns)"), (b, 1, AQUA, "Hold slack (ns)")):
        vals = [r[idx] for r in order]
        ax.barh(list(ys), vals, height=0.62, color=color)
        for y, v in zip(ys, vals):
            ax.text(v, y, f" {v:.2f}", va="center", ha="left", fontsize=8, color=INK)
        ax.axvline(0, color=INK2, lw=0.8)
        ax.set_title(title, loc="left")
        ax.set_xlim(0, max(vals) * 1.22)
        ax.grid(axis="x", color=GRID, lw=0.6)
        ax.set_axisbelow(True)
        ax.spines[["top", "right"]].set_visible(False)
    a.set_yticks(list(ys), [label(r[0]) for r in order])
    fig.suptitle(f"Post-route signoff at {ol['clock_mhz']:.1f} MHz: positive slack at all 9 PVT and parasitic corners",
                 x=0.01, ha="left", fontsize=10.5, fontweight="bold", color=INK)
    fig.text(0.01, 0.01, "Corners: slow = ss 100C 1.60V, typical = tt 25C 1.80V, fast = ff -40C 1.95V; "
             "min / nom / max wire parasitics. Source: openlane/final/sta_signoff_summary.rpt",
             fontsize=7.5, color=INK2)
    fig.tight_layout(rect=(0, 0.04, 1, 0.97))
    fig.savefig(DOCS / "signoff_slack.png")
    plt.close(fig)


def closure_plot():
    sweep = json.loads((RES / "clock_sweep.json").read_text())
    ol = json.loads((RES / "openlane.json").read_text())
    prev = next(p for p in sweep["previous_design_62p5MHz"]["points"] if p.get("passed"))
    first = sweep["first_design_run"]
    stages = [
        ("First design\n(single-cycle MAC)", first["fmax_estimate_mhz"], "#b9b8b3",
         f"{first['fmax_estimate_mhz']:.1f} MHz\n(estimate, did not close\nat the 50 MHz target)"),
        ("Pipelined PE,\nregistered control", prev["clock_mhz"], "#8fb8ea", f"{prev['clock_mhz']:.1f} MHz"),
        ("Final chip", ol["clock_mhz"], BLUE, f"{ol['clock_mhz']:.1f} MHz"),
    ]
    fig, ax = plt.subplots(figsize=(6.4, 3.3), dpi=160)
    xs = range(len(stages))
    ax.bar(list(xs), [s[1] for s in stages], width=0.56, color=[s[2] for s in stages])
    for x, s in zip(xs, stages):
        ax.text(x, s[1] + 2, s[3], ha="center", va="bottom", fontsize=8.5, color=INK)
    ax.set_xticks(list(xs), [s[0] for s in stages])
    ax.set_ylabel("clock met at all 9 corners (MHz)")
    ax.set_ylim(0, ol["clock_mhz"] * 1.3)
    ax.set_title("Signoff clock across design iterations", loc="left")
    ax.grid(axis="y", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(DOCS / "timing_closure.png")
    plt.close(fig)


def layout_figure(full, detail):
    import matplotlib.image as mpimg
    from matplotlib.patches import ConnectionPatch, Rectangle

    ol = json.loads((RES / "openlane.json").read_text())
    m = json.loads((ROOT / "openlane/final/metrics.json").read_text())
    _, _, w, h = [float(v) for v in m["design__die__bbox"].split()]
    zx0, zy0, zx1, zy1 = 600, 600, 660, 640
    bg, fg, fg2 = "#0E1117", "#ffffff", "#c3c2b7"
    fig = plt.figure(figsize=(12, 6.4), dpi=150, facecolor=bg)
    a = fig.add_axes([0.02, 0.11, 0.47, 0.8])
    b = fig.add_axes([0.51, 0.11, 0.47, 0.8])
    a.imshow(mpimg.imread(full), extent=[0, w, 0, h])
    a.set_xlim(0, w)
    a.set_ylim(0, h)
    b.imshow(mpimg.imread(detail), extent=[zx0, zx1, zy0, zy1])
    b.set_xlim(zx0, zx1)
    b.set_ylim(zy0, zy1)
    for ax in (a, b):
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_color("#5b6270")
    a.add_patch(Rectangle((zx0, zy0), zx1 - zx0, zy1 - zy0, fill=False, ec=fg, lw=1.4))
    for ya in (zy1, zy0):
        fig.add_artist(ConnectionPatch((zx1, ya), (zx0, ya), "data", "data", axesA=a, axesB=b,
                                       color=fg, lw=0.8, alpha=0.6))
    a.plot([60, 260], [45, 45], color=fg, lw=2.5)
    a.text(160, 62, "200 µm", color=fg, ha="center", va="bottom", fontsize=9)
    b.plot([zx1 - 13, zx1 - 3], [zy0 + 2, zy0 + 2], color=fg, lw=2.5)
    b.text(zx1 - 8, zy0 + 2.6, "10 µm", color=fg, ha="center", va="bottom", fontsize=9,
           bbox=dict(facecolor=bg, edgecolor="none", pad=1.5))
    fig.text(0.02, 0.94, f"Full chip: {w / 1000:.2f} x {h / 1000:.2f} mm, {ol['stdcell_count']:,} standard cells",
             color=fg, fontsize=10.5)
    fig.text(0.51, 0.94, "Detail, 60 x 40 µm: cell rows, poly and diffusion under the routing",
             color=fg, fontsize=10.5)
    x = 0.02
    for name, c in [("met1", "#3987E5"), ("met2", "#1BAF7A"), ("met3", "#EDA100"), ("met4", "#E87BA4"),
                    ("met5", "#9085E9"), ("poly", "#D84343"), ("diffusion", "#2E7D32")]:
        fig.patches.append(Rectangle((x, 0.045), 0.012, 0.022, transform=fig.transFigure, color=c))
        fig.text(x + 0.016, 0.05, name, color=fg2, fontsize=9)
        x += 0.085
    fig.savefig(DOCS / "layout.png", facecolor=bg)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--layout", nargs=2, metavar=("FULL", "DETAIL"))
    args = ap.parse_args()
    DOCS.mkdir(exist_ok=True)
    slack_plot()
    closure_plot()
    if args.layout:
        layout_figure(*args.layout)
    print("figures written to docs/")


if __name__ == "__main__":
    main()
