"""Shared cocotb driver for sa_top and seq_mac_baseline (identical ports).

Output protocol: ready latency 1. A row transfers in every cycle where m_valid
is high, and the DUT may only raise m_valid if m_ready was high the cycle before
(the driver checks this).

run_job() streams one matrix job through the valid/ready ports, optionally with
random input bubbles and output back-pressure, and returns the C matrix the DUT
produced plus the cycle count from the start pulse to the done pulse.
"""

import os
import json
from pathlib import Path

import numpy as np
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly

from ref_model import pack, unpack, DATA_W

RESULTS_DIR = Path(os.environ.get("RESULTS_DIR", Path(__file__).resolve().parent.parent / "results"))


def env_int(name, default):
    return int(os.environ.get(name, default))


N = env_int("N", 8)
ACC_W = env_int("ACC_W", 32)
K_MAX = env_int("K_MAX", 64)
CLK_NS = float(os.environ.get("CLK_NS", 10))


async def start_clock_and_reset(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    dut.rst_n.value = 0
    dut.start.value = 0
    dut.k_len.value = 0
    dut.s_valid.value = 0
    dut.s_a.value = 0
    dut.s_b.value = 0
    dut.m_ready.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def run_job(dut, a, b, k_len=None, p_bubble=0.0, p_stall=0.0, rng=None,
                  timeout=200000):
    """Run one job. a is N x K, b is K x N. Returns (C as np.int64 array, cycles, beats).

    k_len defaults to K (the number of columns of a). If k_len is larger than
    the hardware K_MAX, the DUT clamps it and only accepts K_MAX beats; we keep
    offering beats and count how many were really accepted.
    """
    rng = rng or np.random.default_rng()
    a = np.asarray(a)
    b = np.asarray(b)
    k = a.shape[1]
    k_len = k if k_len is None else k_len
    beats_a = [pack(a[:, kk], DATA_W) for kk in range(k)]
    beats_b = [pack(b[kk, :], DATA_W) for kk in range(k)]

    rows = []
    beat = 0
    cycles = 0
    prev_ready = 0      # output uses ready latency 1

    # Cycle 0: pulse start.
    dut.start.value = 1
    dut.k_len.value = k_len
    dut.s_valid.value = 0
    dut.m_ready.value = 0
    while True:
        await ReadOnly()
        cycles += 1
        s_fire = int(dut.s_valid.value) and int(dut.s_ready.value)
        m_fire = int(dut.m_valid.value)
        if m_fire and not prev_ready:
            raise AssertionError("m_valid raised although m_ready was low in the previous cycle")
        prev_ready = int(dut.m_ready.value)
        if m_fire:
            rows.append(unpack(dut.m_data.value.to_unsigned(), N, ACC_W))
            if bool(int(dut.m_last.value)) != (len(rows) == N):
                raise AssertionError(f"m_last wrong on output row {len(rows) - 1}")
        is_done = int(dut.done.value)
        await RisingEdge(dut.clk)
        if s_fire:
            beat += 1
        if is_done:
            break
        if cycles > timeout:
            raise TimeoutError("job did not finish")
        # Drive inputs for the next cycle.
        dut.start.value = 0
        offer = beat < k and rng.random() >= p_bubble
        dut.s_valid.value = 1 if offer else 0
        dut.s_a.value = beats_a[beat] if beat < k else 0
        dut.s_b.value = beats_b[beat] if beat < k else 0
        dut.m_ready.value = 0 if rng.random() < p_stall else 1

    dut.s_valid.value = 0
    dut.m_ready.value = 0
    if len(rows) != N:
        raise AssertionError(f"expected {N} output rows, got {len(rows)}")
    return np.array(rows, dtype=np.int64), cycles, beat


def update_json(name, key, value):
    """Read-modify-write a results/*.json file so tests can share one file."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / name
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            data = {}
    data[key] = value
    path.write_text(json.dumps(data, indent=2) + "\n")
    return data
