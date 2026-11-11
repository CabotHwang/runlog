import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from runlog import (
    SegmentConfig,
    check_dataset,
    load_record,
    tag_dataset,
    verify_dataset,
    write_record,
)


@pytest.fixture
def record(tmp_path):
    time = np.arange(600) / 10
    frame = pd.DataFrame({"time": time, "x": np.sin(time)})
    write_record(frame, tmp_path, "r", {"x": "m"}, "r.csv")
    return tmp_path, frame


def test_loading_changed_parquet_rejects_the_old_hash(record):
    dataset, frame = record
    frame["x"] *= 2
    frame.to_parquet(dataset / "records/r.parquet", index=False)
    with pytest.raises(ValueError, match="hash mismatch"):
        load_record(dataset, "r")


@pytest.mark.parametrize("analysis", ["check", "tag"])
def test_changed_data_cannot_overwrite_analysis_under_old_hash(record, analysis):
    dataset, frame = record
    config = SegmentConfig(0.005)
    check_dataset(dataset)
    tag_dataset(dataset, "x", config)
    paths = [dataset / folder / "r.json" for folder in ("checks", "segments")]
    before = [path.read_bytes() for path in paths]
    frame["x"] *= 2
    frame.to_parquet(dataset / "records/r.parquet", index=False)
    with pytest.raises(ValueError, match="hash mismatch"):
        if analysis == "check":
            check_dataset(dataset)
        else:
            tag_dataset(dataset, "x", config)
    assert [path.read_bytes() for path in paths] == before


@pytest.mark.parametrize("field", ["record_id", "n_samples", "channels"])
def test_loading_checks_the_record_metadata_contract(record, field):
    dataset, _ = record
    path = dataset / "records/r.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if field == "record_id":
        data[field] = "another"
    elif field == "n_samples":
        data[field] += 1
    else:
        data[field][0]["name"] = "another"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="mismatch"):
        load_record(dataset, "r")


@pytest.mark.parametrize("field", ["n_samples", "channels"])
def test_verification_checks_the_parquet_metadata_contract(record, field):
    dataset, _ = record
    path = dataset / "records/r.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if field == "n_samples":
        data[field] += 1
    else:
        data[field][0]["name"] = "another"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert any("mismatch" in error for error in verify_dataset(dataset))


def test_matching_hash_does_not_make_invalid_parquet_valid(record):
    dataset, _ = record
    parquet = dataset / "records/r.parquet"
    parquet.write_bytes(b"not a Parquet file")
    path = dataset / "records/r.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["sha256"] = hashlib.sha256(parquet.read_bytes()).hexdigest()
    path.write_text(json.dumps(data), encoding="utf-8")
    assert any("invalid Parquet file" in error for error in verify_dataset(dataset))
    with pytest.raises(ValueError, match="invalid Parquet file"):
        load_record(dataset, "r")
