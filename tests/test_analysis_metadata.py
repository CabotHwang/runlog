import json
from dataclasses import asdict

import numpy as np
import pandas as pd
import pytest

from runlog import CheckConfig, SegmentConfig, __version__, verify_dataset, write_record
from runlog.cli import main


def make_analysis(dataset, command, options=None, channel="x", noise_floor=0.1):
    if not (dataset / "records").exists():
        time = np.arange(0, 60, 0.1)
        frame = pd.DataFrame({"time": time, "x": np.sin(time), "y": np.cos(time)})
        write_record(frame, dataset, "r", {"x": "m", "y": "m"}, "r.csv")
    args = [command, "--dataset", str(dataset)]
    if options is not None:
        config = dataset.parent / "config.json"
        config.write_text(json.dumps(options), encoding="utf-8")
        args.extend(["--config", str(config)])
    if command == "tag":
        args.extend(["--channel", channel, "--noise-floor", str(noise_floor)])
    assert main(args) == 0
    folder = "checks" if command == "check" else "segments"
    path = dataset / folder / "r.json"
    return path, json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("options", [None, {"spike_window": 51, "min_duration_s": 20,
                                         "derivative_pairs": [["x", "y"]]}])
def test_checks_store_effective_config_and_version(tmp_path, options):
    dataset = tmp_path / "dataset"
    _, report = make_analysis(dataset, "check", options)
    expected = json.loads(json.dumps(asdict(CheckConfig(**(options or {})))))
    assert report["runlog_version"] == __version__
    assert report["config"] == expected
    assert verify_dataset(dataset) == []


def test_tag_preserves_each_channels_effective_config(tmp_path):
    dataset = tmp_path / "dataset"
    _, first = make_analysis(dataset, "tag")
    options = {"window_s": 2, "rel_tol": 0.2, "min_steady_s": 5, "noise_floor": 99}
    _, data = make_analysis(dataset, "tag", options, channel="y", noise_floor=0.3)
    assert data["channels"]["x"] == first["channels"]["x"]
    assert data["channels"]["x"]["config"] == asdict(SegmentConfig(0.1))
    report = data["channels"]["y"]
    assert report["runlog_version"] == __version__
    assert report["config"] == asdict(SegmentConfig(**(options | {"noise_floor": 0.3})))
    _, data = make_analysis(dataset, "tag", channel="missing", noise_floor=0.4)
    assert data["channels"]["y"] == report
    missing = data["channels"]["missing"]
    assert missing["status"] == "not_testable"
    assert missing["segments"] == []
    assert missing["runlog_version"] == __version__
    assert missing["config"] == asdict(SegmentConfig(0.4))
    assert verify_dataset(dataset) == []


@pytest.mark.parametrize("command", ["check", "tag"])
@pytest.mark.parametrize("field", ["runlog_version", "config"])
def test_missing_provenance_names_field(tmp_path, command, field):
    dataset = tmp_path / "dataset"
    path, data = make_analysis(dataset, command)
    report = data if command == "check" else data["channels"]["x"]
    del report[field]
    path.write_text(json.dumps(data), encoding="utf-8")
    errors = verify_dataset(dataset)
    assert len(errors) == 1
    assert f"{path.parent.name}/r.json" in errors[0]
    assert errors == [f"invalid analysis sidecar: {path.parent.name}/r.json: missing field {field}"]
    assert main(["verify", "--dataset", str(dataset)]) == 1
    assert main(["index", "--dataset", str(dataset)]) == 2


@pytest.mark.parametrize("command", ["check", "tag"])
@pytest.mark.parametrize("field,value", [("runlog_version", None), ("runlog_version", " "),
                                        ("config", []), ("config", {})])
def test_invalid_provenance_is_schema_error(tmp_path, command, field, value):
    dataset = tmp_path / "dataset"
    path, data = make_analysis(dataset, command)
    report = data if command == "check" else data["channels"]["x"]
    report[field] = value
    path.write_text(json.dumps(data), encoding="utf-8")
    assert "schema error" in verify_dataset(dataset)[0]


@pytest.mark.parametrize("command", ["check", "tag"])
def test_historical_version_is_accepted(tmp_path, command):
    dataset = tmp_path / "dataset"
    path, data = make_analysis(dataset, command)
    report = data if command == "check" else data["channels"]["x"]
    report["runlog_version"] = "0.0.1"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert verify_dataset(dataset) == []
