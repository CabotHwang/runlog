import json
import os
from pathlib import Path
import subprocess

from runlog import build_catalog, query, verify_dataset
from runlog.cli import main


def test_quickstart():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(["bash", "examples/quickstart.sh"], cwd=root,
                            capture_output=True, text=True, env=os.environ)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Records checked: 16. Failed checks: 5." in result.stdout
    dataset = root / "examples/output/dataset"
    expected = {"run_03": [("gaps", None)], "run_06": [("flatline", "fx")],
                "run_09": [("spikes", "sway")], "run_12": [("clipping", "sway")],
                "run_15": [("non_finite", "fx")]}
    for index in range(1, 17):
        record_id = f"run_{index:02d}"
        checks = json.loads((dataset / f"checks/{record_id}.json").read_text(encoding="utf-8"))["checks"]
        failed = [(r["check"], r["channel"]) for r in checks if r["status"] == "fail"]
        assert failed == expected.get(record_id, [])
        if record_id not in expected:
            assert all(row["status"] == "pass" for row in checks)
            report = json.loads((dataset / f"segments/{record_id}.json").read_text(encoding="utf-8"))["channels"]["sway"]
            assert [s["tag"] for s in report["segments"]] == ["quiet", "buildup", "steady", "decay", "quiet"]
    assert verify_dataset(dataset) == []
    rows = query(dataset, "SELECT DISTINCT record_id FROM segments WHERE tag='steady' AND record_id NOT IN "
                 "(SELECT record_id FROM checks WHERE status='fail') ORDER BY record_id")
    assert rows == [{"record_id": f"run_{i:02d}"} for i in range(1, 17) if f"run_{i:02d}" not in expected]
    assert query(dataset, "SELECT MIN(value_num) AS low, MAX(value_num) AS high FROM attrs "
                 "WHERE key='vr' AND record_id NOT IN "
                 "(SELECT record_id FROM checks WHERE status='fail')") == [{"low": 3.0, "high": 10.0}]
    for file in dataset.rglob("*.json"):
        assert str(root) not in file.read_text(encoding="utf-8")


def test_all_json_reads_use_utf8(tmp_path, make_test_record, monkeypatch):
    dataset = tmp_path / "dataset"
    make_test_record(dataset)
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
