from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike, NDArray


@dataclass(frozen=True)
class CheckConfig:
    sample_rate_rel_tol: float = 0.01
    gap_factor: float = 3.0
    min_duration_s: float = 10.0
    non_finite_fraction: float = 0.0
    max_flatline_s: float = 2.0
    clipping_fraction: float = 0.01
    clipping_min_run: int = 3
    spike_window: int = 101
    spike_z: float = 8.0
    derivative_pair_rel_tol: float = 0.05
    derivative_pairs: tuple[tuple[str, str], ...] = ()
    resolution_min_fraction: float = 0.05
    expected_rate_hz: float | None = None


    def __post_init__(self) -> None:
        if type(self.spike_window) is not int or self.spike_window < 3 or self.spike_window % 2 == 0:
            raise ValueError("spike_window must be an odd integer of at least 3")


@dataclass(frozen=True)
class CheckResult:
    record_id: str
    check: str
    channel: str | None
    status: str
    value: float | None
    threshold: float | None
    message: str


def _result(record_id: str, check: str, channel: str | None, value: float | None,
            threshold: float, message: str = "") -> CheckResult:
    status = "not_testable" if value is None else ("pass" if value <= threshold else "fail")
    return CheckResult(record_id, check, channel, status, value, threshold,
                       message or ("rule satisfied" if status == "pass" else "threshold exceeded"))


def _time_error(time: NDArray[np.float64]) -> str:
    if len(time) < 10:
        return "fewer than 10 samples"
    if not np.isfinite(time).all():
        return "time contains non-finite values"
    if not np.all(np.diff(time) > 0):
        return "time is not strictly increasing"
    return ""


def _values_error(values: NDArray[np.float64], constant: bool = False) -> str:
    if len(values) < 10:
        return "fewer than 10 samples"
    if not np.isfinite(values).all():
        return "channel contains non-finite values"
    if constant and np.ptp(values) == 0:
        return "channel is constant"
    return ""


def time_monotonic(time: ArrayLike, record_id: str, config: CheckConfig = CheckConfig()) -> CheckResult:
    """Check that time strictly increases."""
    time = np.asarray(time, dtype=float)
    error = "fewer than 2 samples" if len(time) < 2 else ""
    with np.errstate(invalid="ignore"):
        violations = np.count_nonzero(~np.isfinite(time)) + np.count_nonzero(np.diff(time) <= 0)
    value = None if error else float(violations)
    return _result(record_id, "time_monotonic", None, value, 0.0, error)


def _step_resolution(deviation: NDArray[np.float64], roundoff: float,
                     min_fraction: float) -> float:
    nonzero = np.sort(deviation[deviation > roundoff])
    if not len(nonzero):
        return 0.0
    # Group equal magnitudes within the supplied subtraction roundoff.
    starts = np.r_[0, np.flatnonzero(np.diff(nonzero) > roundoff) + 1]
    counts = np.diff(np.r_[starts, len(nonzero)])
    repeated = nonzero[starts[counts >= min_fraction * len(deviation)]]
    return float(repeated[0]) if len(repeated) else 0.0


def sample_rate(time: ArrayLike, record_id: str, config: CheckConfig = CheckConfig()) -> CheckResult:
    """Check sample spacing and exclude steps counted as gaps."""
    time = np.asarray(time, dtype=float)
    error = _time_error(time)
    value, threshold = None, config.sample_rate_rel_tol
    if not error:
        dt = np.diff(time)
        median = np.median(dt)
        regular = dt[dt <= config.gap_factor * median]
        deviation = np.abs(regular - median)
        # Exclude floating-point roundoff when inferring timestamp resolution.
        roundoff = 8 * np.finfo(float).eps * max(np.max(np.abs(time)), median)
        resolution = _step_resolution(deviation, roundoff, config.resolution_min_fraction)
        if resolution:
            threshold = max(threshold, (resolution + roundoff) / median)
        value = float(np.max(deviation) / median)
        if config.expected_rate_hz is not None:
            error = f"expected {config.expected_rate_hz:g} Hz; measured {1 / median:g} Hz"
            rate_error = float(abs(median * config.expected_rate_hz - 1))
            if rate_error > config.sample_rate_rel_tol:
                return _result(record_id, "sample_rate", None, rate_error,
                               config.sample_rate_rel_tol, f"rate mismatch: {error}")
            error = f"maximum relative step error {value:g}; {error}"
    return _result(record_id, "sample_rate", None, value, threshold, error)


def gaps(time: ArrayLike, record_id: str, config: CheckConfig = CheckConfig()) -> CheckResult:
    """Count time steps above the gap limit."""
    time = np.asarray(time, dtype=float)
    error = _time_error(time)
    dt = np.diff(time)
    value = None if error else float(np.count_nonzero(dt > config.gap_factor * np.median(dt)))
    return _result(record_id, "gaps", None, value, 0.0, error)


def duration(time: ArrayLike, record_id: str, config: CheckConfig = CheckConfig()) -> CheckResult:
    """Check the minimum record duration."""
    time = np.asarray(time, dtype=float)
    error = ""
    if len(time) >= 2:
        if not np.isfinite(time).all():
            error = "time contains non-finite values"
        elif not np.all(np.diff(time) > 0):
            error = "time is not strictly increasing"
    value = None if error else (float(time[-1] - time[0]) if len(time) >= 2 else 0.0)
    result = _result(record_id, "duration", None, value, config.min_duration_s, error)
    if value is None:
        return result
    status = "pass" if len(time) >= 2 and value >= config.min_duration_s else "fail"
    return CheckResult(record_id, "duration", None, status, value, config.min_duration_s,
                       "minimum duration satisfied" if status == "pass" else "record is too short")


def non_finite(values: ArrayLike, record_id: str, channel: str,
               config: CheckConfig = CheckConfig()) -> CheckResult:
    """Check the fraction of NaN and infinite channel values."""
    values = np.asarray(values, dtype=float)
    error = "fewer than 10 samples" if len(values) < 10 else ""
    value = None if error else float(np.mean(~np.isfinite(values)))
    return _result(record_id, "non_finite", channel, value, config.non_finite_fraction, error)


def _runs(mask: NDArray[np.bool_]) -> tuple[NDArray[np.intp], NDArray[np.intp]]:
    edges = np.diff(np.r_[False, mask, False].astype(int))
    return np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)


def flatline(time: ArrayLike, values: ArrayLike, record_id: str, channel: str,
             config: CheckConfig = CheckConfig()) -> CheckResult:
    """Measure the longest interval of identical channel values."""
    time, values = np.asarray(time, dtype=float), np.asarray(values, dtype=float)
    error = _time_error(time) or _values_error(values)
    value = None
    if not error:
        starts, stops = _runs(np.diff(values) == 0)
        value = float(np.max(time[stops] - time[starts])) if len(starts) else 0.0
    return _result(record_id, "flatline", channel, value, config.max_flatline_s, error)


def clipping(values: ArrayLike, record_id: str, channel: str,
             config: CheckConfig = CheckConfig()) -> CheckResult:
    """Measure samples in repeated runs at the channel limits."""
    values = np.asarray(values, dtype=float)
    error = _values_error(values, constant=True)
    value = None
    if not error:
        count = 0
        for limit in (np.min(values), np.max(values)):
            starts, stops = _runs(values == limit)
            lengths = stops - starts
            count += int(np.sum(lengths[lengths >= config.clipping_min_run]))
        value = float(count / len(values))
    return _result(record_id, "clipping", channel, value, config.clipping_fraction, error)


def spikes(values: ArrayLike, record_id: str, channel: str,
           config: CheckConfig = CheckConfig()) -> CheckResult:
    """Count robust z-scores above the spike limit."""
    values = np.asarray(values, dtype=float)
    error = _values_error(values)
    value = None
    if not error:
        series = pd.Series(values)
        rolling = series.rolling(config.spike_window, center=True, min_periods=1)
        residual = values - rolling.median().to_numpy()
        mad = rolling.apply(lambda x: np.median(np.abs(x - np.median(x))), raw=True).to_numpy()
        global_mad = np.median(np.abs(residual - np.median(residual)))
        # 101 samples stabilize local MAD; the global floor prevents small local
        # scales from turning Gaussian noise into false alarms at the 8-sigma limit.
        scale = 1.4826 * np.maximum(mad, global_mad)
        steps = np.abs(np.diff(values))
        quantum = _step_resolution(steps, 0.0, config.resolution_min_fraction)
        scale = np.maximum(scale, 1.4826 * quantum)
        if not np.any(scale) and not np.any(residual):
            error = "median absolute deviation is zero"
        else:
            score = np.divide(np.abs(residual), scale,
                              out=np.where(residual == 0, 0.0, np.inf), where=scale > 0)
            value = float(np.count_nonzero(score > config.spike_z))
    return _result(record_id, "spikes", channel, value, 0.0, error)


def derivative_pair(time: ArrayLike, position: ArrayLike, velocity: ArrayLike,
                    record_id: str, channel: str,
                    config: CheckConfig = CheckConfig()) -> CheckResult:
    """Compare position gradients with the paired velocity channel."""
    time = np.asarray(time, dtype=float)
    position, velocity = np.asarray(position, dtype=float), np.asarray(velocity, dtype=float)
    error = _time_error(time) or _values_error(position) or _values_error(velocity, constant=True)
    value = None
    if not error:
        residual = np.gradient(position, time) - velocity
        value = float(np.sqrt(np.mean(residual ** 2)) / np.std(velocity))
    return _result(record_id, "derivative_pair", channel, value, config.derivative_pair_rel_tol, error)


def run_checks(frame: pd.DataFrame, record_id: str,
               config: CheckConfig = CheckConfig()) -> list[CheckResult]:
    """Run time checks, channel checks and configured derivative pairs."""
    if "time" not in frame:
        raise ValueError("missing time column: time")
    time = frame["time"].to_numpy(dtype=float)
    results = [check(time, record_id, config) for check in (time_monotonic, sample_rate, gaps, duration)]
    for channel in frame.columns:
        if channel == "time":
            continue
        values = frame[channel].to_numpy(dtype=float)
        results.append(non_finite(values, record_id, channel, config))
        results.append(flatline(time, values, record_id, channel, config))
        results.extend(check(values, record_id, channel, config) for check in (clipping, spikes))
    for position, velocity in config.derivative_pairs:
        if position not in frame or velocity not in frame:
            results.append(_result(record_id, "derivative_pair", position, None,
                                   config.derivative_pair_rel_tol, "configured channel is missing"))
        else:
            results.append(derivative_pair(time, frame[position], frame[velocity],
                                           record_id, position, config))
    return results
