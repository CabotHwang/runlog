import runpy

import numpy as np

from runlog import derivative_pair, load_record


def test_demo_noise_levels_and_repeatability(tmp_path):
    make_demo = runpy.run_path("examples/make_demo_data.py")["make_demo_data"]
    first, second = tmp_path / "first", tmp_path / "second"
    make_demo(first)
    make_demo(second)
    for path in first.iterdir():
        assert path.read_bytes() == (second / path.name).read_bytes()
    data = np.loadtxt(first / "run_01.csv", delimiter=",", skiprows=1)
    time = data[:, 0]
    amplitude = 0.02 + 0.18 * np.exp(-4)
    envelope = np.interp(
        time, [0, 30, 70, 230, 270, 300], [0.002, 0.002, amplitude, amplitude, 0.002, 0.002]
    )
    basis = np.column_stack((np.sin(2 * np.pi * 0.2 * time), np.cos(2 * np.pi * 0.2 * time)))
    clean_sway = (envelope[:, None] * basis) @ np.linalg.lstsq(
        envelope[:, None] * basis, data[:, 1], rcond=None
    )[0]
    residuals = [
        data[:, 1] - clean_sway,
        data[:, 2] - np.gradient(clean_sway, time),
        data[:, 3] - 0.3,
        data[:, 4] - basis @ np.linalg.lstsq(basis, data[:, 4], rcond=None)[0],
    ]
    expected_sd = [0.0005, 0.01 * amplitude * 2 * np.pi * 0.2, 0.003, 0.05]
    np.testing.assert_allclose([np.std(r) for r in residuals], expected_sd, rtol=0.1)
    frozen = np.loadtxt(first / "run_06.csv", delimiter=",", skiprows=1)[:, 4]
    np.testing.assert_array_equal(frozen[1200:1230], np.full(30, frozen[1199]))
    assert frozen[1230] != frozen[1229]
    clipped = np.loadtxt(first / "run_12.csv", delimiter=",", skiprows=1)[:, 1]
    vr = np.linspace(3, 10, 16)[11]
    limit = 0.7 * (0.02 + 0.18 * np.exp(-(((vr - 6) / 1.5) ** 2)))
    assert np.min(clipped) == -limit
    assert np.max(clipped) == limit


def test_demo_derivative_pair_on_small_and_large_responses(demo_dataset):
    frame, _ = load_record(demo_dataset, "run_01")
    result = derivative_pair(frame.time, frame.sway, frame.sway_velocity, "run_01", "sway")
    assert result.status == "fail"
    assert result.value > result.threshold
    frame, _ = load_record(demo_dataset, "run_07")
    result = derivative_pair(frame.time, frame.sway, frame.sway_velocity, "run_07", "sway")
    assert result.status == "pass"


def test_demo_gap_has_no_tags(demo_dataset):
    import json

    from runlog import query

    report = json.loads((demo_dataset / "segments/run_03.json").read_text())["channels"]["sway"]
    assert report["status"] == "not_testable"
    assert report["segments"] == []
    assert "gap" in report["message"]
    assert query(demo_dataset, "SELECT * FROM segments WHERE record_id='run_03'") == []
