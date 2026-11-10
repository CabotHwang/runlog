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


@pytest.mark.parametrize("index,events", [(None, 0), (10, 1), (-11, 1)])
def test_smooth_start_and_near_edge_impulse(index, events):
    time = np.arange(0, 60, 0.05)
    values = (1 - np.exp(-time)) * np.sin(2 * np.pi * time)
    if index is not None:
        values[index] += 10
    assert spikes(values, "r", "x").value == events


@pytest.mark.parametrize("index", [0, 1, -2, -1])
def test_incomplete_detrend_windows_are_not_scored(index):
    values = np.sin(np.arange(1000) * 0.13)
    values[index] += 100
    assert spikes(values, "r", "x").value == 0


def test_detrend_window_longer_than_record():
    result = spikes(np.arange(10), "r", "x", CheckConfig(spike_detrend_window=11))
    assert result.status == "not_testable"


def test_scale_uses_nearest_complete_window():
    import pandas as pd

    from runlog.checks import _spike_scale

    series = pd.Series(np.arange(200, dtype=float) ** 2)
    scale = _spike_scale(series, series, 101)
    np.testing.assert_array_equal(scale[:50], np.full(50, scale[50]))
    np.testing.assert_array_equal(scale[-50:], np.full(50, scale[-51]))
