from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike, NDArray


@dataclass(frozen=True)
class SegmentConfig:
    noise_floor: float
    window_s: float = 10.0
    rel_tol: float = 0.05
    min_steady_s: float = 30.0
    transition_low: float = 0.3
    transition_high: float = 0.9

    def __post_init__(self) -> None:
        if not np.isfinite(self.noise_floor) or self.noise_floor <= 0:
            raise ValueError("noise_floor must be positive and finite")
        if not np.isfinite(self.window_s) or self.window_s <= 0:
            raise ValueError("window_s must be positive and finite")
        if not np.isfinite(self.min_steady_s) or self.min_steady_s <= 0:
            raise ValueError("min_steady_s must be positive and finite")
        if not np.isfinite(self.rel_tol) or not 0 <= self.rel_tol < 1:
            raise ValueError("rel_tol must be between zero and one")
        if not 0 < self.transition_low < self.transition_high <= 1:
            raise ValueError("transition limits must satisfy 0 < low < high <= 1")


@dataclass(frozen=True)
class Segment:
    record_id: str
    channel: str
    start_s: float
    end_s: float
    tag: str
    rms: float
    peak_freq_hz: float | None
    method: str = "rolling_std"
    method_version: int = 2


@dataclass(frozen=True)
class SegmentReport:
    status: str
    segments: tuple[Segment, ...]


def _runs(mask: NDArray[np.bool_]) -> list[tuple[int, int]]:
    edges = np.diff(np.r_[False, mask, False].astype(int))
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))


def _rolling_std(values: NDArray[np.float64], window: int) -> NDArray[np.float64]:
    return (
        pd.Series(values)
        .rolling(window, center=True, min_periods=1)
        .std(ddof=0)
        .to_numpy()
    )


def _steady_intervals(
    envelope: NDArray[np.float64], edges: NDArray[np.float64], config: SegmentConfig
) -> list[tuple[int, int]]:
    width = max(1, int(np.ceil(config.min_steady_s / np.median(np.diff(edges)))))
    rolling = pd.Series(envelope).rolling(width, min_periods=width)
    median = rolling.median().to_numpy()
    flat = (
        rolling.max().to_numpy() - rolling.min().to_numpy()
        <= 2 * config.rel_tol * median
    )
    ends = np.flatnonzero(flat & (median >= config.noise_floor)) + 1
    coverage = np.zeros(len(envelope) + 1, dtype=int)
    np.add.at(coverage, ends - width, 1)
    np.add.at(coverage, ends, -1)
    return _runs(np.cumsum(coverage[:-1]) > 0)


def _transition(
    envelope: NDArray[np.float64], steady_rms: float, config: SegmentConfig
) -> int | None:
    low = np.flatnonzero(envelope < config.transition_low * steady_rms)
    if not len(low):
        return None
    start = int(low[-1])
    ramp = envelope[start:]
    if not len(ramp) or ramp[-1] < config.transition_high * steady_rms:
        return None
    if np.any(np.maximum.accumulate(ramp) - ramp > config.rel_tol * steady_rms):
        return None
    return start


def _tag_intervals(
    envelope: NDArray[np.float64], edges: NDArray[np.float64], config: SegmentConfig
) -> list[tuple[int, int, str]]:
    steady = []
    for start, stop in _steady_intervals(envelope, edges, config):
        level = float(np.median(envelope[start:stop]))
        high = np.flatnonzero(envelope[start:stop] >= config.transition_high * level)
        # Loose flatness tolerances can cover the ramp; keep transition
        # endpoints at the configured high level of the steady candidate.
        steady.append((start + int(high[0]), start + int(high[-1]) + 1, level))
    tags = [(start, stop, "steady") for start, stop, _ in steady]
    for index, (start, stop, level) in enumerate(steady):
        left = steady[index - 1][1] if index else 0
        right = steady[index + 1][0] if index + 1 < len(steady) else len(envelope)
        buildup = _transition(envelope[left : start + 1], level, config)
        if buildup is not None and left + buildup < start:
            tags.append((left + buildup, start, "buildup"))
        decay = _transition(envelope[stop - 1 : right][::-1], level, config)
        if decay is not None:
            end = right - decay
            if end > stop:
                tags.append((stop, end, "decay"))
    quiet = envelope < config.noise_floor
    for start, stop, _ in tags:
        quiet[start:stop] = False
    tags.extend((start, stop, "quiet") for start, stop in _runs(quiet))
    return sorted(tags)


def _make_segment(
    time: NDArray[np.float64],
    values: NDArray[np.float64],
    edges: NDArray[np.float64],
    start: int,
    stop: int,
    tag: str,
    record_id: str,
    channel: str,
    config: SegmentConfig,
) -> Segment:
    span = values[start:stop] - np.mean(values[start:stop])
    rms = float(np.sqrt(np.mean(span**2)))
    frequency = None
    if (
        edges[stop] - edges[start] >= config.window_s
        and len(span) >= 2
        and np.ptp(span) > 0
    ):
        spectrum = np.abs(np.fft.rfft((span - np.mean(span)) * np.hanning(len(span))))
        frequencies = np.fft.rfftfreq(len(span), d=float(np.median(np.diff(time))))
        frequency = float(frequencies[1 + np.argmax(spectrum[1:])])
    return Segment(
        record_id, channel, float(edges[start]), float(edges[stop]), tag, rms, frequency
    )


def tag_segments(
    time: ArrayLike,
    values: ArrayLike,
    record_id: str,
    channel: str,
    config: SegmentConfig,
) -> SegmentReport:
    """Tag quiet, steady, buildup and decay intervals from a rolling standard deviation envelope."""
    time, values = np.asarray(time, dtype=float), np.asarray(values, dtype=float)
    if time.ndim != 1 or values.ndim != 1 or len(time) != len(values):
        raise ValueError(
            "time and values must be one-dimensional arrays of equal length"
        )
    if len(time) < 2 or not np.isfinite(time).all() or not np.isfinite(values).all():
        return SegmentReport("not_testable", ())
    if np.any(np.diff(time) <= 0) or time[-1] - time[0] < 2 * config.window_s:
        return SegmentReport("not_testable", ())
    dt = float(np.median(np.diff(time)))
    window = min(len(time), max(1, round(config.window_s / dt)))
    envelope = _rolling_std(values, window)
    edges = np.r_[time, time[-1] + dt]
    tags = _tag_intervals(envelope, edges, config)
    segments = tuple(
        _make_segment(time, values, edges, start, stop, tag, record_id, channel, config)
        for start, stop, tag in tags
    )
    return SegmentReport("ok", segments)
