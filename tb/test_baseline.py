"""The same checks as test_sa_top, run on the single-MAC baseline.

The baseline needs about N*N*K cycles per job, so the Makefile runs fewer random
matrices on it (NUM_RANDOM=500 by default). Its cycle counts go into
results/cycles.json next to the systolic array's, and the speedup is computed
from those two measurements.
"""

import os

os.environ.setdefault("DESIGN", "baseline")
os.environ.setdefault("NUM_RANDOM", "500")

from test_sa_top import test_directed, test_random, test_cycles  # noqa: E402,F401
