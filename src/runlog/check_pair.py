import numpy as np
from numpy.typing import NDArray


def _pair_span(position: NDArray, dt: float, span_s: float | None) -> int:
    if span_s is None:
        centered = position - np.mean(position)
        spectrum = np.abs(np.fft.rfft(centered * np.hanning(len(position))))
        peak = 1 + int(np.argmax(spectrum[1:]))
        steps = len(position) / (4 * peak)
    else:
        steps = span_s / dt
    return max(2, 2 * int(np.floor(steps / 2 + 0.5)))


def _simpson_spans(velocity: NDArray, dt: float, steps: int) -> NDArray:
    panels = dt / 3 * (velocity[:-2] + 4 * velocity[1:-1] + velocity[2:])
    # Separate cumulative integrals for spans starting on each sample parity.
    integral = np.zeros(len(velocity))
    integral[2::2] = np.cumsum(panels[::2])
    integral[3::2] = np.cumsum(panels[1::2])
    return integral[steps:] - integral[:-steps]
