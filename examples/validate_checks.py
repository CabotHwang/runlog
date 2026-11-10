"""Reproduce synthetic check characteristics with NumPy and runlog."""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from runlog import CheckConfig, SegmentConfig, __version__, derivative_pair, spikes, tag_segments

SEED = 20261110
RATE = 10
AMPLITUDE = 0.15
NOISE_SD = 0.001
FREQUENCY = 0.2


def _ar_noise(rng, samples):
    values = rng.normal(size=samples)
    values[1:] *= np.sqrt(1 - 0.9**2)
    for i in range(1, samples):
        values[i] += 0.9 * values[i - 1]
    return values


def _spike_trials(trials, samples):
    failures = dict.fromkeys(["gaussian", "ar1_phi_0.9", "uniform", "student_t_df4", "noisy_sine"], 0)
    detections = {(w, h): 0 for w in (1, 2, 3, 5) for h in (10, 20, 50, 200)}
    clean = AMPLITUDE * np.sin(2 * np.pi * FREQUENCY * np.arange(samples) / RATE)
    for seed in range(SEED, SEED + trials):
        rng = np.random.default_rng(seed)
        signals = [rng.normal(size=samples), _ar_noise(rng, samples),
                   rng.uniform(-np.sqrt(3), np.sqrt(3), samples),
                   rng.standard_t(4, samples) / np.sqrt(2),
                   clean + rng.normal(0, NOISE_SD, samples)]
        baselines = [spikes(x, "validation", "x") for x in signals]
        for name, result in zip(failures, baselines):
            failures[name] += int(result.status == "fail")
        index = int(rng.integers(101, samples - 106))
        for width, height in detections:
            faulty = signals[-1].copy()
            faulty[index:index + width] += height * NOISE_SD
            result = spikes(faulty, "validation", "x")
            detections[width, height] += int(result.value > baselines[-1].value)
    false_rows = [{"signal": name, "failed": count, "trials": trials}
                  for name, count in failures.items()]
    hit_rows = [{"width_samples": w, "height_noise_sd": h, "detected": count, "trials": trials}
                for (w, h), count in detections.items()]
    return false_rows, hit_rows


def _pair_trials():
    rows = []
    omega = 2 * np.pi * FREQUENCY
    for rate in (5, 10, 20, 100):
        time = np.arange(600 * rate) / rate
        clean = AMPLITUDE * np.sin(omega * time)
        velocity = AMPLITUDE * omega * np.cos(omega * time)
        for error in (0.02, 0.05, 0.1, None):
            position = clean.copy()
            if error is None:
                position += np.random.default_rng(SEED).normal(0, 0.01 * AMPLITUDE, len(time))
            result = derivative_pair(time, position, velocity * (1 + (error or 0)), "validation", "x")
            rows.append({"rate_hz": rate, "case": "position_noise_1pct" if error is None else f"velocity_scale_{error:.0%}",
                         "score": result.value, "status": result.status, "message": result.message})
    return rows


def _harmonic_pair_trials():
    rate = 160
    time = np.arange(600 * rate) / rate
    omega = 2 * np.pi * FREQUENCY
    position = np.sin(omega * time) + 0.2 * np.sin(4 * omega * time)
    fundamental = omega * np.cos(omega * time)
    harmonic = 0.2 * 4 * omega * np.cos(4 * omega * time)
    rows = []
    for span in (None, 1 / (16 * FREQUENCY)):
        config = CheckConfig(derivative_pair_span_s=span)
        for scale in (1.0, 1.5):
            result = derivative_pair(time, position, fundamental + scale * harmonic,
                                     "validation", "x", config)
            rows.append({"rate_hz": rate, "frequency_hz": FREQUENCY,
                         "position_harmonic_fraction": 0.2, "harmonic_velocity_scale": scale,
                         "derivative_pair_span_s": span, "score": result.value,
                         "status": result.status, "message": result.message})
    return rows


def _steady_row(time, values, config):
    report = tag_segments(time, values, "validation", "x", config)
    segments = [s for s in report.segments if s.tag == "steady"]
    durations = [s.end_s - s.start_s for s in segments]
    total = sum(durations)
    rms = float(np.sqrt(np.average([s.rms**2 for s in segments], weights=durations))) if total else None
    return {"status": report.status, "steady_time_s": float(total), "segment_count": len(segments),
            "segment_rms_m": [s.rms for s in segments], "steady_rms_m": rms}


def _steady_trials(samples):
    time = np.arange(samples) / RATE
    clean = AMPLITUDE * np.sin(2 * np.pi * FREQUENCY * time)
    true_rms = AMPLITUDE / np.sqrt(2)
    limit_rows = []
    for fraction in (0.01, 0.07, 0.2, 0.4):
        sd = fraction * AMPLITUDE
        noisy = clean + np.random.default_rng(SEED).normal(0, sd, samples)
        config = SegmentConfig(noise_floor=3 * sd)
        row = _steady_row(time, noisy, config)
        row.update(noise_amplitude_fraction=fraction, noise_floor_m=config.noise_floor,
                   true_rms_m=float(true_rms), rel_tol=config.rel_tol)
        row["rms_bias_pct"] = None if row["steady_rms_m"] is None else 100 * (row["steady_rms_m"] / true_rms - 1)
        limit_rows.append(row)
    spectrum = np.fft.rfft(np.random.default_rng(SEED).normal(size=samples))
    frequencies = np.fft.rfftfreq(samples, 1 / RATE)
    spectrum[(frequencies < 0.18) | (frequencies > 0.22)] = 0
    random = np.fft.irfft(spectrum, n=samples)
    random *= true_rms / np.std(random)
    random_rows = []
    for tolerance in (0.05, 0.25, 0.5):
        config = SegmentConfig(noise_floor=0.003, rel_tol=tolerance)
        random_rows.append({"rel_tol": tolerance, "noise_floor_m": config.noise_floor,
                            **_steady_row(time, random, config)})
    return limit_rows, random_rows


def measure(trials=20, samples=36000):
    if trials < 1 or samples < 1000:
        raise ValueError("require at least one trial and 1000 samples")
    false_rows, hit_rows = _spike_trials(trials, samples)
    limit_rows, random_rows = _steady_trials(samples)
    return {"schema_version": 1, "runlog_version": __version__,
            "protocol": {"seed_start": SEED, "trials": trials, "samples": samples,
                         "rate_hz": RATE, "duration_s": samples / RATE,
                         "sine_amplitude_m": AMPLITUDE, "sine_frequency_hz": FREQUENCY,
                         "sine_noise_sd_m": NOISE_SD, "pair_duration_s": 600,
                         "position_noise_sd": "1% of sine amplitude",
                         "noise_distributions": "unit SD; stationary AR(1) initial value; Student-t divided by sqrt(2)",
                         "glitch": "one positive rectangular pulse per record at a seeded interior sample",
                         "detection": "event count exceeds matched unmodified record",
                         "steady_rms": "duration-weighted quadratic mean of segment RMS; null when no steady segment",
                         "random_response": "FFT mask 0.18-0.22 Hz; scaled to 0.15/sqrt(2) m SD",
                         "check_config": {"spike_z": CheckConfig().spike_z, "spike_window": CheckConfig().spike_window,
                                          "spike_detrend_window": CheckConfig().spike_detrend_window,
                                          "derivative_pair_rel_tol": CheckConfig().derivative_pair_rel_tol},
                         "segment_config": {"window_s": 10, "min_steady_s": 30, "transition_low": 0.3, "transition_high": 0.9}},
            "spikes_false_alarms": false_rows, "spikes_detection": hit_rows,
            "derivative_pair": _pair_trials(), "derivative_pair_harmonic": _harmonic_pair_trials(), "steady_limit_cycle": limit_rows,
            "steady_random_response": random_rows}


def _table(headers, rows):
    return ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers),
            *["| " + " | ".join(map(str, row)) + " |" for row in rows], ""]


def _number(value, digits=4):
    return "none" if value is None else f"{value:.{digits}f}"


def _markdown(report):
    protocol = report["protocol"]
    lines = ["# Check characteristics", "", "Run `.venv/bin/python examples/validate_checks.py` from the repository root.",
             f"runlog {report['runlog_version']}; seeds start at {SEED}; {protocol['trials']} spike trials, {protocol['samples']} samples per record.",
             f"All records use 10 Hz except the pair tests (600 s at each rate; harmonic case at 160 Hz). Tagging records last {protocol['duration_s']:g} s.",
             "The sine has amplitude 0.15 m and frequency 0.2 Hz. Spike trials add Gaussian noise with SD 0.001 m.",
             "Noise-only trials have unit SD. AR(1) starts in its stationary distribution. Student-t has four degrees of freedom.",
             "Each glitch is one positive rectangular pulse. A detection increases the event count over the matched original record.",
             "Pair position-noise SD is 1% of amplitude. Limit-cycle noise uses the same seeded normal draws at each level.",
             "Random response uses an FFT mask from 0.18 to 0.22 Hz and SD 0.15/sqrt(2) m.",
             "Steady RMS is the duration-weighted quadratic mean of segment RMS values. It includes noise. No segment gives none.",
             "These are measured cases, not probability bounds or guarantees for other signals.", "", "## Spike false alarms", ""]
    lines += _table(["Signal", "Failed / trials"], [(r["signal"], f"{r['failed']}/{r['trials']}") for r in report["spikes_false_alarms"]])
    lines += ["## Spike detections", "", "Heights are multiples of noise SD. Cells give detections / trials.", ""]
    hits = {(r["width_samples"], r["height_noise_sd"]): f"{r['detected']}/{r['trials']}" for r in report["spikes_detection"]}
    lines += _table(["Width (samples)", "10 SD", "20 SD", "50 SD", "200 SD"], [(w, *[hits[w, h] for h in (10, 20, 50, 200)]) for w in (1, 2, 3, 5)])
    lines += ["## Derivative pairs", ""]
    lines += _table(["Rate (Hz)", "Case", "Score", "Status", "Span"], [(r["rate_hz"], r["case"], _number(r["score"], 6), r["status"], r["message"]) for r in report["derivative_pair"]])
    lines += ["## Harmonic pair scope", "",
              "Position is sin(2*pi*0.2*t) + 0.2*sin(2*pi*0.8*t). Only the 0.8 Hz velocity component is scaled.",
              "The automatic span contains one full harmonic period. Its velocity error has zero integral over that span.",
              "Set derivative_pair_span_s to 0.3125 s, one quarter of the harmonic period, to detect this error.", ""]
    lines += _table(["Harmonic velocity scale", "Override (s)", "Score", "Status", "Span"],
                    [(r["harmonic_velocity_scale"], r["derivative_pair_span_s"], f"{r['score']:.10g}", r["status"], r["message"]) for r in report["derivative_pair_harmonic"]])
    lines += ["## Steady limit cycle", "", "True signal RMS is 0.106066 m. Noise floor is three times noise SD; rel_tol is 0.05.", ""]
    lines += _table(["Noise / amplitude", "Steady time (s)", "Segments", "RMS (m)", "Bias (%)"], [(f"{r['noise_amplitude_fraction']:.0%}", _number(r["steady_time_s"], 1), r["segment_count"], _number(r["steady_rms_m"], 6), _number(r["rms_bias_pct"], 2)) for r in report["steady_limit_cycle"]])
    lines += ["## Steady random response", "", "Noise floor is 0.003 m.", ""]
    lines += _table(["rel_tol", "Steady time (s)", "Segments", "RMS (m)"], [(r["rel_tol"], _number(r["steady_time_s"], 1), r["segment_count"], _number(r["steady_rms_m"], 6)) for r in report["steady_random_response"]])
    return "\n".join(lines)


def write_report(report, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    entries = []
    for key, value in report.items():
        if isinstance(value, list):
            encoded = "[\n" + ",\n".join("    " + json.dumps(row, allow_nan=False) for row in value) + "\n  ]"
        else:
            encoded = json.dumps(value, allow_nan=False)
        entries.append("  " + json.dumps(key) + ": " + encoded)
    (output / "check_characteristics.json").write_text("{\n" + ",\n".join(entries) + "\n}\n", encoding="utf-8")
    (output / "README.md").write_text(_markdown(report), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=20)
    parser.add_argument("--samples", type=int, default=36000)
    parser.add_argument("--output", type=Path, default=Path("docs/validation"))
    args = parser.parse_args()
    report = measure(args.trials, args.samples)
    write_report(report, args.output)
    print(_markdown(report))


if __name__ == "__main__":
    main()
