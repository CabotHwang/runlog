import runpy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from runlog import write_record

from runlog.cli import main


@pytest.fixture(scope="session")
def demo_dataset(tmp_path_factory):
    root = tmp_path_factory.mktemp("demo")
    raw, dataset = root / "raw", root / "dataset"
    make_demo = runpy.run_path(str(Path("examples/make_demo_data.py")))["make_demo_data"]
    make_demo(raw)
    base = ["--dataset", str(dataset)]
    assert main(["ingest", *map(str, sorted(raw.glob("run_*.csv"))), *base,
                 "--units", str(raw / "units.json"), "--attrs", str(raw / "attrs.json")]) == 0
    assert main(["check", *base]) == 1
    assert main(["tag", *base, "--channel", "sway", "--noise-floor", "0.005"]) == 0
    assert main(["index", *base]) == 0
    return dataset


@pytest.fixture
def make_test_record():
    def record(path, time=None, channel="x"):
        time = np.arange(0, 60, 0.1) if time is None else np.asarray(time)
        return write_record(
            pd.DataFrame({"time": time, channel: np.sin(np.arange(len(time)) * 0.1)}),
            path, "r", {channel: "m"}, "r.csv",
        )

    return record
