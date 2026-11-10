import json
import runpy
import sys

import numpy as np
import pytest

from runlog import __version__


def test_reduced_validation_report(tmp_path, monkeypatch, capsys):
    script = runpy.run_path("examples/validate_checks.py")
    monkeypatch.setattr(sys, "argv", ["validate_checks.py", "--trials", "2", "--samples", "2000", "--output", str(tmp_path)])
    script["main"]()
    report = json.loads((tmp_path / "check_characteristics.json").read_text())
    assert report == script["measure"](trials=2, samples=2000)
    assert report["schema_version"] == 1
    assert report["runlog_version"] == __version__
    assert report["protocol"]["trials"] == 2
    assert report["protocol"]["samples"] == 2000
    assert report["protocol"]["duration_s"] == 200
    assert len(report["spikes_false_alarms"]) == 5
    assert len(report["spikes_detection"]) == 16
    for key, count in [("spikes_false_alarms", "failed"), ("spikes_detection", "detected")]:
        assert all(r["trials"] == 2 and 0 <= r[count] <= 2 for r in report[key])
    assert len(report["derivative_pair"]) == 16
    for row in report["derivative_pair"]:
        assert row["rate_hz"] in (5, 10, 20, 100)
        assert np.isfinite(row["score"])
        expected = "fail" if row["case"] in ("velocity_scale_5%", "velocity_scale_10%") else "pass"
        assert row["status"] == expected
        assert "span" in row["message"]
    assert len(report["steady_limit_cycle"]) == 4
    assert len(report["steady_random_response"]) == 3
    for row in report["steady_limit_cycle"] + report["steady_random_response"]:
        assert row["status"] == "ok"
        assert 0 <= row["steady_time_s"] <= 200
        assert len(row["segment_rms_m"]) == row["segment_count"]
        assert (row["steady_rms_m"] is None) == (row["segment_count"] == 0)
    markdown = (tmp_path / "README.md").read_text()
    assert "Tagging records last 200 s" in markdown
    assert "Spike false alarms" in markdown
    assert "Steady random response" in markdown
    assert capsys.readouterr().out.strip() == markdown.strip()


@pytest.mark.parametrize("trials,samples", [(0, 2000), (1, 999)])
def test_invalid_validation_size(trials, samples):
    measure = runpy.run_path("examples/validate_checks.py")["measure"]
    with pytest.raises(ValueError, match="one trial and 1000 samples"):
        measure(trials, samples)
