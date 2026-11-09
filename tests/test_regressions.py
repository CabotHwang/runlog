import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from runlog import (
    build_catalog, duration, load_record, query, sample_rate, spikes,
    tag_segments, SegmentConfig, time_monotonic, verify_dataset, write_record,
)
from runlog.cli import main


def record(path, time=None, channel="x"):
    time = np.arange(0, 60, 0.1) if time is None else np.asarray(time)
    return write_record(pd.DataFrame({"time": time, channel: np.sin(np.arange(len(time)) * 0.1)}),
                        path, "r", {channel: "m"}, "r.csv")


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_nonfinite_time_fails_check(tmp_path, bad):
    time = np.arange(20, dtype=float)
    time[5] = bad
    result = time_monotonic(time, "r")
    assert result.status == "fail"
    assert result.value >= 1
    record(tmp_path, time)
    assert main(["check", "--dataset", str(tmp_path)]) == 1


def test_time_violation_count_and_short_records():
    assert time_monotonic([0, np.nan, 1, 1, np.inf, -np.inf], "r").value == 5
    assert time_monotonic([1, 0], "r").value == 1
    assert time_monotonic([0, 1], "r").status == "pass"
    assert time_monotonic([np.nan], "r").status == "not_testable"


@pytest.mark.parametrize("time,status", [([], "fail"), ([0], "fail"),
    ([0, 1, 2], "fail"), ([0, 10], "pass"), ([0, 5, 10], "pass"),
    ([0, np.nan], "not_testable"), ([1, 0], "not_testable")])
def test_short_duration(time, status):
    assert duration(time, "r").status == status


@pytest.mark.parametrize("hz", [30, 60, 128])
def test_rounded_timestamps(hz):
    time = np.round(np.arange(hz * 20) / hz, 3)
    assert sample_rate(time, "r").status == "pass"


def test_quantized_spikes():
    values = np.zeros(200)
    values[[20, 50, 80]] = [1, 2, 3]
    assert spikes(values, "r", "x").value == 0
    values[120] = 30
    assert spikes(values, "r", "x").value == 1


def test_constant_segment_has_no_frequency():
    time = np.arange(0, 60, 0.1)
    report = tag_segments(time, np.ones(len(time)), "r", "x", SegmentConfig(0.1))
    assert report.segments
    assert all(segment.peak_freq_hz is None for segment in report.segments)


@pytest.mark.parametrize("overwrite", [False, True])
def test_write_clears_old_analysis(tmp_path, overwrite):
    record(tmp_path)
    for folder in ("checks", "segments"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "r.json").write_text("{}", encoding="utf-8")
    if not overwrite:
        for path in (tmp_path / "records").iterdir():
            path.unlink()
    frame = pd.DataFrame({"time": [0, 1], "x": [2, 3]})
    write_record(frame, tmp_path, "r", {"x": "m"}, "r.csv", overwrite=overwrite)
    assert all(not (tmp_path / folder / "r.json").exists() for folder in ("checks", "segments"))


@pytest.mark.parametrize("folder", ["checks", "segments"])
def test_reports_bind_to_record_hash(tmp_path, folder):
    meta = record(tmp_path)
    assert main(["check", "--dataset", str(tmp_path)]) == 0
    assert main(["tag", "--dataset", str(tmp_path), "--channel", "x", "--noise-floor", "0.1"]) == 0
    path = tmp_path / folder / "r.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["record_sha256"] == meta.sha256
    assert verify_dataset(tmp_path) == []
    data["record_sha256"] = "0" * 64
    path.write_text(json.dumps(data), encoding="utf-8")
    assert any(f"{folder}/r.json" in error and "mismatch" in error for error in verify_dataset(tmp_path))
    with pytest.raises(ValueError, match="mismatch"):
        build_catalog(tmp_path)


def test_tag_keeps_other_channels_and_skips_missing(tmp_path):
    meta = record(tmp_path)
    frame, _ = load_record(tmp_path, "r")
    frame["y"] = np.cos(frame.time)
    meta = write_record(frame, tmp_path, "r", {"x": "m", "y": "m"}, "r.csv", overwrite=True)
    write_record(frame.drop(columns="y"), tmp_path, "a", {"x": "m"}, "a.csv")
    base = ["tag", "--dataset", str(tmp_path), "--noise-floor", "0.1", "--channel"]
    assert main([*base, "x"]) == 0
    path = tmp_path / "segments/r.json"
    first = json.loads(path.read_text(encoding="utf-8"))["channels"]["x"]
    assert main([*base, "y"]) == 0
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["record_sha256"] == meta.sha256
    assert data["channels"]["x"] == first
    assert data["channels"]["y"]["status"] == "ok"
    missing = json.loads((tmp_path / "segments/a.json").read_text(encoding="utf-8"))
    assert missing["channels"]["y"] == {"status": "not_testable", "segments": []}
    assert main([*base, "x"]) == 0
    build_catalog(tmp_path)
    assert {row["channel"] for row in query(tmp_path, "SELECT DISTINCT channel FROM segments")} == {"x", "y"}
    assert verify_dataset(tmp_path) == []


@pytest.mark.parametrize("overwrite", [False, True])
def test_ingest_duplicate_stems_before_writes(tmp_path, capsys, overwrite):
    paths = [tmp_path / "one/r.csv", tmp_path / "two/r.csv"]
    for path in paths:
        path.parent.mkdir()
        path.write_text("time,x\n0,1\n1,2\n", encoding="utf-8")
    units = tmp_path / "units.json"
    units.write_text('{"x":"m"}', encoding="utf-8")
    dataset = tmp_path / "dataset"
    args = ["ingest", *map(str, paths), "--units", str(units), "--dataset", str(dataset)]
    assert main(args + (["--overwrite"] if overwrite else [])) == 2
    assert "duplicate record" in capsys.readouterr().err
    assert not dataset.exists()


@pytest.mark.parametrize("sql", ["ATTACH DATABASE ? AS other", "VACUUM INTO ?",
    "CREATE TABLE bad(x)", "DELETE FROM records", "PRAGMA user_version=3"])
def test_query_denies_file_creation_and_writes(tmp_path, sql):
    record(tmp_path)
    build_catalog(tmp_path)
    destination = tmp_path / "leaked.sqlite"
    with pytest.raises(sqlite3.DatabaseError):
        query(tmp_path, sql, (str(destination),) if "?" in sql else ())
    assert not destination.exists()


def test_all_json_reads_use_utf8(tmp_path, monkeypatch):
    dataset = tmp_path / "dataset"
    record(dataset)
    original = Path.read_text

    def checked_read(path, *args, **kwargs):
        if path.suffix == ".json":
            assert kwargs.get("encoding") == "utf-8"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", checked_read)
    units = tmp_path / "units.json"
    units.write_text('{"x":"m"}', encoding="utf-8")
    attrs = tmp_path / "attrs.json"
    attrs.write_text('{"s.csv":{"label":"海"}}', encoding="utf-8")
    config = tmp_path / "config.json"
    config.write_text('{}', encoding="utf-8")
    csv = tmp_path / "s.csv"
    csv.write_text("time,x\n0,1\n1,2\n", encoding="utf-8")
    assert main(["ingest", str(csv), "--units", str(units), "--attrs", str(attrs),
                 "--dataset", str(dataset)]) == 0
    assert main(["check", "--dataset", str(dataset), "--config", str(config)]) == 1
    assert main(["tag", "--dataset", str(dataset), "--channel", "x", "--noise-floor", "0.1",
                 "--config", str(config)]) == 0
    assert verify_dataset(dataset) == []
    build_catalog(dataset)
    assert query(dataset, "SELECT value_text FROM attrs WHERE key='label'") == [{"value_text": "海"}]


@pytest.mark.parametrize("content", ["[]", "null", "1", '"text"'])
def test_bad_json_object_is_cli_data_error(tmp_path, capsys, content):
    csv = tmp_path / "r.csv"
    csv.write_text("time,x\n0,1\n1,2\n", encoding="utf-8")
    attrs = tmp_path / "attrs.json"
    attrs.write_text(content, encoding="utf-8")
    units = tmp_path / "units.json"
    units.write_text('{"x":"m"}', encoding="utf-8")
    assert main(["ingest", str(csv), "--dataset", str(tmp_path / "data"),
                 "--units", str(units), "--attrs", str(attrs)]) == 2
    assert capsys.readouterr().err.startswith("runlog: ")


def test_corrupt_parquet_is_cli_data_error(tmp_path, capsys):
    record(tmp_path)
    (tmp_path / "records/r.parquet").write_bytes(b"bad")
    assert main(["check", "--dataset", str(tmp_path)]) == 2
    assert capsys.readouterr().err.startswith("runlog: ")


@pytest.mark.parametrize("record_id", [".r", "_r", "-r"])
def test_id_must_start_with_letter_or_digit(tmp_path, record_id):
    with pytest.raises(ValueError, match="record_id"):
        write_record(pd.DataFrame({"time": [0, 1]}), tmp_path, record_id, {}, "r.csv")


def test_openfast_needs_no_units_csv_does(tmp_path, capsys):
    path = tmp_path / "r.out"
    path.write_text("Time X\n(s) (m)\n0 1\n1 2\n", encoding="utf-8")
    assert main(["ingest", str(path), "--dataset", str(tmp_path / "data")]) == 0
    assert load_record(tmp_path / "data", "r")[1].channels[0].unit == "m"
    csv = tmp_path / "s.csv"
    csv.write_text("time,x\n0,1\n", encoding="utf-8")
    assert main(["ingest", str(csv), "--dataset", str(tmp_path / "data")]) == 2
    assert "--units" in capsys.readouterr().err


def test_readme_install_and_limits():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "python3 -m venv" in readme
    limits = readme.split("## Limits", 1)[1].lower()
    assert all(word in limits for word in ("rounded", "simulated", "extrema", "clipping", "ramp", "rms"))


@pytest.mark.parametrize("folder", ["checks", "segments"])
def test_old_reports_rejected_after_reingest(tmp_path, folder):
    record(tmp_path)
    base = ["--dataset", str(tmp_path)]
    assert main(["check", *base]) == 0
    assert main(["tag", *base, "--channel", "x", "--noise-floor", "0.1"]) == 0
    path = tmp_path / folder / "r.json"
    original = path.read_bytes()
    for file in (tmp_path / "records").iterdir():
        file.unlink()
    record(tmp_path, np.arange(0, 70, 0.1))
    assert not path.exists()
    path.write_bytes(original)
    assert main(["verify", *base]) == 1
    assert main(["index", *base]) == 2


@pytest.mark.parametrize("folder,payload", [
    ("checks", []), ("checks", {"checks": {}}), ("checks", {"checks": [{}]}),
    ("checks", {"checks": [{"record_id": "other", "check": "duration", "channel": None,
        "status": "bad", "value": 0, "threshold": 10, "message": "bad"}]}),
    ("segments", {"channels": []}),
    ("segments", {"channels": {"x": {"status": "bad", "segments": []}}}),
    ("segments", {"channels": {"x": {"status": "ok", "segments": [{}]}}}),
    ("segments", {"channels": {"x": {"status": "ok", "segments": [{"record_id": "r",
        "channel": "y", "start_s": 0, "end_s": 10, "tag": "quiet", "rms": 0,
        "peak_freq_hz": None}]}}}),
])
def test_invalid_analysis_is_reported(tmp_path, folder, payload):
    meta = record(tmp_path)
    if isinstance(payload, dict):
        payload = {"record_sha256": meta.sha256, **payload}
    (tmp_path / folder).mkdir()
    (tmp_path / folder / "r.json").write_text(json.dumps(payload), encoding="utf-8")
    assert any("invalid analysis sidecar" in error for error in verify_dataset(tmp_path))
    assert main(["verify", "--dataset", str(tmp_path)]) == 1
    assert main(["index", "--dataset", str(tmp_path)]) == 2


def test_numeric_overflow_is_cli_data_error(tmp_path, capsys):
    write_record(pd.DataFrame({"time": [0, 1]}), tmp_path, "r", {}, "r.csv", {"big": 10**100})
    assert main(["index", "--dataset", str(tmp_path)]) == 2
    assert capsys.readouterr().err.startswith("runlog: ")


def test_read_queries_include_functions_and_recursive_ctes(tmp_path):
    record(tmp_path)
    build_catalog(tmp_path)
    assert query(tmp_path, "SELECT length(record_id) AS n FROM records") == [{"n": 1}]
    assert query(tmp_path, "WITH RECURSIVE t(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM t WHERE n<3) "
                 "SELECT sum(n) AS total FROM t") == [{"total": 6}]
