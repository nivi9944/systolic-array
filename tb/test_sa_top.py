"""cocotb tests for sa_top: directed corner cases, 10,000 random matrices, cycle counts.

Environment knobs (set by tb/Makefile):
  N, ACC_W, K_MAX   hardware parameters (must match the compiled RTL)
  NUM_RANDOM        number of random matrices (default 10000)
  SEED              random seed (default 2027)
  DESIGN            name used in results files ("systolic" or "baseline")
  PIPE              1 = product register in each PE (default), 0 = single-cycle MAC
"""

import os
import time

import numpy as np
import cocotb

from ref_model import matmul_ref, random_int8, min_safe_acc_w
from harness import (N, ACC_W, K_MAX, start_clock_and_reset, run_job,
                     update_json, env_int)

NUM_RANDOM = env_int("NUM_RANDOM", 10000)
SEED = env_int("SEED", 2027)
DESIGN = os.environ.get("DESIGN", "systolic")
PIPE = env_int("PIPE", 1)
ISO = env_int("ISO", 1)
# Variants other than the chip configuration (PIPE = 1, ISO = 1) get their own keys.
VARIANT = f"_P{PIPE}I{ISO}" if (DESIGN == "systolic" and (PIPE, ISO) != (1, 1)) else ""
RESULT_KEY = f"{DESIGN}_N{N}_ACC{ACC_W}{VARIANT}"


def check(c_hw, a, b, label):
    c_ref = matmul_ref(a, b, ACC_W)
    bad = int(np.count_nonzero(c_hw != c_ref))
    if bad:
        idx = np.argwhere(c_hw != c_ref)[0]
        i, j = int(idx[0]), int(idx[1])
        raise AssertionError(
            f"{label}: {bad} mismatches, first C[{i}][{j}] hw={c_hw[i, j]} ref={c_ref[i, j]}")
    return bad


def directed_cases(rng):
    """(name, A, B, k_len override or None)."""
    cases = []
    eye = np.eye(N, dtype=np.int64)
    rb = random_int8(rng, (N, N))
    cases.append(("identity_x_random", eye, rb, None))
    cases.append(("random_x_identity", rb, eye, None))
    cases.append(("zeros", np.zeros((N, K_MAX), np.int64), np.zeros((K_MAX, N), np.int64), None))
    cases.append(("all_minus128_kmax", np.full((N, K_MAX), -128), np.full((K_MAX, N), -128), None))
    cases.append(("all_127_kmax", np.full((N, K_MAX), 127), np.full((K_MAX, N), 127), None))
    cases.append(("minus128_x_127_kmax", np.full((N, K_MAX), -128), np.full((K_MAX, N), 127), None))
    cases.append(("k_equals_1", random_int8(rng, (N, 1)), random_int8(rng, (1, N)), None))
    # One-hot: exactly one non-zero product lands in each C[i][j] position in turn.
    for (i, j, kk) in [(0, 0, 0), (N - 1, N - 1, 0), (0, N - 1, 3), (N - 1, 0, 5), (N // 2, N // 2, 7)]:
        a = np.zeros((N, 8), np.int64)
        b = np.zeros((8, N), np.int64)
        a[i, kk] = -128
        b[kk, j] = -128
        cases.append((f"one_hot_{i}_{j}_k{kk}", a, b, None))
    # Checkerboard of extremes exercises sign handling in every PE.
    ext = np.where((np.add.outer(np.arange(N), np.arange(K_MAX)) % 2) == 0, 127, -128)
    cases.append(("checkerboard_extremes", ext, ext.T.copy(), None))
    return cases


@cocotb.test()
async def test_directed(dut):
    """Corner cases: identity, zeros, INT8 extremes, K = 1, one-hot, empty job, K clamp."""
    rng = np.random.default_rng(SEED)
    await start_clock_and_reset(dut)
    passed = 0
    for name, a, b, k_len in directed_cases(rng):
        c_hw, _, _ = await run_job(dut, a, b, k_len=k_len, rng=rng)
        check(c_hw, a, b, name)
        passed += 1
        dut._log.info(f"PASS {name}")

    # Empty job (K = 0): no beats accepted, result is all zeros.
    empty_a = np.zeros((N, 0), np.int64)
    empty_b = np.zeros((0, N), np.int64)
    c_hw, _, beats = await run_job(dut, empty_a, empty_b, rng=rng)
    assert beats == 0 and not c_hw.any(), "K = 0 job must return zeros"
    passed += 1
    dut._log.info("PASS empty_job_k0")

    # K larger than K_MAX is clamped: only K_MAX beats are accepted.
    k_big = min(K_MAX + 5, (1 << 7) - 1)
    a = random_int8(rng, (N, k_big))
    b = random_int8(rng, (k_big, N))
    c_hw, _, beats = await run_job(dut, a, b, rng=rng)
    assert beats == K_MAX, f"expected {K_MAX} beats after clamp, got {beats}"
    check(c_hw, a[:, :K_MAX], b[:K_MAX, :], "k_clamp")
    passed += 1
    dut._log.info("PASS k_clamp_to_kmax")

    # Bubbles and back-pressure on a full-size job.
    a = random_int8(rng, (N, K_MAX))
    b = random_int8(rng, (K_MAX, N))
    c_hw, _, _ = await run_job(dut, a, b, p_bubble=0.5, p_stall=0.5, rng=rng)
    check(c_hw, a, b, "heavy_bubbles_and_backpressure")
    passed += 1
    dut._log.info("PASS heavy_bubbles_and_backpressure")

    update_json("verification.json", RESULT_KEY,
                {**_load(RESULT_KEY), "directed_tests_passed": passed})


def _load(key):
    import json
    from harness import RESULTS_DIR
    p = RESULTS_DIR / "verification.json"
    if p.exists():
        try:
            return json.loads(p.read_text()).get(key, {})
        except json.JSONDecodeError:
            return {}
    return {}


@cocotb.test()
async def test_random(dut):
    """NUM_RANDOM random matrices with random K in [1, K_MAX]; a quarter of them
    also get random input bubbles and output back-pressure."""
    rng = np.random.default_rng(SEED + 1)
    await start_clock_and_reset(dut)
    mismatches = 0
    bad_matrices = 0
    stressed = 0
    t0 = time.time()
    for n in range(NUM_RANDOM):
        k = int(rng.integers(1, K_MAX + 1))
        a = random_int8(rng, (N, k))
        b = random_int8(rng, (k, N))
        stress = rng.random() < 0.25
        stressed += int(stress)
        c_hw, _, _ = await run_job(dut, a, b, rng=rng,
                                   p_bubble=0.3 if stress else 0.0,
                                   p_stall=0.3 if stress else 0.0)
        bad = int(np.count_nonzero(c_hw != matmul_ref(a, b, ACC_W)))
        mismatches += bad
        bad_matrices += int(bad > 0)
        if (n + 1) % 1000 == 0:
            dut._log.info(f"{n + 1}/{NUM_RANDOM} matrices, mismatches so far {mismatches}")
    elapsed = time.time() - t0
    update_json("verification.json", RESULT_KEY, {
        **_load(RESULT_KEY),
        "N": N, "ACC_W": ACC_W, "K_MAX": K_MAX, "seed": SEED,
        "random_matrices": NUM_RANDOM,
        "random_matrices_with_stalls": stressed,
        "outputs_checked": NUM_RANDOM * N * N,
        "element_mismatches": mismatches,
        "matrices_with_mismatch": bad_matrices,
        "min_safe_acc_w_for_k_max": min_safe_acc_w(K_MAX),
        "sim_seconds": round(elapsed, 1),
    })
    assert mismatches == 0, f"{mismatches} element mismatches in {bad_matrices} matrices"


@cocotb.test()
async def test_cycles(dut):
    """Cycle count from start to done with no stalls, for K = 8, 16, 64."""
    rng = np.random.default_rng(SEED + 2)
    await start_clock_and_reset(dut)
    out = {}
    for k in (8, 16, 64):
        if k > K_MAX:
            continue
        a = random_int8(rng, (N, k))
        b = random_int8(rng, (k, N))
        c_hw, cycles, _ = await run_job(dut, a, b, rng=rng)
        check(c_hw, a, b, f"cycles_k{k}")
        macs = N * N * k
        out[f"K{k}"] = {
            "cycles": cycles,
            "macs": macs,
            "macs_per_cycle": round(macs / cycles, 3),
            # utilization = useful MACs / (MAC units x cycles)
            "utilization_pct": round(100.0 * macs / (N * N * cycles), 2) if DESIGN == "systolic"
            else round(100.0 * macs / cycles, 2),
            "mac_units": N * N if DESIGN == "systolic" else 1,
        }
        dut._log.info(f"{DESIGN} N={N} K={k}: {cycles} cycles")
    data = update_json("cycles.json", f"{DESIGN}_N{N}{VARIANT}", out)
    if VARIANT:
        return
    # Speedup when both designs have been measured for this N.
    sa, bl = data.get(f"systolic_N{N}"), data.get(f"baseline_N{N}")
    if sa and bl:
        update_json("cycles.json", f"speedup_N{N}", {
            key: round(bl[key]["cycles"] / sa[key]["cycles"], 2)
            for key in sa if key in bl
        })
