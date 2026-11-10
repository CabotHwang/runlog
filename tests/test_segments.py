from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from runlog import SegmentConfig, tag_segments


def analytic_signal():
    time = np.arange(0, 300, 0.05)
    amplitude = np.interp(time, [0, 30, 70, 230, 270, 300], [0, 0, 2, 2, 0, 0])
    values = amplitude * np.sin(2 * np.pi * 1.2 * time)
    return time, values


def test_analytic_envelope():
    time, values = analytic_signal()
    config = SegmentConfig(noise_floor=0.05)
    report = tag_segments(time, values, "r", "sway", config)
    assert report.status == "ok"
    assert [segment.tag for segment in report.segments] == [
        "quiet",
        "buildup",
        "steady",
        "decay",
        "quiet",
    ]
    expected = [(0, 30), (42, 70), (70, 230), (230, 258), (270, 300)]
    for segment, (start, end) in zip(report.segments, expected):
        assert abs(segment.start_s - start) <= config.window_s
        assert abs(segment.end_s - end) <= config.window_s
        assert segment.record_id == "r"
        assert segment.channel == "sway"
        assert segment.method == "rolling_std"
        assert segment.method_version == 2
        assert segment.start_s < segment.end_s
    steady = report.segments[2]
    assert steady.rms == pytest.approx(np.sqrt(2), rel=0.02)
    assert steady.peak_freq_hz == pytest.approx(1.2, abs=0.01)
    for first, second in zip(report.segments, report.segments[1:]):
        assert first.end_s <= second.start_s
    with pytest.raises(FrozenInstanceError):
        steady.tag = "quiet"


@pytest.mark.parametrize("length", [0, 1, 100])
def test_short_record(length):
    report = tag_segments(
        np.arange(length) * 0.1, np.ones(length), "r", "x", SegmentConfig(0.1)
    )
    assert report.status == "not_testable"
    assert report.segments == ()


def test_quiet_and_offset():
    time = np.arange(0, 40, 0.1)
    report = tag_segments(time, np.full(len(time), 5.0), "r", "x", SegmentConfig(0.1))
    assert report.status == "ok"
    assert len(report.segments) == 1
    assert report.segments[0].tag == "quiet"
    assert report.segments[0].start_s == 0
    assert report.segments[0].end_s == pytest.approx(40)
    assert report.segments[0].rms == 0
    assert report.segments[0].peak_freq_hz is None


def test_short_quiet_has_no_frequency():
    time = np.arange(0, 40, 0.05)
    amplitude = np.where(time < 2, 0, 2)
    report = tag_segments(
        time,
        amplitude * np.sin(2 * np.pi * time),
        "r",
        "x",
        SegmentConfig(noise_floor=0.05, window_s=2, min_steady_s=10),
    )
    quiet = next(segment for segment in report.segments if segment.tag == "quiet")
    assert quiet.peak_freq_hz is None


@pytest.mark.parametrize(
    "changes",
    [
        {"noise_floor": 0},
        {"noise_floor": np.nan},
        {"window_s": 0},
        {"min_steady_s": -1},
        {"rel_tol": -0.1},
        {"rel_tol": 1},
    ],
)
def test_bad_config(changes):
    with pytest.raises(ValueError):
        SegmentConfig(**({"noise_floor": 0.1} | changes))


def test_noise_floor_required():
    with pytest.raises(TypeError):
        SegmentConfig()


@pytest.mark.parametrize("kind", ["reverse", "nan_time", "nan_values"])
def test_untestable_input(kind):
    time, values = analytic_signal()
    if kind == "reverse":
        time = time[::-1]
    elif kind == "nan_time":
        time[20] = np.nan
    else:
        values[20] = np.nan
    assert (
        tag_segments(time, values, "r", "x", SegmentConfig(0.1)).status
        == "not_testable"
    )


def test_mismatched_input():
    with pytest.raises(ValueError, match="equal length"):
        tag_segments([0, 1], [1], "r", "x", SegmentConfig(0.1))
    with pytest.raises(ValueError, match="one-dimensional"):
        tag_segments([[0, 1]], [[1, 2]], "r", "x", SegmentConfig(0.1))


def test_growing_signal_has_no_tags():
    time = np.arange(0, 60, 0.05)
    values = (1 + time / 5) * np.sin(2 * np.pi * time)
    report = tag_segments(time, values, "r", "x", SegmentConfig(0.01))
    assert report.status == "ok"
    assert report.segments == ()


def test_repeated_steady_spans():
    time = np.arange(0, 600, 0.05)
    local_time = np.mod(time, 300)
    amplitude = np.interp(local_time, [0, 30, 70, 230, 270, 300], [0, 0, 2, 2, 0, 0])
    values = amplitude * np.sin(2 * np.pi * 1.2 * time)
    report = tag_segments(time, values, "r", "x", SegmentConfig(0.05))
    assert sum(segment.tag == "steady" for segment in report.segments) == 2
    assert sum(segment.tag == "buildup" for segment in report.segments) == 2
    assert sum(segment.tag == "decay" for segment in report.segments) == 2
    for first, second in zip(report.segments, report.segments[1:]):
        assert first.end_s <= second.start_s


def test_large_dip_rejects_buildup():
    time = np.arange(0, 300, 0.05)
    amplitude = np.interp(
        time, [0, 30, 50, 55, 70, 230, 270, 300], [0, 0, 1.5, 0.7, 2, 2, 0, 0]
    )
    values = amplitude * np.sin(2 * np.pi * 1.2 * time)
    report = tag_segments(time, values, "r", "x", SegmentConfig(0.05, window_s=2))
    assert "steady" in [segment.tag for segment in report.segments]
    assert "buildup" not in [segment.tag for segment in report.segments]


def test_small_dip_allows_buildup():
    time = np.arange(0, 300, 0.05)
    amplitude = np.interp(
        time, [0, 30, 50, 55, 70, 230, 270, 300], [0, 0, 1.5, 1.46, 2, 2, 0, 0]
    )
    values = amplitude * np.sin(2 * np.pi * 1.2 * time)
    report = tag_segments(time, values, "r", "x", SegmentConfig(0.05, window_s=2))
    assert "buildup" in [segment.tag for segment in report.segments]


def test_long_transitions_short_plateau():
    time = np.arange(0, 300, 0.05)
    amplitude = 2 * np.minimum(np.minimum(time / 100, (300 - time) / 140), 1) ** 2
    report = tag_segments(
        time, amplitude * np.sin(2 * np.pi * 1.2 * time), "r", "x", SegmentConfig(0.05)
    )
    steady = [s for s in report.segments if s.tag == "steady"]
    assert len(steady) == 1
    assert abs(steady[0].start_s - 100) <= 10
    assert abs(steady[0].end_s - 160) <= 10


def test_different_plateau_levels():
    time = np.arange(0, 300, 0.05)
    amplitude = np.interp(time, [0, 30, 100, 150, 240, 300], [0, 1, 1, 3, 3, 0])
    report = tag_segments(
        time, amplitude * np.sin(2 * np.pi * 1.2 * time), "r", "x", SegmentConfig(0.05)
    )
    steady = [s for s in report.segments if s.tag == "steady"]
    assert len(steady) == 2
    assert abs(steady[0].start_s - 30) <= 10
    assert abs(steady[0].end_s - 100) <= 10
    assert abs(steady[1].start_s - 150) <= 10
    assert abs(steady[1].end_s - 240) <= 10
    assert steady[1].rms / steady[0].rms == pytest.approx(3, rel=0.05)


@pytest.mark.parametrize(
    "changes",
    [
        {"transition_low": 0},
        {"transition_low": -0.1},
        {"transition_low": 0.9},
        {"transition_high": 0.3},
        {"transition_high": 1.01},
        {"transition_low": np.nan},
        {"transition_high": np.nan},
        {"transition_low": np.inf},
        {"transition_high": np.inf},
    ],
)
def test_bad_transition_limits(changes):
    with pytest.raises(ValueError, match="transition"):
        SegmentConfig(**({"noise_floor": 0.1} | changes))


def test_transition_limits_control_boundaries():
    time, values = analytic_signal()
    default = tag_segments(time, values, "r", "x", SegmentConfig(0.05))
    custom = tag_segments(
        time,
        values,
        "r",
        "x",
        SegmentConfig(0.05, transition_low=0.5, transition_high=1.0),
    )
    assert [s.tag for s in custom.segments] == [s.tag for s in default.segments]
    default_buildup, custom_buildup = default.segments[1], custom.segments[1]
    default_decay, custom_decay = default.segments[3], custom.segments[3]
    assert custom_buildup.start_s > default_buildup.start_s
    assert custom_buildup.end_s > default_buildup.end_s
    assert custom_decay.start_s < default_decay.start_s
    assert custom_decay.end_s < default_decay.end_s
