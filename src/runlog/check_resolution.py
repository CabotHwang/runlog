import numpy as np
from numpy.typing import NDArray


def _step_resolution(steps: NDArray[np.float64], roundoff: float, min_fraction: float) -> float:
    deviation = np.abs(steps - np.median(steps))
    nonzero = np.sort(deviation[deviation > roundoff])
    if not len(nonzero):
        return 0.0
    # Group equal magnitudes within the supplied subtraction roundoff.
    starts = np.r_[0, np.flatnonzero(np.diff(nonzero) > roundoff) + 1]
    counts = np.diff(np.r_[starts, len(nonzero)])
    repeated = nonzero[starts[counts >= min_fraction * len(deviation)]]
    if not len(repeated):
        return 0.0
    resolution = float(repeated[0])
    # Quantization stays near one uniform clock; a sustained rate change drifts away.
    elapsed = np.r_[0.0, np.cumsum(steps)]
    grid = np.arange(len(elapsed)) * np.mean(steps)
    if np.ptp(elapsed - grid) > 2 * resolution + roundoff:
        return 0.0
    return resolution


def _sample_step(time: NDArray[np.float64], gap_factor: float = 3.0) -> float:
    steps = np.diff(time)
    regular = steps[steps <= gap_factor * np.median(steps)]
    return float(np.mean(regular))


def _lattice_quantum(values: NDArray[np.float64]) -> float:
    levels = np.unique(values)
    if len(levels) < 3:
        return 0.0
    spacing = np.diff(levels)
    tolerance = 2 * np.finfo(np.float32).eps * np.max(np.abs(levels))
    minimum = float(np.min(spacing))
    if minimum <= tolerance:
        return 0.0
    # Missing adjacent levels can make the smallest observed gap a multiple of q.
    for divisor in range(1, 33):
        quantum = minimum / divisor
        if quantum <= tolerance:
            return 0.0
        multiples = np.rint(spacing / quantum)
        quantum = float(np.dot(spacing, multiples) / np.dot(multiples, multiples))
        if np.all(np.abs(spacing - multiples * quantum) <= tolerance):
            return quantum
    return 0.0
