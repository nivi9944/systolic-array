#!/usr/bin/env python3
"""Simulate one 4x4, K = 4 job (tb/wave_tb.v) and draw docs/waveform.png.

    python3 scripts/make_waveform.py

Needs iverilog and matplotlib. The same wave.vcd can be opened in GTKWave.
"""

import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RTL = ["pe.v", "skew.v", "systolic_array.v", "controller.v", "sa_top.v"]
N, ACC_W = 4, 32


def parse_vcd(path):
    """Minimal VCD reader: returns {full_name: [(time, value_str), ...]}."""
    ids, scope, data = {}, [], {}
    lines = Path(path).read_text().split("\n")
    t = 0
    in_defs = True
    for line in lines:
        tok = line.split()
        if not tok:
            continue
        if in_defs:
            if tok[0] == "$scope":
                scope.append(tok[2])
            elif tok[0] == "$upscope":
                scope.pop()
            elif tok[0] == "$var":
                code, name = tok[3], tok[4]
                ids.setdefault(code, []).append(".".join(scope + [name]))
            elif tok[0] == "$enddefinitions":
                in_defs = False
            continue
        if tok[0].startswith("#"):
            t = int(tok[0][1:])
        elif tok[0][0] in "bB":
            for name in ids.get(tok[1], []):
                data.setdefault(name, []).append((t, tok[0][1:]))
        elif tok[0][0] in "01xzXZ":
            for name in ids.get(tok[0][1:], []):
                data.setdefault(name, []).append((t, tok[0][0]))
    return data


def value_at(changes, t):
    v = changes[0][1]
    for ct, cv in changes:
        if ct > t:
            break
        v = cv
    return v


def to_int(bits, width=None, signed=False):
    if any(c in "xXzZ" for c in bits):
        return None
    v = int(bits, 2)
    width = width or len(bits)
    if signed and v >= 1 << (width - 1):
        v -= 1 << width
    return v


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    with tempfile.TemporaryDirectory() as tmp:
        srcs = [str(ROOT / "rtl" / f) for f in RTL] + [str(ROOT / "tb" / "wave_tb.v")]
        subprocess.run(["iverilog", "-g2005", "-o", f"{tmp}/wave.vvp", *srcs], check=True)
        subprocess.run(["vvp", "-n", f"{tmp}/wave.vvp"], cwd=tmp, check=True, capture_output=True)
        data = parse_vcd(f"{tmp}/wave.vcd")

    period = 10000  # 10 ns in ps
    t_start = min(t for t, v in data["wave_tb.start"] if v == "1") - period // 2
    t_done = max(t for t, v in data["wave_tb.done"] if v == "1")
    samples = list(range(t_start + period // 2, t_done + 2 * period, period))  # mid-cycle (after negedge drive)

    def bit(name):
        return [int(value_at(data[name], t) == "1") for t in samples]

    def lane(name, idx, width, signed=True):
        out = []
        for t in samples:
            bits = value_at(data[name], t).rjust(width * N, "0")
            chunk = bits[len(bits) - (idx + 1) * width: len(bits) - idx * width]
            out.append(to_int(chunk, width, signed))
        return out

    rows = [
        ("start", bit("wave_tb.start"), "bit"),
        ("s_valid", bit("wave_tb.s_valid"), "bit"),
        ("A row 0 at PE(0,0)", lane("wave_tb.dut.a_skewed", 0, 8), "bus"),
        ("A row 3 at PE(3,0)", lane("wave_tb.dut.a_skewed", 3, 8), "bus"),
        ("B col 3 at PE(0,3)", lane("wave_tb.dut.b_skewed", 3, 8), "bus"),
        ("acc of PE(0,3), then C[i][3]", lane("wave_tb.m_data", 3, ACC_W), "bus"),
        ("m_valid", bit("wave_tb.m_valid"), "bit"),
        ("done", bit("wave_tb.done"), "bit"),
    ]

    n = len(samples)
    fig, ax = plt.subplots(figsize=(10, 4.2), dpi=150)
    for r, (name, vals, kind) in enumerate(rows):
        y = (len(rows) - r) * 1.3
        ax.text(-0.3, y + 0.35, name, ha="right", va="center", fontsize=8.5)
        if kind == "bit":
            xs, ys = [], []
            for i, v in enumerate(vals):
                xs += [i, i + 1]
                ys += [y + 0.7 * v, y + 0.7 * v]
            ax.plot(xs, ys, color="#2a6fdb", lw=1.4)
        else:
            i = 0
            while i < n:
                j = i
                while j + 1 < n and vals[j + 1] == vals[i]:
                    j += 1
                v = vals[i]
                color = "#e8eef9" if v not in (0, None) else "#f5f5f5"
                ax.add_patch(plt.Polygon([(i + 0.08, y + 0.35), (i + 0.2, y + 0.7), (j + 0.8, y + 0.7),
                                          (j + 0.92, y + 0.35), (j + 0.8, y), (i + 0.2, y)],
                                         closed=True, fc=color, ec="#2a6fdb", lw=0.9))
                if v is not None:
                    ax.text((i + j + 1) / 2, y + 0.35, "" if v is None else str(v),
                            ha="center", va="center", fontsize=7.5)
                i = j + 1
    for i in range(n + 1):
        ax.axvline(i, color="#dddddd", lw=0.5, zorder=0)
    ax.set_xlim(-0.1, n + 0.1)
    ax.set_ylim(0.8, (len(rows) + 1) * 1.3)
    ax.set_yticks([])
    ax.set_xticks([i + 0.5 for i in range(n)], [str(i) for i in range(n)], fontsize=7)
    ax.set_xlabel("clock cycle after start")
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.set_title("4x4 array, K = 4: skewed inputs, accumulation, then drain (row 0, 1, 2, 3 of C)",
                 fontsize=9.5)
    fig.tight_layout()
    (ROOT / "docs").mkdir(exist_ok=True)
    fig.savefig(ROOT / "docs" / "waveform.png", bbox_inches="tight")
    print("wrote docs/waveform.png")


if __name__ == "__main__":
    main()
