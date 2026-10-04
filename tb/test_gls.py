"""Gate-level simulation of the routed netlist: random jobs checked against NumPy.

Run through the Makefile (TB=gls). NUM_RANDOM jobs with random K in [1, K_MAX],
a quarter of them with random input bubbles and output back-pressure. With
GLS_POWER=1 it instead runs back-to-back K = K_MAX jobs at full throughput (a
realistic busy workload) while the netlist is dumped to gls.vcd for power
analysis.
"""

import os
import time

import numpy as np
import cocotb

from ref_model import matmul_ref, random_int8
from harness import N, ACC_W, K_MAX, start_clock_and_reset, run_job, update_json, env_int

NUM_RANDOM = env_int("NUM_RANDOM", 200)
SEED = env_int("SEED", 2027)
POWER = env_int("GLS_POWER", 0)
TAG = os.environ.get("GLS_RESULT_KEY", "chip")


@cocotb.test()
async def test_gls(dut):
    rng = np.random.default_rng(SEED + 7)
    await start_clock_and_reset(dut)
    t0 = time.time()
    mismatches = bad = 0
    for n in range(NUM_RANDOM):
        k = K_MAX if POWER else int(rng.integers(1, K_MAX + 1))
        a = random_int8(rng, (N, k))
        b = random_int8(rng, (k, N))
        stress = (not POWER) and rng.random() < 0.25
        c_hw, _, _ = await run_job(dut, a, b, rng=rng,
                                   p_bubble=0.3 if stress else 0.0, p_stall=0.3 if stress else 0.0)
        e = int(np.count_nonzero(c_hw != matmul_ref(a, b, ACC_W)))
        mismatches += e
        bad += int(e > 0)
    if not POWER:
        update_json("gls.json", TAG, {
            "netlist": os.environ.get("GLS_NETLIST", ""), "N": N, "ACC_W": ACC_W,
            "random_matrices": NUM_RANDOM, "outputs_checked": NUM_RANDOM * N * N,
            "element_mismatches": mismatches, "matrices_with_mismatch": bad,
            "sim_seconds": round(time.time() - t0, 1),
            "models": "sky130_fd_sc_hd functional Verilog models, zero delay",
        })
    assert mismatches == 0, f"{mismatches} mismatches in {bad} matrices"
