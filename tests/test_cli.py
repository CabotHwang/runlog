import json
import os
import subprocess
import sys
from dataclasses import asdict

import numpy as np
import pandas as pd
import pytest

from runlog import (SegmentConfig, __version__, build_catalog, load_record, query,
                    time_monotonic, verify_dataset, write_record)
from runlog.cli import main


def ingest(tmp_path):
    source = tmp_path / "r.csv"
    source.write_text("time,x\n" + "".join(f"{i / 10},{i / 100}\n" for i in range(400)))
    units = tmp_path / "units.json"
    units.write_text('{"x":"m"}')
    dataset = tmp_path / "dataset"
    assert main(["ingest", str(source), "--dataset", str(dataset), "--units", str(units)]) == 0
    return dataset


def test_full_cli(tmp_path, capsys):
    dataset = ingest(tmp_path)
    base = ["--dataset", str(dataset)]
    assert main(["check", *base]) == 0
    config = tmp_path / "segments.json"
    config.write_text('{"window_s":2,"min_steady_s":5}')
    assert main(["tag", *base, "--channel", "x", "--noise-floor", "0.1", "--config", str(config)]) == 0
    assert main(["verify", *base]) == 0
    assert main(["index", *base]) == 0
    output = capsys.readouterr().out
    assert "Records ingested: 1." in output
    assert "Records checked: 1. Failed checks: 0." in output
    assert "Records tagged: 1." in output
    for output in ("json", "csv", "table"):
        assert main(["query", *base, "SELECT record_id FROM records", "--format", output]) == 0
        text = capsys.readouterr().out
        assert "record_id" in text and "r" in text
        if output == "json":
            assert json.loads(text) == [{"record_id": "r"}]
    assert main(["query", *base, "SELECT * FROM records WHERE 0"]) == 0
    assert main(["query", *base, "DELETE FROM records"]) == 2
    assert main(["tag", *base, "--channel", "missing", "--noise-floor", "0.1"]) == 0
    assert main(["tag", *base, "--channel", "x", "--noise-floor", "0"]) == 2
    (dataset / "records/r.parquet").write_bytes(b"corrupt")
    assert main(["verify", *base]) == 1


def test_check_fail_and_config(tmp_path):
    dataset = ingest(tmp_path)
    config = tmp_path / "checks.json"
    config.write_text('{"min_duration_s":100}')
    assert main(["check", "--dataset", str(dataset), "--config", str(config)]) == 1


@pytest.mark.parametrize("args", [[], ["bad"], ["ingest"], ["query", "--dataset", "none", "bad sql"],
                                  ["check", "--dataset", "none"], ["--help"]])
def test_usage_and_data_errors(args):
    assert main(args) == (0 if args == ["--help"] else 2)


def test_openfast_cli_and_bad_json(tmp_path):
    path = tmp_path / "r.out"
    path.write_text("Time X\n(s) (m)\n0 1\n1 2\n")
    units = tmp_path / "units.json"
    units.write_text("{}")
    args = ["ingest", str(path), "--dataset", str(tmp_path / "data"), "--units", str(units)]
    assert main(args) == 0
    assert main(args) == 2
    units.write_text("bad")
    assert main(args) == 2


def test_module_entrypoint():
    result = subprocess.run([sys.executable, "-m", "runlog", "--help"],
                            env=os.environ | {"PYTHONPATH": "src"}, capture_output=True, text=True)
    assert result.returncode == 0
    assert "ingest" in result.stdout


def test_export_cli_environment_and_replace(demo_dataset, tmp_path, monkeypatch, capsys):
    from sqlalchemy import create_engine, inspect

    base = ["export", "--dataset", str(demo_dataset)]
    monkeypatch.delenv("RUNLOG_DB_URL", raising=False)
    assert main(base) == 2
    assert "RUNLOG_DB_URL" in capsys.readouterr().err
    first = f"sqlite:///{tmp_path / 'first.sqlite'}"
    second = f"sqlite:///{tmp_path / 'second.sqlite'}"
    monkeypatch.setenv("RUNLOG_DB_URL", first)
    assert main(base) == 0
    output = capsys.readouterr().out
    assert all(value in output for value in ("records", "checks", "segments", "16", "320", "76"))
    assert main(base) == 2
    assert "exist" in capsys.readouterr().err
    assert main([*base, "--replace"]) == 0
    assert main([*base, "--url", second]) == 0
    engine = create_engine(second)
    assert len(inspect(engine).get_table_names()) == 5
    engine.dispose()


def test_export_cli_masks_errors(demo_dataset, monkeypatch, capsys):
    from uuid import uuid4
    from sqlalchemy.exc import SQLAlchemyError
    import runlog.export as module

    secret = uuid4().hex

    def fail(*args, **kwargs):
        raise SQLAlchemyError(secret)

    monkeypatch.setattr(module, "create_engine", fail)
    assert main(["export", "--dataset", str(demo_dataset), "--url",
                 f"mysql+pymysql://root:{secret}@localhost/runlog"]) == 2
    output = capsys.readouterr()
    assert secret not in output.out + output.err and "***" in output.err


def test_optional_export_dependency(demo_dataset, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "runlog.export", None)
    assert main(["query", "--dataset", str(demo_dataset), "SELECT COUNT(*) FROM records"]) == 0
    assert main(["export", "--dataset", str(demo_dataset), "--url", "sqlite://"]) == 2
    assert "mysql extra" in capsys.readouterr().err


def test_named_query_cli(demo_dataset, capsys):
    from runlog.catalog import named_queries, query

    base = ["query", "--dataset", str(demo_dataset), "--file", "examples/queries.sql"]
    for name, sql in named_queries("examples/queries.sql").items():
        capsys.readouterr()
        assert main([*base, "--name", name, "--format", "json"]) == 0
        assert json.loads(capsys.readouterr().out) == query(demo_dataset, sql)


@pytest.mark.parametrize("options", [[], ["--file", "examples/queries.sql"], ["--name", "a"],
    ["SELECT 1", "--name", "a"], ["SELECT 1", "--file", "examples/queries.sql", "--name", "a"],
    ["--file", "examples/queries.sql", "--name", "missing"], ["--file", "absent.sql", "--name", "a"]])
def test_named_query_cli_errors(demo_dataset, options):
    assert main(["query", "--dataset", str(demo_dataset), *options]) == 2


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_nonfinite_time_fails_check(tmp_path, make_test_record, bad):
    time = np.arange(20, dtype=float)
    time[5] = bad
    result = time_monotonic(time, "r")
    assert result.status == "fail"
    assert result.value >= 1
    make_test_record(tmp_path, time)
    assert main(["check", "--dataset", str(tmp_path)]) == 1


def test_tag_keeps_other_channels_and_skips_missing(tmp_path, make_test_record):
    meta = make_test_record(tmp_path)
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
    assert missing["channels"]["y"] == {"status": "not_testable", "segments": [], "message": "",
        "runlog_version": __version__, "config": asdict(SegmentConfig(0.1))}
    assert main([*base, "x"]) == 0
    build_catalog(tmp_path)
    assert {row["channel"] for row in query(tmp_path, "SELECT DISTINCT channel FROM segments")} == {"x", "y"}
    assert verify_dataset(tmp_path) == []


@pytest.mark.parametrize("overwrite", [False, True])
@pytest.mark.parametrize("mode", ["stem", "parent"])
def test_ingest_duplicate_ids_before_writes(tmp_path, capsys, overwrite, mode):
    paths = ([tmp_path / "one/r.csv", tmp_path / "two/r.csv"] if mode == "stem" else
             [tmp_path / "one/a.csv", tmp_path / "one/b.csv"])
    for path in paths:
        path.parent.mkdir(exist_ok=True)
        path.write_text("time,x\n0,1\n1,2\n", encoding="utf-8")
    units = tmp_path / "units.json"
    units.write_text('{"x":"m"}', encoding="utf-8")
    dataset = tmp_path / "dataset"
    args = ["ingest", *map(str, paths), "--units", str(units), "--dataset", str(dataset),
            "--id-from", mode]
    assert main(args + (["--overwrite"] if overwrite else [])) == 2
    assert "duplicate record" in capsys.readouterr().err
    assert not dataset.exists()


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


def test_corrupt_parquet_is_cli_data_error(tmp_path, make_test_record, capsys):
    make_test_record(tmp_path)
    (tmp_path / "records/r.parquet").write_bytes(b"bad")
    assert main(["check", "--dataset", str(tmp_path)]) == 2
    assert capsys.readouterr().err.startswith("runlog: ")


def test_csv_requires_units_openfast_does_not(tmp_path, capsys):
    path = tmp_path / "r.out"
    path.write_text("Time X\n(s) (m)\n0 1\n1 2\n", encoding="utf-8")
    assert main(["ingest", str(path), "--dataset", str(tmp_path / "data")]) == 0
    assert load_record(tmp_path / "data", "r")[1].channels[0].unit == "m"
    csv = tmp_path / "s.csv"
    csv.write_text("time,x\n0,1\n", encoding="utf-8")
    assert main(["ingest", str(csv), "--dataset", str(tmp_path / "data")]) == 2
    assert "--units" in capsys.readouterr().err


def test_numeric_overflow_is_cli_data_error(tmp_path, capsys):
    write_record(pd.DataFrame({"time": [0, 1]}), tmp_path, "r", {}, "r.csv", {"big": 10**100})
    assert main(["index", "--dataset", str(tmp_path)]) == 2
    assert capsys.readouterr().err.startswith("runlog: ")


@pytest.mark.parametrize("mode", [None, "stem", "parent"])
def test_ingest_ids_and_attribute_priority(tmp_path, mode):
    paths = [tmp_path / "one/first.csv", tmp_path / "two/second.csv"]
    for path in paths:
        path.parent.mkdir(exist_ok=True)
        path.write_text("time,x\n0,1\n1,2\n", encoding="utf-8")
    ids = [p.parent.name if mode == "parent" else p.stem for p in paths]
    attrs = tmp_path / "attrs.json"
    attrs.write_text(json.dumps({ids[0]: {"source": "id"},
                                paths[0].name: {"source": "file"},
                                paths[1].name: {"source": "fallback"}}), encoding="utf-8")
    units = tmp_path / "units.json"
    units.write_text('{"x":"m"}', encoding="utf-8")
    dataset = tmp_path / "dataset"
    args = ["ingest", *map(str, paths), "--units", str(units), "--attrs", str(attrs),
            "--dataset", str(dataset)]
    assert main(args + (["--id-from", mode] if mode else [])) == 0
    assert load_record(dataset, ids[0])[1].attrs == {"source": "id"}
    assert load_record(dataset, ids[1])[1].attrs == {"source": "fallback"}
    assert sorted(p.stem for p in (dataset / "records").glob("*.json")) == sorted(ids)
    attrs.write_text(json.dumps({ids[0]: {}, paths[0].name: {"source": "file"}}))
    assert main(args + ["--overwrite"] + (["--id-from", mode] if mode else [])) == 0
    assert load_record(dataset, ids[0])[1].attrs == {}


def test_ingest_parent_ids_accept_shared_file_name(tmp_path):
    paths = [tmp_path / "one/shared.out", tmp_path / "two/shared.out"]
    for path in paths:
        path.parent.mkdir()
        path.write_text("Time X\n(s) (m)\n0 1\n1 2\n", encoding="utf-8")
    dataset = tmp_path / "dataset"
    assert main(["ingest", *map(str, paths), "--id-from", "parent",
                 "--dataset", str(dataset)]) == 0
    assert load_record(dataset, "one")[1].source == "shared.out"
    assert load_record(dataset, "two")[1].source == "shared.out"


def test_ingest_parent_id_for_relative_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "r.out"
    source.write_text("Time X\n(s) (m)\n0 1\n1 2\n", encoding="utf-8")
    dataset = tmp_path / "data"
    assert main(["ingest", "r.out", "--id-from", "parent", "--dataset", str(dataset)]) == 0
    assert load_record(dataset, tmp_path.name)[1].source == "r.out"
