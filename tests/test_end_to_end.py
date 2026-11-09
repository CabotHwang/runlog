import json
import os
from pathlib import Path
import subprocess

from runlog import query, verify_dataset


def test_quickstart():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(["bash", "examples/quickstart.sh"], cwd=root,
                            capture_output=True, text=True, env=os.environ)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Checked 16 records: 5 failed checks." in result.stdout
    dataset = root / "examples/output/dataset"
    expected = {"run_03": [("gaps", None)], "run_06": [("flatline", "fx")],
                "run_09": [("spikes", "sway")], "run_12": [("clipping", "sway")],
                "run_15": [("non_finite", "fx")]}
    for index in range(1, 17):
        record_id = f"run_{index:02d}"
        checks = json.loads((dataset / f"checks/{record_id}.json").read_text())
        failed = [(r["check"], r["channel"]) for r in checks if r["status"] == "fail"]
        assert failed == expected.get(record_id, [])
        if record_id not in expected:
            assert all(row["status"] == "pass" for row in checks)
            report = json.loads((dataset / f"segments/{record_id}.json").read_text())
            assert [s["tag"] for s in report["segments"]] == ["quiet", "buildup", "steady", "decay", "quiet"]
    assert verify_dataset(dataset) == []
    rows = query(dataset, "SELECT DISTINCT record_id FROM segments WHERE tag='steady' AND record_id NOT IN "
                 "(SELECT record_id FROM checks WHERE status='fail') ORDER BY record_id")
    assert rows == [{"record_id": f"run_{i:02d}"} for i in range(1, 17) if f"run_{i:02d}" not in expected]
    assert query(dataset, "SELECT MIN(value_num) AS low, MAX(value_num) AS high FROM attrs "
                 "WHERE key='vr' AND record_id NOT IN "
                 "(SELECT record_id FROM checks WHERE status='fail')") == [{"low": 3.0, "high": 10.0}]
    for file in dataset.rglob("*.json"):
        assert str(root) not in file.read_text()
