import json
import os
import subprocess
import sys

import pytest

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
    capsys.readouterr()
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
    assert all(value in output for value in ("records", "checks", "segments", "16", "320", "81"))
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
