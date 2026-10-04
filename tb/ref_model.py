"""NumPy golden model and bus packing helpers for the systolic-array testbenches.

The hardware computes C = A x B with signed INT8 inputs and a signed ACC_W-bit
accumulator that wraps on overflow (two's complement). The model does the exact
math in int64 and then applies the same wrap, so it matches the RTL bit for bit
for any ACC_W.
"""

import numpy as np

DATA_W = 8
INT8_MIN, INT8_MAX = -128, 127


def wrap_signed(x, width):
    """Wrap integers (scalar or array) to a signed two's-complement width."""
    x = np.asarray(x, dtype=np.int64)
    mask = (1 << width) - 1
    x = x & mask
    return np.where(x >= (1 << (width - 1)), x - (1 << width), x)


def matmul_ref(a, b, acc_w=32):
    """Golden C = A x B. a is N x K, b is K x N (int8 values), result int64."""
    a = np.asarray(a, dtype=np.int64)
    b = np.asarray(b, dtype=np.int64)
    return wrap_signed(a @ b, acc_w)


def min_safe_acc_w(k, data_w=DATA_W):
    """Smallest signed accumulator width that can never overflow for K terms.

    Worst case is (-128) * (-128) * K = K * 2^14, which must fit below 2^(W-1).
    """
    worst_pos = k * (1 << (2 * data_w - 2))          # (-128)^2 * K
    worst_neg = k * INT8_MIN * INT8_MAX              # (-128) * 127 * K
    w = 2
    while not (worst_pos <= (1 << (w - 1)) - 1 and worst_neg >= -(1 << (w - 1))):
        w += 1
    return w


def pack(values, width):
    """Pack a list of signed ints into one bus integer, element 0 in the LSBs."""
    mask = (1 << width) - 1
    word = 0
    for idx, v in enumerate(values):
        word |= (int(v) & mask) << (idx * width)
    return word


def unpack(word, n, width):
    """Unpack a bus integer into n signed ints, element 0 from the LSBs."""
    mask = (1 << width) - 1
    out = []
    for idx in range(n):
        v = (word >> (idx * width)) & mask
        if v >= 1 << (width - 1):
            v -= 1 << width
        out.append(v)
    return out


def random_int8(rng, shape):
    return rng.integers(INT8_MIN, INT8_MAX + 1, size=shape, dtype=np.int64)


if __name__ == "__main__":
    rng = np.random.default_rng(0)
    a = random_int8(rng, (4, 5))
    b = random_int8(rng, (5, 4))
    assert np.array_equal(matmul_ref(a, b), a @ b)
    assert unpack(pack([-1, 5, -128, 127], 8), 4, 8) == [-1, 5, -128, 127]
    assert min_safe_acc_w(64) == 22
    assert wrap_signed(1 << 19, 20) == -(1 << 19)
    assert wrap_signed(64 * 16384, 20) == 0          # all -128 at K=64 wraps in 20 bits
    print("ref_model self-test passed")
