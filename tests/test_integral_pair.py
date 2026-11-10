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
    offset = score * np.std(position) / (2 * 0.05)
    result = derivative_pair(time, position, np.full(len(time), 1 + offset), "r", "x")
    assert result.value == pytest.approx(score)
    assert result.status == status
