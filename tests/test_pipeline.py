import json
from dataclasses import asdict

import numpy as np
import pandas as pd
import pytest

from runlog import (
    CheckConfig, SegmentConfig, SegmentReport, __version__, build_catalog,
    check_dataset, load_record, query, run_checks, tag_dataset, tag_segments,
    verify_dataset, write_record,
)
from runlog.cli import main


@pytest.fixture
def dataset(tmp_path):
    time = np.arange(0, 60, 0.05)
    frame = pd.DataFrame({"time": time, "x": np.sin(2 * np.pi * time)})
    write_record(frame, tmp_path, "b", {"x": "m"}, "b.csv")
    frame["y"] = np.cos(2 * np.pi * time)
    write_record(frame, tmp_path, "a", {"x": "m", "y": "m"}, "a.csv")
    (tmp_path / "records/.hidden.json").write_text("invalid")
    return tmp_path


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_check_dataset_results_and_sidecars(dataset, capsys):
    config = CheckConfig(channels=("x",), min_duration_s=100)
    reports = check_dataset(str(dataset), config)
    assert list(reports) == ["a", "b"]
    assert capsys.readouterr().out == ""
    for record_id, results in reports.items():
        frame, meta = load_record(dataset, record_id)
        assert results == run_checks(frame, record_id, config)
        assert any(result.status == "fail" for result in results)
        data = {"record_sha256": meta.sha256, "runlog_version": __version__,
                "config": asdict(config), "checks": [asdict(result) for result in results]}
        assert (dataset / f"checks/{record_id}.json").read_text() == json.dumps(data, indent=2) + "\n"
    assert verify_dataset(dataset) == []


def test_tag_dataset_results_and_channel_preservation(dataset, capsys):
    config = SegmentConfig(0.1)
    first = tag_dataset(str(dataset), "x", config)
    original = read_json(dataset / "segments/a.json")["channels"]["x"]
    reports = tag_dataset(dataset, "y", SegmentConfig(0.2, window_s=2))
    assert list(reports) == ["a", "b"]
    assert capsys.readouterr().out == ""
    assert reports["b"] == SegmentReport("not_testable", ())
    frame, meta = load_record(dataset, "a")
    assert first["a"] == tag_segments(frame.time, frame.x, "a", "x", config)
    data = read_json(dataset / "segments/a.json")
    assert data["record_sha256"] == meta.sha256
    assert data["channels"]["x"] == original
    expected = {**asdict(reports["a"]), "runlog_version": __version__,
                "config": asdict(SegmentConfig(0.2, window_s=2))}
    assert data["channels"]["y"] == json.loads(json.dumps(expected))
    for channel in ("time", "missing"):
        missing = tag_dataset(dataset, channel, config)
        assert all(report == SegmentReport("not_testable", ()) for report in missing.values())
    assert verify_dataset(dataset) == []
    build_catalog(dataset)
    assert {row["channel"] for row in query(dataset, "SELECT DISTINCT channel FROM segments")} == {"x", "y"}


@pytest.mark.parametrize("command", ["check", "tag"])
def test_pipeline_and_cli_write_identical_bytes(dataset, command, capsys):
    if command == "check":
        check_dataset(dataset)
        folder, options, output = "checks", [], "Records checked: 2. Failed checks: 0.\n"
    else:
        tag_dataset(dataset, "x", SegmentConfig(0.1))
        folder, options, output = "segments", ["--channel", "x", "--noise-floor", "0.1"], "Records tagged: 2.\n"
    before = {path.name: path.read_bytes() for path in (dataset / folder).glob("*.json")}
    assert main([command, "--dataset", str(dataset), *options]) == 0
    assert capsys.readouterr().out == output
    assert before == {path.name: path.read_bytes() for path in (dataset / folder).glob("*.json")}


@pytest.mark.parametrize("command", ["check", "tag"])
def test_pipeline_missing_and_empty_dataset(tmp_path, command):
    def analyze():
        return check_dataset(tmp_path) if command == "check" else tag_dataset(tmp_path, "x", SegmentConfig(0.1))

    with pytest.raises(ValueError, match="missing directory: records"):
        analyze()
    (tmp_path / "records").mkdir()
    assert analyze() == {}


def test_tag_rejects_stale_sidecar(dataset):
    tag_dataset(dataset, "x", SegmentConfig(0.1))
    path = dataset / "segments/a.json"
    data = read_json(path)
    data["record_sha256"] = "0" * 64
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="hash mismatch"):
        tag_dataset(dataset, "y", SegmentConfig(0.1))
    assert path.read_bytes() == before
