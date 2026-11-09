import numpy as np
import pandas as pd
import pytest

from runlog import load_record, read_csv, read_openfast_out, write_record


def test_csv_roundtrip(tmp_path):
    path = tmp_path / "input.csv"
    path.write_text("t,sway,label\n0,1,10\n0.2,2,20\n0.1,3,30\n4,4,40\n")
    frame = read_csv(path, time_column="t")
    assert frame.time.dtype == np.float64
    meta = write_record(frame, tmp_path / "dataset", "run", {"sway": "m", "label": "-"},
                        path, {"vr": 5})
    restored, restored_meta = load_record(tmp_path / "dataset", "run")
    pd.testing.assert_frame_equal(restored, frame)
    assert meta == restored_meta
    assert meta.source == "input.csv"
    sidecar = (tmp_path / "dataset/records/run.json").read_text()
    assert str(tmp_path) not in sidecar


def test_openfast_roundtrip(tmp_path):
    path = tmp_path / "synthetic.out"
    path.write_text("Synthetic test\nheader\n Time Sway Fx\n(s) (m) (N)\n0 1 2\n0.1 3 4\n\n")
    frame, units = read_openfast_out(path)
    assert list(frame) == ["time", "Sway", "Fx"]
    assert units == {"Sway": "m", "Fx": "N"}
    write_record(frame, tmp_path / "data", "run", units, path)
    restored, _ = load_record(tmp_path / "data", "run")
    pd.testing.assert_frame_equal(restored, frame)


@pytest.mark.parametrize("remaining", ["both", "json", "parquet"])
def test_overwrite(tmp_path, remaining):
    frame = pd.DataFrame({"time": [0, 1], "x": [1, 2]})
    write_record(frame, tmp_path, "r", {"x": "m"}, "r.csv")
    if remaining != "both":
        other = "json" if remaining == "parquet" else "parquet"
        (tmp_path / f"records/r.{other}").unlink()
    with pytest.raises(ValueError, match="already exists"):
        write_record(frame, tmp_path, "r", {"x": "m"}, "r.csv")
    write_record(frame, tmp_path, "r", {"x": "m"}, "C:\\logs\\r.csv", overwrite=True)
    assert load_record(tmp_path, "r")[1].source == "r.csv"


@pytest.mark.parametrize("content,time_column", [
    ("x\n1\n", "time"), ("time\nhello\n", "time"), ("t,time\n1,2\n", "t"),
])
def test_bad_csv(tmp_path, content, time_column):
    path = tmp_path / "bad.csv"
    path.write_text(content)
    with pytest.raises(ValueError):
        read_csv(path, time_column)


@pytest.mark.parametrize("content", [
    "no header", "Time X", "Time X\n(s)\n", "Time X X\n(s) (m) (m)\n",
    "Time X\ns m\n", "Time X\n(s) (m)\n0 bad\n", "Time X\n(s) (m)\n0 1 2\n",
])
def test_bad_openfast(tmp_path, content):
    path = tmp_path / "bad.out"
    path.write_text(content)
    with pytest.raises(ValueError):
        read_openfast_out(path)


def test_write_validation_before_output(tmp_path):
    frame = pd.DataFrame({"time": [0], "x": [1]})
    with pytest.raises(ValueError, match="missing unit"):
        write_record(frame, tmp_path, "r", {}, "r.csv")
    with pytest.raises(ValueError, match="record_id"):
        write_record(frame, tmp_path, "../r", {"x": "m"}, "r.csv")
    duplicate = pd.DataFrame([[0, 1, 2]], columns=["time", "x", "x"])
    with pytest.raises(ValueError, match="unique"):
        write_record(duplicate, tmp_path, "r", {"x": "m"}, "r.csv")
    assert not (tmp_path / "records").exists()


def test_channel_numeric_conversion(tmp_path):
    frame = pd.DataFrame({"time": [0, 1], "force": ["1.5", "bad"]})
    with pytest.raises(ValueError, match="force"):
        write_record(frame, tmp_path, "r", {"force": "N"}, "r.csv")
    frame.force = ["1.5", "2.5"]
    write_record(frame, tmp_path, "r", {"force": "N"}, "r.csv")
    assert load_record(tmp_path, "r")[0].force.tolist() == [1.5, 2.5]


def test_overwrite_removes_analysis(tmp_path):
    frame = pd.DataFrame({"time": [0, 1], "x": [1, 2]})
    write_record(frame, tmp_path, "r", {"x": "m"}, "r.csv")
    for folder in ("checks", "segments"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "r.json").write_text("[]")
    write_record(frame, tmp_path, "r", {"x": "m"}, "r.csv", overwrite=True)
    assert not (tmp_path / "checks/r.json").exists()
    assert not (tmp_path / "segments/r.json").exists()
