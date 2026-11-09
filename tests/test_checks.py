from dataclasses import FrozenInstanceError

import numpy as np
import pandas as pd
import pytest

from runlog import (
    CheckConfig, clipping, derivative_pair, duration, flatline, gaps,
    non_finite, run_checks, sample_rate, spikes, time_monotonic,
)


@pytest.mark.parametrize("check", [time_monotonic, sample_rate, gaps, duration])
def test_time_checks_pass(check):
    result = check(np.arange(200) * 0.1, "r")
    assert result.status == "pass"
    assert result.record_id == "r"
    assert result.channel is None
    assert result.value is not None


@pytest.mark.parametrize("check,time", [
    (time_monotonic, np.r_[np.arange(100), 99]),
    (time_monotonic, np.arange(100)[::-1]),
    (sample_rate, np.r_[np.arange(100) * 0.1, 10.05]),
    (gaps, np.r_[np.arange(100) * 0.1, 12.0]),
    (duration, np.arange(20) * 0.1),
])
def test_time_checks_fail(check, time):
    result = check(time, "r")
    assert result.status == "fail"
    assert result.message


@pytest.mark.parametrize("check", [time_monotonic, sample_rate, gaps, duration])
@pytest.mark.parametrize("time", [[], np.arange(9), np.r_[np.arange(20), np.nan]])
def test_time_checks_not_testable(check, time):
    result = check(time, "r")
    assert result.status == "not_testable"
    assert result.value is None
    assert result.message


@pytest.mark.parametrize("check", [sample_rate, gaps, duration])
def test_time_checks_need_monotonic_time(check):
    result = check(np.arange(100)[::-1], "r")
    assert result.status == "not_testable"
    assert "increasing" in result.message


def test_sample_rate_ignores_gaps():
    time = np.arange(200) * 0.1
    time[100:] += 2
    assert gaps(time, "r").value == 1
    assert sample_rate(time, "r").status == "pass"


@pytest.mark.parametrize("check", [non_finite, clipping, spikes])
def test_channel_checks_pass(check):
    result = check(np.sin(np.arange(200) * 0.13), "r", "x")
    assert result.status == "pass"
    assert result.channel == "x"


@pytest.mark.parametrize("check,values", [
    (non_finite, np.r_[np.arange(100), np.nan, np.inf, -np.inf]),
    (clipping, np.clip(np.sin(np.arange(200) * 0.13), -0.5, 0.5)),
    (spikes, np.r_[np.sin(np.arange(200) * 0.13), 100]),
])
def test_channel_checks_fail(check, values):
    assert check(values, "r", "x").status == "fail"


@pytest.mark.parametrize("check", [non_finite, clipping, spikes])
def test_channel_checks_short(check):
    result = check(np.arange(9), "r", "x")
    assert result.status == "not_testable"
    assert "10" in result.message


@pytest.mark.parametrize("check", [clipping, spikes])
@pytest.mark.parametrize("values", [np.zeros(100), np.r_[np.arange(100), np.inf]])
def test_channel_checks_undefined(check, values):
    assert check(values, "r", "x").status == "not_testable"


def test_zero_mad_nonconstant():
    result = spikes(np.r_[np.zeros(99), 1], "r", "x")
    assert result.status == "fail"
    assert result.value == 1


def test_clipping_counts_runs_separately():
    values = np.arange(100, dtype=float)
    values[10:14] = -1
    values[20:23] = 101
    values[30:32] = -1
    result = clipping(values, "r", "x")
    assert result.value == 0.07


def test_flatline_pass_and_fail():
    time = np.arange(100) * 0.1
    assert flatline(time, np.arange(100), "r", "x").status == "pass"
    values = np.arange(100, dtype=float)
    values[10:41] = 10
    result = flatline(time, values, "r", "x")
    assert result.status == "fail"
    assert result.value == pytest.approx(3.0)
    assert flatline(time, np.ones(100), "r", "x").status == "fail"


@pytest.mark.parametrize("time,values", [
    (np.arange(9), np.ones(9)),
    (np.arange(100)[::-1], np.ones(100)),
    (np.arange(100), np.r_[np.zeros(99), np.nan]),
])
def test_flatline_not_testable(time, values):
    assert flatline(time, values, "r", "x").status == "not_testable"


def test_derivative_pair_pass_and_fail():
    time = np.arange(1000) * 0.01
    position, velocity = np.sin(time), np.cos(time)
    assert derivative_pair(time, position, velocity, "r", "x").status == "pass"
    result = derivative_pair(time, position, 2 * velocity, "r", "x")
    assert result.status == "fail"
    assert result.value > result.threshold


@pytest.mark.parametrize("time,position,velocity", [
    (np.arange(9), np.arange(9), np.arange(9)),
    (np.arange(100)[::-1], np.arange(100), np.arange(100)),
    (np.arange(100), np.arange(100), np.ones(100)),
    (np.arange(100), np.r_[np.arange(99), np.inf], np.arange(100)),
])
def test_derivative_pair_not_testable(time, position, velocity):
    result = derivative_pair(time, position, velocity, "r", "x")
    assert result.status == "not_testable"
    assert result.value is None


def test_run_checks():
    time = np.arange(1000) * 0.02
    frame = pd.DataFrame({"time": time, "position": np.sin(time), "velocity": np.cos(time)})
    config = CheckConfig(derivative_pairs=(("position", "velocity"), ("missing", "velocity")))
    results = run_checks(frame, "r", config)
    assert len(results) == 14
    assert all(result.status == "pass" for result in results[:-1])
    assert results[-1].status == "not_testable"
    assert "missing" in results[-1].message
    with pytest.raises(ValueError, match="time"):
        run_checks(frame.drop(columns="time"), "r")
    with pytest.raises(FrozenInstanceError):
        config.spike_z = 5


def test_config_thresholds():
    assert duration(np.arange(100) * 0.1, "r", CheckConfig(min_duration_s=9)).status == "pass"
    assert non_finite(np.r_[np.ones(99), np.nan], "r", "x",
                      CheckConfig(non_finite_fraction=0.01)).status == "pass"
    assert clipping(np.clip(np.sin(np.arange(200)), -0.5, 0.5), "r", "x",
                    CheckConfig(clipping_fraction=1)).status == "pass"


def test_hampel_quiet_then_large_sine():
    rng = np.random.default_rng(42)
    values = np.r_[rng.normal(0, 1, 700), 100 * np.sin(np.arange(300) * 0.13)]
    assert spikes(values, "r", "x").value == 0
    values[[100, 400, 800]] += 10000
    assert spikes(values, "r", "x").value == 3


@pytest.mark.parametrize("window", [2, 4, 1, 3.5])
def test_invalid_spike_window(window):
    with pytest.raises(ValueError, match="spike_window"):
        CheckConfig(spike_window=window)
