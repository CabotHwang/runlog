import json
from dataclasses import FrozenInstanceError, replace

import pytest

from runlog import Channel, RecordMeta, SCHEMA_VERSION, __version__


def metadata():
    return RecordMeta("run-1", (Channel("sway", "m"),),
                      {"vr": 5.0, "repeat": 1, "valid": True, "label": "test"},
                      "run.csv", 100, "a" * 64)


def test_roundtrip(tmp_path):
    meta = metadata()
    path = tmp_path / "record.json"
    meta.to_json(path)
    assert RecordMeta.from_json(path) == meta
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == SCHEMA_VERSION == 1
    assert __version__ == "0.2.0"
    with pytest.raises(FrozenInstanceError):
        meta.source = "other.csv"


@pytest.mark.parametrize("record_id", ["", "a" * 65, "../bad", "a b", "a\n", 12, ".r", "_r", "-r"])
def test_invalid_id(record_id):
    with pytest.raises(ValueError, match="record_id"):
        replace(metadata(), record_id=record_id)


@pytest.mark.parametrize("name,unit", [("", "m"), ("time", "s"), ("x", ""), ("x", " "), (1, "m"), ("x", 1)])
def test_invalid_channel(name, unit):
    with pytest.raises(ValueError):
        Channel(name, unit)


@pytest.mark.parametrize("changes", [
    {"channels": (Channel("x", "m"), Channel("x", "N"))},
    {"channels": [Channel("x", "m")]}, {"channels": ("x",)},
    {"attrs": {"x": []}}, {"attrs": {1: "x"}}, {"attrs": []},
    {"source": "/data/run.csv"}, {"source": "C:\\data\\run.csv"},
    {"source": ""}, {"source": ".."}, {"n_samples": -1}, {"n_samples": True},
    {"sha256": "bad"}, {"schema_version": 2}, {"schema_version": True},
])
def test_invalid_metadata(changes):
    with pytest.raises(ValueError):
        replace(metadata(), **changes)


@pytest.mark.parametrize("content", ["not json", "{}", "[]", '{"channels": [null]}'])
def test_invalid_json(tmp_path, content):
    path = tmp_path / "bad.json"
    path.write_text(content)
    with pytest.raises(ValueError, match="sidecar"):
        RecordMeta.from_json(path)


def test_json_requires_schema_version(tmp_path):
    path = tmp_path / "record.json"
    metadata().to_json(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["schema_version"]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="schema_version"):
        RecordMeta.from_json(path)
