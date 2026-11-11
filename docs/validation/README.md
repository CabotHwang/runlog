# Check characteristics

Use `.venv/bin/python examples/validate_checks.py` at the root of the repository.

The runlog version is 0.2.4. Seeds start at 20261110.
Each spike case has 20 tests. Each record has 36000 samples.

Records use 10 Hz, except for the pair tests. Pair tests use 600 s at each rate. The harmonic case uses 160 Hz.
The records for tag tests have a duration of 3600 s.

The sine amplitude is 0.15 m. Its frequency is 0.2 Hz. Spike tests add Gaussian noise with standard deviation (SD) 0.001 m.
Noise-only tests use unit SD. AR(1) starts in its stationary distribution. Student-t has four degrees of freedom.

Each glitch is one positive rectangular pulse. A detection adds events to the count for the original record.
The pair tests use position-noise SD of 1% of amplitude. Each limit-cycle noise level uses the same seeded normal draws.

The random response uses an FFT mask from 0.18 to 0.22 Hz. Its SD is 0.15/sqrt(2) m.

The steady RMS is the duration-weighted quadratic mean of segment RMS values. It includes noise. If no segment exists, the table shows none.

These results apply to the specified test signals. They are not probability bounds for other signals.

## Spike false alarms

| Signal | Failed / tests |
|---|---|
| gaussian | 0/20 |
| ar1_phi_0.9 | 0/20 |
| uniform | 0/20 |
| student_t_df4 | 20/20 |
| noisy_sine | 0/20 |

## Spike detections

Pulse heights are multiples of noise SD. Each cell gives detections / tests.

| Width (samples) | 10 SD | 20 SD | 50 SD | 200 SD |
|---|---|---|---|---|
| 1 | 2/20 | 20/20 | 20/20 | 20/20 |
| 2 | 0/20 | 5/20 | 20/20 | 20/20 |
| 3 | 0/20 | 5/20 | 20/20 | 20/20 |
| 5 | 0/20 | 3/20 | 20/20 | 20/20 |

## Derivative pairs

| Rate (Hz) | Case | Score | Status | Span |
|---|---|---|---|---|
| 5 | velocity_scale_2% | 0.027395 | pass | span 6 steps (1.2 s) |
| 5 | velocity_scale_5% | 0.068442 | fail | span 6 steps (1.2 s) |
| 5 | velocity_scale_10% | 0.136854 | fail | span 6 steps (1.2 s) |
| 5 | position_noise_1pct | 0.020038 | pass | span 6 steps (1.2 s) |
| 10 | velocity_scale_2% | 0.027366 | pass | span 12 steps (1.2 s) |
| 10 | velocity_scale_5% | 0.068412 | fail | span 12 steps (1.2 s) |
| 10 | velocity_scale_10% | 0.136821 | fail | span 12 steps (1.2 s) |
| 10 | position_noise_1pct | 0.019951 | pass | span 12 steps (1.2 s) |
| 20 | velocity_scale_2% | 0.029140 | pass | span 26 steps (1.3 s) |
| 20 | velocity_scale_5% | 0.072849 | fail | span 26 steps (1.3 s) |
| 20 | velocity_scale_10% | 0.145697 | fail | span 26 steps (1.3 s) |
| 20 | position_noise_1pct | 0.020187 | pass | span 26 steps (1.3 s) |
| 100 | velocity_scale_2% | 0.028443 | pass | span 126 steps (1.26 s) |
| 100 | velocity_scale_5% | 0.071106 | fail | span 126 steps (1.26 s) |
| 100 | velocity_scale_10% | 0.142213 | fail | span 126 steps (1.26 s) |
| 100 | position_noise_1pct | 0.019981 | pass | span 126 steps (1.26 s) |

## Harmonic pair scope

The position is sin(2*pi*0.2*t) + 0.2*sin(2*pi*0.8*t). The test changes only the scale of the 0.8 Hz velocity component.
The automatic span contains one full harmonic period. Its velocity error has zero integral over that span.
Set derivative_pair_span_s to 0.3125 s, one quarter of the harmonic period, to detect this error.

| Harmonic velocity scale | Override (s) | Score | Status | Span |
|---|---|---|---|---|
| 1.0 | None | 2.92959528e-11 | pass | span 200 steps (1.25 s) |
| 1.5 | None | 2.929616788e-11 | pass | span 200 steps (1.25 s) |
| 1.0 | 0.3125 | 1.500854109e-09 | pass | span 50 steps (0.3125 s) |
| 1.5 | 0.3125 | 0.1386520546 | fail | span 50 steps (0.3125 s) |

## Steady limit cycle

The true signal RMS is 0.106066 m. The noise floor is three times noise SD. The value of rel_tol is 0.05.

| Noise / amplitude | Steady time (s) | Segments | RMS (m) | Bias (%) |
|---|---|---|---|---|
| 1% | 3600.0 | 1 | 0.106059 | -0.01 |
| 7% | 3600.0 | 1 | 0.106464 | 0.38 |
| 20% | 3497.3 | 14 | 0.109803 | 3.52 |
| 40% | 0.0 | 0 | none | none |

## Steady random response

The noise floor is 0.003 m.

| rel_tol | Steady time (s) | Segments | RMS (m) |
|---|---|---|---|
| 0.05 | 0.0 | 0 | none |
| 0.25 | 1552.9 | 34 | 0.124093 |
| 0.5 | 3408.1 | 7 | 0.108360 |
