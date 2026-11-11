import json
from dataclasses import asdict

import numpy as np
import pytest

from runlog import CheckConfig
from runlog.cli import main


@pytest.mark.parametrize(
    "field",
    [
        "sample_rate_rel_tol",
        "gap_factor",
        "min_duration_s",
        "non_finite_fraction",
        "max_flatline_s",
        "clipping_fraction",
        "spike_z",
        "derivative_pair_rel_tol",
        "resolution_min_fraction",
        "expected_rate_hz",
        "derivative_pair_span_s",
    ],
)
@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf, True, "0.1"])
def test_numeric_config_rejects_nonfinite_and_nonnumeric(field, value):
    with pytest.raises(ValueError, match=field):
        CheckConfig(**{field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("sample_rate_rel_tol", -0.1),
        ("gap_factor", 1),
        ("gap_factor", 0),
        ("min_duration_s", -1),
        ("max_flatline_s", -1),
        ("non_finite_fraction", -0.1),
        ("non_finite_fraction", 1.2),
        ("clipping_fraction", -0.1),
        ("clipping_fraction", 1.2),
        ("spike_z", 0),
        ("derivative_pair_rel_tol", -0.1),
        ("resolution_min_fraction", 0),
        ("resolution_min_fraction", 1.2),
        ("expected_rate_hz", 0),
        ("derivative_pair_span_s", 0),
    ],
)
def test_numeric_config_rejects_out_of_range(field, value):
    with pytest.raises(ValueError, match=field):
        CheckConfig(**{field: value})


@pytest.mark.parametrize("field", ["clipping_min_run", "spike_window", "spike_detrend_window"])
@pytest.mark.parametrize("value", [0, -1, 3.5, True, None])
def test_count_config_requires_valid_integer(field, value):
    with pytest.raises(ValueError, match=field):
        CheckConfig(**{field: value})


def test_numeric_config_accepts_boundaries_and_json_roundtrip():
    config = CheckConfig(
        sample_rate_rel_tol=0,
        gap_factor=1.01,
        min_duration_s=0,
        max_flatline_s=0,
        non_finite_fraction=0,
        clipping_fraction=1,
        clipping_min_run=1,
        derivative_pair_rel_tol=0,
        resolution_min_fraction=1,
        channels=["x"],
        derivative_pairs=[["x", "v"]],
    )
    assert CheckConfig(**json.loads(json.dumps(asdict(config)))) == config


@pytest.mark.parametrize("channels", ["sway", [""], ["time"], [1], ["x", "x"], 1])
def test_config_rejects_invalid_channel_selection(channels):
    with pytest.raises(ValueError, match="channels"):
        CheckConfig(channels=channels)


@pytest.mark.parametrize(
    "pairs",
    ["xv", ["xv"], [["x"]], [["x", "v", "z"]], [["", "v"]], [["x", "time"]], [["x", 1]], None],
)
def test_config_rejects_malformed_pairs(pairs):
    with pytest.raises(ValueError, match="derivative_pairs"):
        CheckConfig(derivative_pairs=pairs)


def test_config_copies_nested_pair_selection():
    pairs = [["x", "v"]]
    config = CheckConfig(derivative_pairs=pairs)
    pairs[0][0] = "changed"
    assert config.derivative_pairs == (("x", "v"),)


@pytest.mark.parametrize(
    "options", [{"expected_rate_hz": float("nan")}, {"non_finite_fraction": 1.2}]
)
def test_cli_rejects_invalid_config_before_writing(tmp_path, make_test_record, capsys, options):
    make_test_record(tmp_path)
    config = tmp_path / "config.json"
    config.write_text(json.dumps(options), encoding="utf-8")
    assert main(["check", "--dataset", str(tmp_path), "--config", str(config)]) == 2
    assert next(iter(options)) in capsys.readouterr().err
    assert not (tmp_path / "checks").exists()
