from dataclasses import FrozenInstanceError

import numpy as np
import pandas as pd
import pytest

from runlog import (
    CheckConfig,
    clipping,
    derivative_pair,
    duration,
    flatline,
    gaps,
    non_finite,
    run_checks,
    sample_rate,
    spikes,
    time_monotonic,
)


@pytest.mark.parametrize("check", [time_monotonic, sample_rate, gaps, duration])
def test_time_checks_pass(check):
    result = check(np.arange(200) * 0.1, "r")
    assert result.status == "pass"
    assert result.record_id == "r"
    assert result.channel is None
    assert result.value is not None


@pytest.mark.parametrize(
    "check,time",
    [
        (time_monotonic, np.r_[np.arange(100), 99]),
        (time_monotonic, np.arange(100)[::-1]),
        (sample_rate, np.r_[np.arange(100) * 0.1, 10.001, 10.15]),
        (gaps, np.r_[np.arange(100) * 0.1, 12.0]),
        (duration, np.arange(20) * 0.1),
    ],
)
def test_time_checks_fail(check, time):
    result = check(time, "r")
    assert result.status == "fail"
    assert result.message


@pytest.mark.parametrize("check", [sample_rate, gaps])
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


@pytest.mark.parametrize(
    "check,values",
    [
        (non_finite, np.r_[np.arange(100), np.nan, np.inf, -np.inf]),
        (clipping, np.clip(np.sin(np.arange(200) * 0.13), -0.5, 0.5)),
        (spikes, np.r_[np.sin(np.arange(100) * 0.13), 100,
                        np.sin(np.arange(100) * 0.13)]),
    ],
)
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


def test_zero_mad_with_known_quantum():
    values = np.zeros(200)
    values[10:120:20] = 1
    values[-11] = 100
    result = spikes(values, "r", "x")
    assert result.status == "fail"
    assert result.value == 1


def test_isolated_timing_error_does_not_set_resolution():
    time = np.arange(1000) * 0.01
    time[500:] += 0.005
    result = sample_rate(time, "r")
    assert result.status == "fail"
    assert result.threshold == CheckConfig().sample_rate_rel_tol
    assert sample_rate(np.r_[np.arange(100) * 0.1, 10.05], "r").status == "fail"


@pytest.mark.parametrize("hz", [30, 60, 128])
def test_sample_rate_accepts_millisecond_rounding(hz):
    time = np.round(np.arange(hz * 20) / hz, 3)
    assert sample_rate(time, "r").status == "pass"


@pytest.mark.parametrize("count,status", [(49, "fail"), (50, "pass")])
def test_resolution_requires_five_percent_of_regular_steps(count, status):
    steps = np.full(1000, 0.01)
    steps[::20][:count] += 0.001
    time = np.r_[0, np.cumsum(steps)]
    assert sample_rate(time, "r").status == status
    assert (
        sample_rate(time, "r", CheckConfig(resolution_min_fraction=0.06)).status
        == "fail"
    )


@pytest.mark.parametrize("expected,status", [(50, "fail"), (100, "pass")])
def test_expected_sample_rate(expected, status):
    config = CheckConfig(expected_rate_hz=expected)
    result = sample_rate(np.arange(1000) * 0.01, "r", config)
    assert result.status == status
    assert f"expected {expected} Hz" in result.message
    assert "measured 100 Hz" in result.message
    assert sample_rate(np.arange(9), "r", config).status == "not_testable"


def test_expected_rate_uses_relative_tolerance_despite_rounding():
    time = np.round(np.arange(2560) / 128, 3)
    result = sample_rate(time, "r", CheckConfig(expected_rate_hz=120))
    assert result.status == "fail"
    assert result.threshold == CheckConfig().sample_rate_rel_tol
    assert "expected 120 Hz" in result.message
    assert "measured 125 Hz" in result.message


@pytest.mark.parametrize("index", [10, 500, 989])
def test_isolated_channel_spike_does_not_set_quantum(index):
    values = np.zeros(1000)
    values[index] = 1
    result = spikes(values, "r", "x")
    assert result.status == "fail"
    assert result.value == 1


@pytest.mark.parametrize("count", [1, 24, 25])
def test_two_value_channel_does_not_establish_a_lattice(count):
    values = np.zeros(1001)
    values[10 : 10 + 20 * count : 20] = 1
    assert spikes(values, "r", "x").value == count


@pytest.mark.parametrize("noise_lsb", [0.3, 0.5, 1.0])
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_quantized_integer_noise_has_no_spikes(noise_lsb, seed):
    values = np.rint(np.random.default_rng(seed).normal(0, noise_lsb, 10_000))
    result = spikes(values, "r", "x")
    assert result.status == "pass"
    assert result.value == 0


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


@pytest.mark.parametrize(
    "time,values",
    [
        (np.arange(9), np.ones(9)),
        (np.arange(100)[::-1], np.ones(100)),
        (np.arange(100), np.r_[np.zeros(99), np.nan]),
    ],
)
def test_flatline_not_testable(time, values):
    assert flatline(time, values, "r", "x").status == "not_testable"


def test_derivative_pair_pass_and_fail():
    time = np.arange(1000) * 0.1
    position, velocity = np.sin(time), np.cos(time)
    assert derivative_pair(time, position, velocity, "r", "x").status == "pass"
    result = derivative_pair(time, position, 2 * velocity, "r", "x")
    assert result.status == "fail"
    assert result.value > result.threshold


@pytest.mark.parametrize(
    "time,position,velocity",
    [
        (np.arange(9), np.arange(9), np.arange(9)),
        (np.arange(100)[::-1], np.arange(100), np.arange(100)),
        (np.arange(100), np.ones(100), np.arange(100)),
        (np.arange(100), np.r_[np.arange(99), np.inf], np.arange(100)),
    ],
)
def test_derivative_pair_not_testable(time, position, velocity):
    result = derivative_pair(time, position, velocity, "r", "x")
    assert result.status == "not_testable"
    assert result.value is None


def test_run_checks():
    time = np.arange(1000) * 0.02
    frame = pd.DataFrame(
        {"time": time, "position": np.sin(time), "velocity": np.cos(time)}
    )
    config = CheckConfig(
        spike_window=315,
        derivative_pairs=(("position", "velocity"), ("missing", "velocity")),
    )
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
    assert (
        duration(np.arange(100) * 0.1, "r", CheckConfig(min_duration_s=9)).status
        == "pass"
    )
    assert (
        non_finite(
            np.r_[np.ones(99), np.nan], "r", "x", CheckConfig(non_finite_fraction=0.01)
        ).status
        == "pass"
    )
    assert (
        clipping(
            np.clip(np.sin(np.arange(200)), -0.5, 0.5),
            "r",
            "x",
            CheckConfig(clipping_fraction=1),
        ).status
        == "pass"
    )


def test_spikes_quiet_then_large_sine():
    rng = np.random.default_rng(42)
    values = np.r_[rng.normal(0, 1, 700), 100 * np.sin(np.arange(300) * 0.13)]
    assert spikes(values, "r", "x").value == 0
    values[[100, 400, 800]] += 10000
    assert spikes(values, "r", "x").value == 3


@pytest.mark.parametrize("window", [2, 4, 1, 3.5])
def test_invalid_spike_window(window):
    with pytest.raises(ValueError, match="spike_window"):
        CheckConfig(spike_window=window)


def test_spikes_white_noise_false_alarm_rate():
    clean = sum(
        spikes(np.random.default_rng(seed).normal(size=100_000), "r", "x").value == 0
        for seed in range(20)
    )
    assert clean >= 19


@pytest.mark.parametrize("index", [10, 500, 989])
def test_spikes_detects_twenty_five_sigma_impulse(index):
    values = np.random.default_rng(0).normal(size=1000)
    # d2 amplifies white-noise SD by sqrt(6).
    values[index] = 25.0
    result = spikes(values, "r", "x")
    assert result.status == "fail"
    assert result.value == 1


def test_time_violation_count_and_short_records():
    assert time_monotonic([0, np.nan, 1, 1, np.inf, -np.inf], "r").value == 5
    assert time_monotonic([1, 0], "r").value == 1
    assert time_monotonic([0, 1], "r").status == "pass"
    assert time_monotonic([np.nan], "r").status == "not_testable"


@pytest.mark.parametrize(
    "time,status",
    [
        ([], "fail"),
        ([0], "fail"),
        ([0, 1, 2], "fail"),
        ([0, 10], "pass"),
        ([0, 5, 10], "pass"),
        ([0, np.nan], "not_testable"),
        ([1, 0], "not_testable"),
    ],
)
def test_short_duration(time, status):
    assert duration(time, "r").status == status
