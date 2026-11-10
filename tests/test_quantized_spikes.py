import numpy as np
import pytest

from runlog import spikes
from runlog.check_resolution import _lattice_quantum


@pytest.mark.parametrize("float32", [False, True])
@pytest.mark.parametrize("height,events", [(0, 0), (50, 1)])
def test_slow_sine_on_openfast_lattice(float32, height, events):
    time = np.arange(0, 600, 0.05)
    quantum = 2 / 65535
    values = np.rint(np.sin(2 * np.pi * 0.05 * time) / quantum) * quantum
    values[len(values) // 2] += height * quantum
    if float32:
        values = values.astype(np.float32)
    assert _lattice_quantum(values.astype(float)) == pytest.approx(quantum, rel=1e-6)
    assert spikes(values, "r", "x").value == events


@pytest.mark.parametrize("offset", [0, 3])
def test_varied_steps_on_sparse_lattice(offset):
    time = np.arange(0, 600, 0.05)
    quantum = 2 / 65535
    values = np.rint(np.sin(2 * np.pi * 0.05 * time) / quantum) * quantum + offset
    assert spikes(values, "r", "x").value == 0
