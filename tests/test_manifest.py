import hashlib
import json
from dataclasses import asdict

import pandas as pd
import pytest

from runlog import CheckConfig, __version__, sha256_file, verify_dataset, write_record


def make_record(dataset):
    return write_record(pd.DataFrame({"time": [0, 1], "x": [1, 2]}), dataset,
                        "r", {"x": "m"}, "r.csv")


def test_hash_chunks(tmp_path):
    data = b"abc" * 800_000
    path = tmp_path / "data"
    path.write_bytes(data)
    assert sha256_file(path) == hashlib.sha256(data).hexdigest()


def test_valid_and_extra(tmp_path):
    meta = make_record(tmp_path)
    for folder in ("checks", "segments"):
        (tmp_path / folder).mkdir()
        report = ({"checks": [], "runlog_version": __version__, "config": asdict(CheckConfig())}
                  if folder == "checks" else {"channels": {}})
        (tmp_path / folder / "r.json").write_text(json.dumps({"record_sha256": meta.sha256, **report}))
    (tmp_path / "catalog.sqlite").touch()
    assert verify_dataset(tmp_path) == []
    (tmp_path / "records/extra.txt").touch()
    (tmp_path / "checks/unknown.json").touch()
    assert verify_dataset(tmp_path) == ["extra file: checks/unknown.json", "extra file: records/extra.txt"]


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


@pytest.mark.parametrize("change", [{"schema_version": 99}, {"record_id": "other"}, {"source": "/bad/path"}])
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
