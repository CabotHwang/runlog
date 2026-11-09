import runpy
from pathlib import Path

import pytest

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
