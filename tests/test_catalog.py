import json
import sqlite3
from dataclasses import asdict

import numpy as np
import pandas as pd
import pytest

from runlog import (CheckConfig, SegmentConfig, __version__, build_catalog, query,
                    run_checks, tag_segments, write_record)


def dataset(path):
    time = np.arange(0, 60, 0.1)
    frame = pd.DataFrame({"time": time, "sway": np.sin(time)})
    meta = write_record(frame, path, "r", {"sway": "m"}, "r.csv",
                        {"vr": 5, "label": "test", "active": True})
    (path / "checks").mkdir()
    checks = {"record_sha256": meta.sha256, "runlog_version": __version__,
              "config": asdict(CheckConfig()), "checks": [asdict(r) for r in run_checks(frame, "r")]}
    (path / "checks/r.json").write_text(json.dumps(checks), encoding="utf-8")
    (path / "segments").mkdir()
    config = SegmentConfig(0.1, window_s=10, rel_tol=0.2)
    report = tag_segments(time, frame.sway, "r", "sway", config)
    segments = {"record_sha256": meta.sha256, "channels": {"sway": {
        **asdict(report), "runlog_version": __version__, "config": asdict(config)}}}
    (path / "segments/r.json").write_text(json.dumps(segments), encoding="utf-8")


def test_catalog_rebuild_and_rows(tmp_path):
    dataset(tmp_path)
    build_catalog(tmp_path)
    rows = query(tmp_path, "SELECT * FROM records")
    assert rows[0]["record_id"] == "r"
    assert rows[0]["n_samples"] == 600
    assert rows[0]["duration_s"] == pytest.approx(59.9)
    assert rows[0]["sample_rate_hz"] == pytest.approx(10)
    assert query(tmp_path, "SELECT * FROM channels") == [{"record_id": "r", "name": "sway", "unit": "m"}]
    assert query(tmp_path, "SELECT value_text FROM attrs WHERE key='label'") == [{"value_text": "test"}]
    assert query(tmp_path, "SELECT COUNT(*) AS n FROM checks") == [{"n": 8}]
    assert query(tmp_path, "SELECT tag FROM segments") == [{"tag": "steady"}]
    build_catalog(tmp_path)
    assert query(tmp_path, "SELECT * FROM records") == rows
    with sqlite3.connect(tmp_path / "catalog.sqlite") as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert len(connection.execute("PRAGMA index_list(segments)").fetchall()) == 1
        assert connection.execute("PRAGMA index_list(checks)").fetchone()[1] == "checks_record_status"
        columns = connection.execute("PRAGMA index_info(checks_record_status)").fetchall()
        assert [column[2] for column in columns] == ["record_id", "status"]


@pytest.mark.parametrize("sql", ["DELETE FROM records", "CREATE TABLE bad(x)", "UPDATE attrs SET value_num=0"])
def test_query_read_only(tmp_path, sql):
    dataset(tmp_path)
    build_catalog(tmp_path)
    with pytest.raises(sqlite3.DatabaseError):
        query(tmp_path, sql)


def test_failed_rebuild_preserves_catalog(tmp_path):
    dataset(tmp_path)
    build_catalog(tmp_path)
    original = (tmp_path / "catalog.sqlite").read_bytes()
    (tmp_path / "checks/r.json").write_text("bad json")
    with pytest.raises(ValueError):
        build_catalog(tmp_path)
    assert (tmp_path / "catalog.sqlite").read_bytes() == original
    assert not list(tmp_path.glob(".catalog-*"))
    (tmp_path / "records/r.parquet").write_bytes(b"bad")
    with pytest.raises(ValueError, match="hash mismatch"):
        build_catalog(tmp_path)


def test_optional_reports_and_bad_time(tmp_path):
    write_record(pd.DataFrame({"time": [1, 0], "x": [0, 1]}), tmp_path, "r", {"x": "m"}, "r.csv")
    build_catalog(tmp_path)
    assert query(tmp_path, "SELECT duration_s, sample_rate_hz FROM records") == [
        {"duration_s": None, "sample_rate_hz": None}]


def test_query_bound_parameters(tmp_path):
    dataset(tmp_path)
    build_catalog(tmp_path)
    assert query(tmp_path, "SELECT record_id FROM attrs WHERE key=? AND value_num>=?",
                 ("vr", 5)) == [{"record_id": "r"}]
    assert query(tmp_path, "SELECT record_id FROM attrs WHERE key=?", ("' OR 1=1 --",)) == []


def test_connections_close_before_replace_and_after_errors(tmp_path, monkeypatch):
    dataset(tmp_path)
    connections = []
    connect = sqlite3.connect
    replace = type(tmp_path).replace

    class TrackedConnection(sqlite3.Connection):
        closed = False

        def close(self):
            super().close()
            self.closed = True

    def tracked_connect(*args, **kwargs):
        connection = connect(*args, **kwargs, factory=TrackedConnection)
        connections.append(connection)
        return connection

    def checked_replace(path, destination):
        assert all(connection.closed for connection in connections)
        return replace(path, destination)

    monkeypatch.setattr(sqlite3, "connect", tracked_connect)
    monkeypatch.setattr(type(tmp_path), "replace", checked_replace)
    build_catalog(tmp_path)
    assert query(tmp_path, "SELECT COUNT(*) AS n FROM records") == [{"n": 1}]
    assert all(connection.closed for connection in connections)
    with pytest.raises(sqlite3.DatabaseError):
        query(tmp_path, "DELETE FROM records")
    assert all(connection.closed for connection in connections)
    (tmp_path / "checks/r.json").write_text("bad json")
    with pytest.raises(ValueError):
        build_catalog(tmp_path)
    assert all(connection.closed for connection in connections)
