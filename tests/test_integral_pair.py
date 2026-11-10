import numpy as np
import pytest

from runlog import CheckConfig, derivative_pair, sample_rate


def test_exact_fast_sine():
    time = np.arange(6000) * 0.05
    omega = 0.55 / 0.05
    result = derivative_pair(time, np.sin(omega * time), omega * np.cos(omega * time), "r", "x")
    assert result.status == "pass"
    assert result.value < 1e-3


def test_one_percent_position_noise():
    time = np.arange(0, 600, 0.1)
    omega = 2 * np.pi * 0.2
    position = np.sin(omega * time) + np.random.default_rng(0).normal(0, 0.01, len(time))
    result = derivative_pair(time, position, omega * np.cos(omega * time), "r", "x")
    assert result.status == "pass"


@pytest.mark.parametrize("fault", ["scale", "shift"])
def test_inconsistent_velocity(fault):
    time = np.arange(6000) * 0.05
    omega = 0.55 / 0.05
    velocity = omega * np.cos(omega * time)
    velocity = 1.1 * velocity if fault == "scale" else np.roll(velocity, 2)
    result = derivative_pair(time, np.sin(omega * time), velocity, "r", "x")
    assert result.status == "fail"


@pytest.mark.parametrize("jump", [0.025, 1.0])
def test_nonuniform_time(jump):
    time = np.arange(6000) * 0.05
    time[3000:] += jump
    result = derivative_pair(time, np.sin(time), np.cos(time), "r", "x")
    assert result.status == "not_testable"
    assert result.value is None


def test_sample_rate_configuration_is_used():
    time = np.arange(6000) * 0.05
    config = CheckConfig(expected_rate_hz=10)
    assert sample_rate(time, "r", config).status == "fail"
    assert derivative_pair(time, np.sin(time), np.cos(time), "r", "x", config).status == "not_testable"


@pytest.mark.parametrize("score,status", [(0.04, "pass"), (0.06, "fail")])
def test_constant_velocity_offset_limit(score, status):
    time = np.arange(6000) * 0.05
    position = time.copy()
    offset = score * np.std(position) / 1.2
    result = derivative_pair(time, position, np.full(len(time), 1 + offset), "r", "x",
                             CheckConfig(derivative_pair_span_s=1.2))
    assert result.value == pytest.approx(score)
    assert result.status == status


@pytest.mark.parametrize("rate", [5, 10, 20, 100])
@pytest.mark.parametrize("fault", ["exact", "scale", "noise"])
def test_slow_sine_across_sampling_rates(rate, fault):
    time = np.arange(600 * rate) / rate
    omega = 2 * np.pi * 0.2
    position = np.sin(omega * time)
    velocity = omega * np.cos(omega * time)
    if fault == "scale":
        velocity *= 1.05
    if fault == "noise":
        position += np.random.default_rng(0).normal(0, 0.01, len(time))
    result = derivative_pair(time, position, velocity, "r", "x")
    assert result.status == ("fail" if fault == "scale" else "pass")
    if fault == "exact":
        assert result.value < 1e-3
    if fault == "scale":
        assert 0.06 < result.value < 0.08


def test_slow_sine_velocity_shift():
    time = np.arange(6000) / 10
    omega = 2 * np.pi * 0.2
    result = derivative_pair(time, np.sin(omega * time),
                             np.roll(omega * np.cos(omega * time), 2), "r", "x")
    assert result.status == "fail"


@pytest.mark.parametrize("span", [0, -1, np.nan, np.inf])
def test_invalid_pair_span(span):
    with pytest.raises(ValueError, match="derivative_pair_span_s"):
        CheckConfig(derivative_pair_span_s=span)


@pytest.mark.parametrize("rate,steps", [(5, 6), (10, 12), (20, 26), (100, 126)])
def test_automatic_span_and_message(rate, steps):
    time = np.arange(600 * rate) / rate
    omega = 2 * np.pi * 0.2
    result = derivative_pair(time, 10 + np.sin(omega * time),
                             omega * np.cos(omega * time), "r", "x")
    assert f"span {steps} steps ({steps / rate:g} s)" in result.message


@pytest.mark.parametrize("span,steps", [(0.01, 2), (0.49, 4), (0.51, 6), (1.8, 18)])
def test_override_uses_nearest_even_span(span, steps):
    time = np.arange(6000) / 10
    omega = 2 * np.pi * 0.2
    config = CheckConfig(derivative_pair_span_s=span)
    result = derivative_pair(time, np.sin(omega * time),
                             1.1 * omega * np.cos(omega * time), "r", "x", config)
    weights = np.ones(steps + 1)
    weights[1:-1:2], weights[2:-1:2] = 4, 2
    velocity = 1.1 * omega * np.cos(omega * time)
    integral = np.convolve(velocity, weights, mode="valid") / 30
    residual = np.sin(omega * time[steps:]) - np.sin(omega * time[:-steps]) - integral
    assert result.value == pytest.approx(np.sqrt(np.mean(residual**2)) / np.std(np.sin(omega * time)))
    assert f"span {steps} steps" in result.message


@pytest.mark.parametrize("samples,status", [(80, "not_testable"), (81, "pass")])
def test_four_span_boundary(samples, status):
    time = np.arange(samples) / 10
    config = CheckConfig(derivative_pair_span_s=2)
    result = derivative_pair(time, time, np.ones(samples), "r", "x", config)
    assert result.status == status
    assert "span 20 steps (2 s)" in result.message
    if status == "not_testable":
        assert result.value is None
        assert "shorter than 4 spans" in result.message


def test_automatic_span_rejects_short_record():
    time = np.arange(40) / 10
    result = derivative_pair(time, np.sin(2 * np.pi * 0.2 * time),
                             2 * np.pi * 0.2 * np.cos(2 * np.pi * 0.2 * time), "r", "x")
    assert result.status == "not_testable"
