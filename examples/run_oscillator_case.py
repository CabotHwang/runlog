"""Generate and process a controlled forced/damped oscillator example."""

import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from runlog import (
    CheckConfig,
    SegmentConfig,
    build_catalog,
    check_dataset,
    query,
    read_csv,
    sha256_file,
    tag_dataset,
    verify_dataset,
    write_record,
)


def forcing(time, params: dict):
    phase = time - params["drive_on_s"]
    active = (time >= params["drive_on_s"]) & (time < params["drive_off_s"])
    return np.where(
        active,
        params["force_amplitude_n"] * np.sin(2 * np.pi * params["drive_frequency_hz"] * phase),
        0.0,
    )


def simulate(params: dict) -> pd.DataFrame:
    mass = params["mass_kg"]
    wn = 2 * np.pi * params["natural_frequency_hz"]
    damping = 2 * mass * params["damping_ratio"] * wn
    stiffness = mass * wn**2
    step = params["dt_s"]
    time = np.arange(round(params["duration_s"] / step) + 1) * step
    states = np.zeros((len(time), 2))

    def rhs(t, state):
        x, velocity = state
        return np.array(
            [velocity, (forcing(t, params) - damping * velocity - stiffness * x) / mass]
        )

    for index, t in enumerate(time[:-1]):
        state = states[index]
        first = rhs(t, state)
        second = rhs(t + step / 2, state + step * first / 2)
        third = rhs(t + step / 2, state + step * second / 2)
        fourth = rhs(t + step, state + step * third)
        states[index + 1] = state + step * (first + 2 * second + 2 * third + fourth) / 6
    return pd.DataFrame(
        {"time": time, "force": forcing(time, params), "x": states[:, 0], "v": states[:, 1]}
    )


def run_case(dataset: Path | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    inputs = root / "examples/oscillator_case"
    params = json.loads((inputs / "params.json").read_text(encoding="utf-8"))
    dataset = dataset if dataset is not None else root / "examples/output/forced_oscillator"
    raw = dataset.parent / (dataset.name + "_input")
    raw.mkdir(parents=True, exist_ok=True)
    frame = simulate(params)
    source = raw / "forced_oscillator.csv"
    frame.to_csv(source, index=False, float_format="%.17g")
    metadata = {
        "record_id": "forced_oscillator",
        "generator": "RK4 forced/damped linear oscillator",
        "equation": "m*xddot + c*xdot + k*x = F(t)",
        "params": params,
        "initial_state_x_v": [0.0, 0.0],
        "units": {"time": "s", "force": "N", "x": "m", "v": "m/s"},
        "solver": "fixed-step classical RK4; integration step equals dt_s",
        "generator_sha256": sha256_file(Path(__file__)),
        "csv_sha256": sha256_file(source),
        "n_samples": len(frame),
        "sensor_noise_added": False,
    }
    (raw / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    write_record(
        read_csv(source),
        dataset,
        "forced_oscillator",
        {"force": "N", "x": "m", "v": "m/s"},
        source.name,
        {
            "generator": metadata["generator"],
            "input_sha256": metadata["csv_sha256"],
            "generator_sha256": metadata["generator_sha256"],
            "params_sha256": sha256_file(inputs / "params.json"),
        },
        overwrite=True,
    )
    config = json.loads((inputs / "checks.json").read_text(encoding="utf-8"))
    reports = check_dataset(dataset, CheckConfig(**config))
    counts = Counter(result.status for results in reports.values() for result in results)
    print(f"Record: forced_oscillator. Samples: {len(frame)}.")
    print(
        f"Checks: {counts['pass']} pass, {counts['fail']} fail, {counts['not_testable']} not testable."
    )
    config = json.loads((inputs / "segments.json").read_text(encoding="utf-8"))
    tags = tag_dataset(dataset, "x", SegmentConfig(**config))["forced_oscillator"]
    print("Tags: " + " → ".join(segment.tag for segment in tags.segments))
    errors = verify_dataset(dataset)
    if errors:
        raise ValueError("; ".join(errors))
    build_catalog(dataset)
    print(
        json.dumps(
            query(dataset, "SELECT tag,start_s,end_s,rms FROM segments ORDER BY start_s"), indent=2
        )
    )
    return int(counts["fail"] > 0)


if __name__ == "__main__":
    raise SystemExit(run_case())
