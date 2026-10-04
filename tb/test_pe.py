"""cocotb unit tests for one processing element (rtl/pe.v)."""

import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly, Timer

from ref_model import wrap_signed

ACC_W = int(os.environ.get("ACC_W", 32))
PIPE = int(os.environ.get("PIPE", 1))
ISO = int(os.environ.get("ISO", 1))


def s8(v):
    return v - 256 if v >= 128 else v


async def setup(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.shift.value = 0
    dut.a_in.value = 0
    dut.b_in.value = 0
    dut.acc_in.value = 0
    for _ in range(2):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


@cocotb.test()
async def test_mac_passthrough_shift(dut):
    """Random a/b/shift each cycle; check acc, a_out and b_out every cycle."""
    await setup(dut)
    rng = random.Random(7)
    acc = 0
    prod_q = 0          # model of the PE product register (used when PIPE = 1)
    iso_a = iso_b = 0   # model of the operand copy (used when ISO = 1)
    corner = [-128, -127, -1, 0, 1, 126, 127]
    for cyc in range(5000):
        a = rng.choice(corner) if rng.random() < 0.3 else rng.randint(-128, 127)
        b = rng.choice(corner) if rng.random() < 0.3 else rng.randint(-128, 127)
        shift = rng.random() < 0.05
        acc_in = rng.randint(-(1 << (ACC_W - 1)), (1 << (ACC_W - 1)) - 1)
        dut.a_in.value = a & 0xFF
        dut.b_in.value = b & 0xFF
        dut.shift.value = int(shift)
        dut.acc_in.value = acc_in & ((1 << ACC_W) - 1)
        await RisingEdge(dut.clk)
        await ReadOnly()
        # Reference update: shift loads acc_in, otherwise multiply-accumulate.
        prod_now = iso_a * iso_b if ISO else a * b
        addend = prod_q if PIPE else prod_now
        if shift:
            acc = acc_in
        else:
            acc = int(wrap_signed(acc + addend, ACC_W))
        prod_q = prod_now
        iso_a, iso_b = a, b
        got_acc = dut.acc.value.to_signed()
        assert got_acc == acc, f"cycle {cyc}: acc {got_acc} != {acc}"
        assert s8(int(dut.a_out.value)) == a, f"cycle {cyc}: a_out wrong"
        assert s8(int(dut.b_out.value)) == b, f"cycle {cyc}: b_out wrong"
        # Leave the read-only phase before driving the next cycle's inputs.
        await Timer(1, unit="ns")


@cocotb.test()
async def test_worst_case_accumulation(dut):
    """(-128) x (-128) accumulated 64 times must give exactly 64 * 16384."""
    await setup(dut)                # reset leaves the accumulator at zero
    dut.a_in.value = 0x80
    dut.b_in.value = 0x80
    for _ in range(64):
        await RisingEdge(dut.clk)
    dut.a_in.value = 0
    dut.b_in.value = 0
    for _ in range(PIPE + ISO):     # let the last product leave the pipeline registers
        await RisingEdge(dut.clk)
    await ReadOnly()
    expected = int(wrap_signed(64 * 16384, ACC_W))
    assert dut.acc.value.to_signed() == expected, f"got {dut.acc.value.to_signed()}, want {expected}"
