import hashlib
import json
from dataclasses import asdict

import numpy as np
import pandas as pd
import pytest

from runlog import (
    CheckConfig,
    SegmentConfig,
    __version__,
    build_catalog,
    sha256_file,
    verify_dataset,
    write_record,
)
from runlog.cli import main


def make_record(dataset):
    return write_record(
        pd.DataFrame({"time": [0, 1], "x": [1, 2]}), dataset, "r", {"x": "m"}, "r.csv"
    )


def test_hash_chunks(tmp_path):
    data = b"abc" * 800_000
    path = tmp_path / "data"
    path.write_bytes(data)
    assert sha256_file(path) == hashlib.sha256(data).hexdigest()


def test_valid_and_extra(tmp_path):
    meta = make_record(tmp_path)
    for folder in ("checks", "segments"):
        (tmp_path / folder).mkdir()
        report = (
            {"checks": [], "runlog_version": __version__, "config": asdict(CheckConfig())}
            if folder == "checks"
            else {"channels": {}}
        )
        (tmp_path / folder / "r.json").write_text(
            json.dumps({"record_sha256": meta.sha256, **report})
        )
    (tmp_path / "catalog.sqlite").touch()
    assert verify_dataset(tmp_path) == []
    (tmp_path / "records/extra.txt").touch()
    (tmp_path / "checks/unknown.json").touch()
    assert verify_dataset(tmp_path) == [
        "extra file: checks/unknown.json",
        "extra file: records/extra.txt",
    ]


@pytest.mark.parametrize("extension", ["parquet", "json"])
def test_missing(tmp_path, extension):
    make_record(tmp_path)
    (tmp_path / f"records/r.{extension}").unlink()
    assert verify_dataset(tmp_path) == [f"missing file: records/r.{extension}"]


def test_missing_dataset(tmp_path):
    assert verify_dataset(tmp_path) == ["missing directory: records"]


def test_hash_mismatch(tmp_path):
    make_record(tmp_path)
    (tmp_path / "records/r.parquet").write_bytes(b"corrupt")
    assert verify_dataset(tmp_path) == ["hash mismatch: records/r.parquet"]


@pytest.mark.parametrize(
    "change", [{"schema_version": 99}, {"record_id": "other"}, {"source": "/bad/path"}]
)
def test_bad_sidecar(tmp_path, change):
    make_record(tmp_path)
    path = tmp_path / "records/r.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(change)
    path.write_text(json.dumps(data))
    assert "sidecar schema error" in verify_dataset(tmp_path)[0]


def test_ignore_hidden_files(tmp_path):
    make_record(tmp_path)
    for name in (".DS_Store", "records/.DS_Store", "records/.hidden.json"):
        (tmp_path / name).touch()
    assert verify_dataset(tmp_path) == []


@pytest.mark.parametrize("folder", ["checks", "segments"])
def test_reports_bind_to_record_hash(tmp_path, make_test_record, folder):
    meta = make_test_record(tmp_path)
    assert main(["check", "--dataset", str(tmp_path)]) == 0
    assert main(["tag", "--dataset", str(tmp_path), "--channel", "x", "--noise-floor", "0.1"]) == 0
    path = tmp_path / folder / "r.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["record_sha256"] == meta.sha256
    assert verify_dataset(tmp_path) == []
    data["record_sha256"] = "0" * 64
    path.write_text(json.dumps(data), encoding="utf-8")
    assert verify_dataset(tmp_path) == [f"hash mismatch: {folder}/r.json"]
    with pytest.raises(ValueError, match="mismatch"):
        build_catalog(tmp_path)


@pytest.mark.parametrize("folder", ["checks", "segments"])
def test_old_reports_rejected_after_reingest(tmp_path, make_test_record, folder):
    make_test_record(tmp_path)
    base = ["--dataset", str(tmp_path)]
    assert main(["check", *base]) == 0
    assert main(["tag", *base, "--channel", "x", "--noise-floor", "0.1"]) == 0
    path = tmp_path / folder / "r.json"
    original = path.read_bytes()
    for file in (tmp_path / "records").iterdir():
        file.unlink()
    make_test_record(tmp_path, np.arange(0, 70, 0.1))
    assert not path.exists()
    path.write_bytes(original)
    assert main(["verify", *base]) == 1
    assert main(["index", *base]) == 2


@pytest.mark.parametrize(
    "folder,payload",
    [
        ("checks", []),
        ("checks", {"checks": {}}),
        ("checks", {"checks": [{}]}),
        (
            "checks",
            {
                "checks": [
                    {
                        "record_id": "other",
                        "check": "duration",
                        "channel": None,
                        "status": "bad",
                        "value": 0,
                        "threshold": 10,
                        "message": "bad",
                    }
                ]
            },
        ),
        ("segments", {"channels": []}),
        ("segments", {"channels": {"x": {"status": "bad", "segments": []}}}),
        ("segments", {"channels": {"x": {"status": "ok", "segments": [{}]}}}),
        (
            "segments",
            {
                "channels": {
                    "x": {
                        "status": "ok",
                        "segments": [
                            {
                                "record_id": "r",
                                "channel": "y",
                                "start_s": 0,
                                "end_s": 10,
                                "tag": "quiet",
                                "rms": 0,
                                "peak_freq_hz": None,
                            }
                        ],
                    }
                }
            },
        ),
    ],
)
def test_invalid_analysis_is_reported(tmp_path, make_test_record, folder, payload):
    meta = make_test_record(tmp_path)
    if isinstance(payload, dict):
        payload = {"record_sha256": meta.sha256, **payload}
        if folder == "checks":
            payload.update(runlog_version=__version__, config=asdict(CheckConfig()))
        elif isinstance(payload["channels"], dict):
            for report in payload["channels"].values():
                report.update(runlog_version=__version__, config=asdict(SegmentConfig(0.1)))
    (tmp_path / folder).mkdir()
    (tmp_path / folder / "r.json").write_text(json.dumps(payload), encoding="utf-8")
    assert any("invalid analysis sidecar" in error for error in verify_dataset(tmp_path))
    assert main(["verify", "--dataset", str(tmp_path)]) == 1
    assert main(["index", "--dataset", str(tmp_path)]) == 2
