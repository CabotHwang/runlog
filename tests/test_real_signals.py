import numpy as np
import pytest

from runlog import SegmentConfig, spikes, tag_segments


def oscillation(dt=0.1):
    time = np.arange(0, 600, dt)
    values = 0.15 * np.sin(2 * np.pi * 0.2 * time)
    values += np.random.default_rng(0).normal(0, 0.001, len(time))
    return time, values


@pytest.mark.parametrize("dt,height", [(0.1, 0.02), (0.1, 0.15), (0.1, 1.0), (0.01, 0.02)])
def test_d1_spike_on_noisy_oscillation(dt, height):
    time, values = oscillation(dt)
    values[len(time) // 2] += height
    assert spikes(values, "r", "x").value == 1


@pytest.mark.parametrize("ramp_s", [0, 30])
def test_d2_oscillation_onset_without_spike(ramp_s):
    time = np.arange(0, 600, 0.1)
    amplitude = (time >= 420).astype(float)
    if ramp_s:
        phase = np.clip((time - 420) / ramp_s, 0, 1)
        amplitude = (1 - np.cos(np.pi * phase)) / 2
    values = np.random.default_rng(0).normal(0, 0.001, len(time))
    values += 0.15 * amplitude * np.sin(2 * np.pi * 0.2 * time)
    assert spikes(values, "r", "x").value == 0


def response(modulation=0.0, offset=False):
    time = np.arange(0, 600, 0.1)
    buildup_end = 180 if offset else 150
    amplitude = np.interp(time, [0, 90, buildup_end, 450, 510, 600], [0, 0, 0.15, 0.15, 0, 0])
    values = amplitude * (1 + modulation * np.sin(2 * np.pi * 0.01 * time))
    values *= np.sin(2 * np.pi * 0.2 * time)
    if offset:
        values += np.interp(time, [0, 90, buildup_end, 600], [0, 0, 0.3, 0.3])
    return time, values


def test_d3_offset_buildup_preserves_quiet():
    time, values = response(offset=True)
    report = tag_segments(time, values, "r", "x", SegmentConfig(0.005))
    assert [s.tag for s in report.segments] == ["quiet", "buildup", "steady", "decay", "quiet"]
    assert report.segments[0].start_s == 0
    assert report.segments[0].end_s >= 60
    assert not any(s.tag == "steady" and s.start_s < 60 for s in report.segments)
    for segment in report.segments:
        span = values[(time >= segment.start_s) & (time < segment.end_s)]
        assert segment.rms == pytest.approx(np.sqrt(np.mean((span - span.mean()) ** 2)))
        assert segment.method == "rolling_std"
        assert segment.method_version == 3


def test_d4_modulation_preserves_transitions():
    time, values = response(modulation=0.2)
    report = tag_segments(time, values, "r", "x", SegmentConfig(0.005, rel_tol=0.25))
    assert [s.tag for s in report.segments] == ["quiet", "buildup", "steady", "decay", "quiet"]


@pytest.mark.parametrize("modulation,start,buildup", [(0, 143.9, 108.2), (0.05, 144.0, 108.1)])
def test_clean_and_small_modulation_keep_previous_boundaries(modulation, start, buildup):
    time, values = response()
    values *= 1 + modulation * np.sin(2 * np.pi * 0.1 * time)
    config = SegmentConfig(0.005)
    report = tag_segments(time, values, "r", "x", config)
    # Boundaries measured with version 1 before this change.
    expected = [("quiet", 0, 91.3), ("buildup", buildup, start),
                ("steady", start, 456.3), ("decay", 456.3, 492.0), ("quiet", 508.9, 600)]
    assert [s.tag for s in report.segments] == [tag for tag, _, _ in expected]
    for segment, (_, old_start, old_end) in zip(report.segments, expected):
        assert abs(segment.start_s - old_start) <= config.window_s
        assert abs(segment.end_s - old_end) <= config.window_s


def test_step_is_one_spike_event():
    values = np.zeros(1000)
    values[500:] = 1
    assert spikes(values, "r", "x").value == 1


def test_drift_during_short_transition_can_exceed_dip_limit():
    time = np.arange(0, 600, 0.1)
    amplitude = np.interp(
        time, [0, 60, 120, 480, 540, 600], [0.002, 0.002, 0.15, 0.15, 0.002, 0.002]
    )
    values = amplitude * np.sin(2 * np.pi * 0.2 * time)
    values += np.random.default_rng(0).normal(0, 0.001, len(time))
    drift = np.interp(time, [0, 60, 120, 600], [0, 0, 0.3, 0.3])
    expected = ["quiet", "buildup", "steady", "decay", "quiet"]
    clean = tag_segments(time, values, "r", "x", SegmentConfig(0.005))
    assert [s.tag for s in clean.segments] == expected
    default = tag_segments(time, values + drift, "r", "x", SegmentConfig(0.005))
    assert [s.tag for s in default.segments] == ["quiet", "steady", "decay", "quiet"]
    relaxed = tag_segments(time, values + drift, "r", "x", SegmentConfig(0.005, rel_tol=0.07))
    assert [s.tag for s in relaxed.segments] == expected
