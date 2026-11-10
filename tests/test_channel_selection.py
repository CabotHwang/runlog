import json

import numpy as np
import pandas as pd
import pytest

from runlog import CheckConfig, run_checks, write_record
from runlog.cli import main


def frame():
    time = np.arange(400) / 10
    return pd.DataFrame({"time": time, "x": time, "constant": np.ones(len(time))})


def test_selected_channels_and_missing_names():
    results = run_checks(frame(), "r", CheckConfig(channels=("x", "missing")))
    assert len(results) == 12
    assert all(r.status == "pass" for r in results[:8])
    missing = results[8:]
    assert {r.check for r in missing} == {"non_finite", "flatline", "clipping", "spikes"}
    assert all(r.channel == "missing" and r.status == "not_testable" for r in missing)
    assert all(r.message == "channel is missing" and r.value is None for r in missing)


def test_empty_selection_keeps_time_checks():
    results = run_checks(frame(), "r", CheckConfig(channels=()))
    assert len(results) == 4
    assert all(r.channel is None for r in results)


def test_selection_excludes_derivative_pairs():
    config = CheckConfig(channels=("x",), derivative_pairs=(("x", "constant"),))
    assert all(r.check != "derivative_pair" for r in run_checks(frame(), "r", config))
    config = CheckConfig(channels=("x", "constant"), derivative_pairs=(("x", "constant"),))
    assert run_checks(frame(), "r", config)[-1].check == "derivative_pair"


@pytest.mark.parametrize("cli", [False, True])
def test_cli_channel_selection_and_override(tmp_path, cli):
    write_record(frame(), tmp_path, "r", {"x": "m", "constant": "-"}, "r.csv")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"channels": ["constant"] if cli else ["x"]}))
    args = ["check", "--dataset", str(tmp_path), "--config", str(config)]
    if cli:
        args += ["--channels", "x, missing"]
    assert main(args) == 0
    data = json.loads((tmp_path / "checks/r.json").read_text())
    assert data["config"]["channels"] == (["x", "missing"] if cli else ["x"])
    assert {r["channel"] for r in data["checks"]} == ({None, "x", "missing"} if cli else {None, "x"})


def test_config_channels_are_immutable():
    config = CheckConfig(channels=["x"])
    assert config.channels == ("x",)
