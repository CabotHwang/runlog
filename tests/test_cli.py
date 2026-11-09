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
    assert main(["tag", *base, "--channel", "missing", "--noise-floor", "0.1"]) == 2
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
