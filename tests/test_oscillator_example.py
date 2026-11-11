import json
import runpy
from pathlib import Path

import numpy as np
import pytest

from runlog import load_record, query, sha256_file, verify_dataset


def parameters():
    return json.loads(Path("examples/oscillator_case/params.json").read_text(encoding="utf-8"))


def analytic_state(time, p):
    mass = p["mass_kg"]
    wn = 2 * np.pi * p["natural_frequency_hz"]
    omega = 2 * np.pi * p["drive_frequency_hz"]
    beta = p["damping_ratio"] * wn
    wd = np.sqrt(wn**2 - beta**2)
    response = p["force_amplitude_n"] / (mass * (wn**2 - omega**2 + 2j * beta * omega))

    def free(t, x0, v0):
        c, d = x0, (v0 + beta * x0) / wd
        decay = np.exp(-beta * t)
        x = decay * (c * np.cos(wd * t) + d * np.sin(wd * t))
        v = decay * ((-beta * c + wd * d) * np.cos(wd * t) + (-beta * d - wd * c) * np.sin(wd * t))
        return np.array([x, v])

    def driven(t):
        particular = np.array(
            [
                (response * np.exp(1j * omega * t)).imag,
                (1j * omega * response * np.exp(1j * omega * t)).imag,
            ]
        )
        return particular + free(t, -response.imag, -(1j * omega * response).imag)

    states = np.zeros((2, len(time)))
    active = (time >= p["drive_on_s"]) & (time < p["drive_off_s"])
    states[:, active] = driven(time[active] - p["drive_on_s"])
    after = time >= p["drive_off_s"]
    end = driven(p["drive_off_s"] - p["drive_on_s"])
    states[:, after] = free(time[after] - p["drive_off_s"], *end)
    return states.T


def test_numerical_response_matches_independent_closed_form():
    p = parameters()
    simulate = runpy.run_path("examples/run_oscillator_case.py")["simulate"]
    frame = simulate(p)
    exact = analytic_state(frame.time.to_numpy(), p)
    np.testing.assert_allclose(frame[["x", "v"]].to_numpy(), exact, rtol=0, atol=1e-6)
    half = simulate(p | {"dt_s": p["dt_s"] / 2})
    fine_error = np.max(abs(half[["x", "v"]].to_numpy()[::2] - exact))
    coarse_error = np.max(abs(frame[["x", "v"]].to_numpy() - exact))
    assert fine_error < coarse_error / 10


def test_drive_schedule_and_free_decay_energy():
    p = parameters()
    frame = runpy.run_path("examples/run_oscillator_case.py")["simulate"](p)
    assert (frame.loc[frame.time <= p["drive_on_s"], ["x", "v"]] == 0).all().all()
    assert (
        frame.loc[(frame.time < p["drive_on_s"]) | (frame.time >= p["drive_off_s"]), "force"] == 0
    ).all()
    after = frame.loc[frame.time >= p["drive_off_s"]]
    stiffness = p["mass_kg"] * (2 * np.pi * p["natural_frequency_hz"]) ** 2
    energy = (p["mass_kg"] * after.v**2 + stiffness * after.x**2) / 2
    assert np.all(np.diff(energy) <= 1e-12)
    expected_amplitude = p["force_amplitude_n"] / (
        2 * p["mass_kg"] * p["damping_ratio"] * (2 * np.pi * p["natural_frequency_hz"]) ** 2
    )
    steady = frame.loc[(frame.time >= 180) & (frame.time < 230), "x"]
    assert np.std(steady) == pytest.approx(expected_amplitude / np.sqrt(2), rel=0.001)


def test_controlled_example_processing_and_provenance(tmp_path, capsys):
    folder = tmp_path / "dataset"
    run_case = runpy.run_path("examples/run_oscillator_case.py")["run_case"]
    assert run_case(folder) == 0
    assert "13 pass, 0 fail, 0 not testable" in capsys.readouterr().out
    raw = tmp_path / "dataset_input"
    metadata = json.loads((raw / "metadata.json").read_text())
    assert metadata["csv_sha256"] == sha256_file(raw / "forced_oscillator.csv")
    assert metadata["generator_sha256"] == sha256_file(Path("examples/run_oscillator_case.py"))
    assert metadata["sensor_noise_added"] is False
    frame, meta = load_record(folder, "forced_oscillator")
    assert len(frame) == metadata["n_samples"] == 7201
    assert {c.name: c.unit for c in meta.channels} == {"force": "N", "x": "m", "v": "m/s"}
    assert meta.attrs["input_sha256"] == metadata["csv_sha256"]
    assert verify_dataset(folder) == []
    assert query(folder, "SELECT COUNT(*) AS n FROM checks WHERE status='pass'") == [{"n": 13}]
    rows = query(folder, "SELECT tag,start_s,end_s,rms FROM segments ORDER BY start_s")
    assert [s["tag"] for s in rows] == ["quiet", "buildup", "steady", "decay", "quiet"]
    for segment in rows:
        span = frame.loc[(frame.time >= segment["start_s"]) & (frame.time < segment["end_s"]), "x"]
        assert segment["rms"] == pytest.approx(np.std(span))
