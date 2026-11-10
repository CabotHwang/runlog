# Check characteristics

Run `.venv/bin/python examples/validate_checks.py` from the repository root.
runlog 0.2.2; seeds start at 20261110; 20 spike trials, 36000 samples per record.
All records use 10 Hz except the pair tests (600 s at each rate). Tagging records last 3600 s.
The sine has amplitude 0.15 m and frequency 0.2 Hz. Spike trials add Gaussian noise with SD 0.001 m.
Noise-only trials have unit SD. AR(1) starts in its stationary distribution. Student-t has four degrees of freedom.
Each glitch is one positive rectangular pulse. A detection increases the event count over the matched original record.
Pair position-noise SD is 1% of amplitude. Limit-cycle noise uses the same seeded normal draws at each level.
Random response uses an FFT mask from 0.18 to 0.22 Hz and SD 0.15/sqrt(2) m.
Steady RMS is the duration-weighted quadratic mean of segment RMS values. It includes noise. No segment gives none.
These are measured cases, not probability bounds or guarantees for other signals.

## Spike false alarms

| Signal | Failed / trials |
|---|---|
| gaussian | 0/20 |
| ar1_phi_0.9 | 0/20 |
| uniform | 0/20 |
| student_t_df4 | 20/20 |
| noisy_sine | 0/20 |

## Spike detections

Heights are multiples of noise SD. Cells give detections / trials.

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

## Steady limit cycle

True signal RMS is 0.106066 m. Noise floor is three times noise SD; rel_tol is 0.05.

| Noise / amplitude | Steady time (s) | Segments | RMS (m) | Bias (%) |
|---|---|---|---|---|
| 1% | 3600.0 | 1 | 0.106059 | -0.01 |
| 7% | 3600.0 | 1 | 0.106464 | 0.38 |
| 20% | 3497.4 | 13 | 0.109802 | 3.52 |
| 40% | 0.0 | 0 | none | none |

## Steady random response

Noise floor is 0.003 m.

| rel_tol | Steady time (s) | Segments | RMS (m) |
|---|---|---|---|
| 0.05 | 0.0 | 0 | none |
| 0.25 | 1553.1 | 34 | 0.124086 |
| 0.5 | 3408.1 | 7 | 0.108360 |
