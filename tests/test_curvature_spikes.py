import numpy as np
import pytest

from runlog import CheckConfig, spikes


@pytest.mark.parametrize("dt", [0.01, 0.02, 0.05, 0.1])
def test_noiseless_sine_has_no_curvature_events(dt):
    time = np.arange(0, 600, dt)
    values = 0.15 * np.sin(2 * np.pi * 0.2 * time)
    result = spikes(values, "r", "x")
    assert result.status == "pass"
    assert result.value == 0


@pytest.mark.parametrize("window", [7, 9, 11])
@pytest.mark.parametrize("height,events", [(0, 0), (0.02, 1)])
def test_short_curvature_window_preserves_single_sample_impulse(window, height, events):
    time = np.arange(0, 600, 0.01)
    values = 0.15 * np.sin(2 * np.pi * 0.2 * time)
    values[len(values) // 2] += height
    config = CheckConfig(spike_detrend_window=window)
    assert spikes(values, "r", "x", config).value == events


@pytest.mark.parametrize("window", [0, 1, 2, 4, 3.5, True, "7", None])
def test_invalid_curvature_window(window):
    with pytest.raises(ValueError, match="spike_detrend_window"):
        CheckConfig(spike_detrend_window=window)


def test_default_curvature_window():
    assert CheckConfig().spike_detrend_window == 7
