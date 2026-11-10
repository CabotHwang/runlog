import numpy as np
import pandas as pd
import pytest

from runlog import load_record, read_openfast_outb
from runlog.cli import main


def binary_fixture(file_id, names=None, units=None):
    time = np.array([2.5, 2.75, 3.25] if file_id == 1 else [2.5, 2.75, 3.0])
    values = np.array([[-2.5, 10], [0.5, -4], [3.0, 2.5]])
    scale, offset = np.array([10, 20]), np.array([-5, 40])
    width = 20 if file_id == 4 else 10
    sway_name = "PlatformSway" if file_id == 4 else "Sway"
    names = names or ["Time", sway_name, "Fx"]
    units = units or ["(s)", "(m)", "(N)"]
    header = np.array([file_id], dtype="<i2").tobytes()
    if file_id == 4:
        header += np.array([width], dtype="<i2").tobytes()
    header += np.array([2, len(time)], dtype="<i4").tobytes()
    time_info = [100, -50] if file_id == 1 else [time[0], 0.25]
    header += np.array(time_info, dtype="<f8").tobytes()
    if file_id != 3:
        header += scale.astype("<f4").tobytes() + offset.astype("<f4").tobytes()
    description = b"Synthetic fixture"
    header += np.array([len(description)], dtype="<i4").tobytes() + description
    header += b"".join(label.encode("ascii").ljust(width) for label in names + units)
    if file_id == 1:
        header += (time * 100 - 50).astype("<i4").tobytes()
    packed = values.astype("<f8") if file_id == 3 else (values * scale + offset).astype("<i2")
    expected = pd.DataFrame({"time": time, sway_name: values[:, 0], "Fx": values[:, 1]})
    return header + packed.tobytes(), expected


@pytest.mark.parametrize("file_id", [1, 2, 3, 4])
def test_binary_roundtrip_and_cli(tmp_path, file_id):
    content, expected = binary_fixture(file_id)
    path = tmp_path / "test.OUTB"
    path.write_bytes(content)
    frame, units = read_openfast_outb(path)
    pd.testing.assert_frame_equal(frame, expected)
    assert units == {expected.columns[1]: "m", "Fx": "N"}
    dataset = tmp_path / "dataset"
    assert main(["ingest", str(path), "--dataset", str(dataset)]) == 0
    restored, meta = load_record(dataset, "test")
    pd.testing.assert_frame_equal(restored, expected)
    assert {c.name: c.unit for c in meta.channels} == units


@pytest.mark.parametrize("file_id", [1, 2, 3, 4])
def test_binary_truncation_at_every_byte(tmp_path, file_id):
    content, _ = binary_fixture(file_id)
    path = tmp_path / "truncated.outb"
    for length in range(len(content)):
        path.write_bytes(content[:length])
        with pytest.raises(ValueError, match="truncated OpenFAST binary file"):
            read_openfast_outb(path)


@pytest.mark.parametrize("file_id", [-1, 0, 5, 100])
def test_binary_unsupported_id(tmp_path, capsys, file_id):
    path = tmp_path / "bad.outb"
    path.write_bytes(np.array([file_id], dtype="<i2").tobytes())
    with pytest.raises(ValueError, match=f"unsupported OpenFAST binary FileID: {file_id}"):
        read_openfast_outb(path)
    assert main(["ingest", str(path), "--dataset", str(tmp_path / "data")]) == 2
    assert "FileID" in capsys.readouterr().err


@pytest.mark.parametrize("names,units", [
    (["Other", "Sway", "Fx"], None), (["Time", "Fx", "Fx"], None),
    (["Time", "time", "Fx"], None),
])
def test_binary_invalid_labels(tmp_path, names, units):
    content, _ = binary_fixture(2, names, units)
    path = tmp_path / "bad.outb"
    path.write_bytes(content)
    with pytest.raises(ValueError, match="invalid OpenFAST binary"):
        read_openfast_outb(path)


@pytest.mark.parametrize("file_id", [1, 2, 3, 4])
@pytest.mark.parametrize("units,expected", [
    (["s", "m", "N"], {"Sway": "m", "Fx": "N"}),
    (["(s)", "", "()"], {"Sway": "-", "Fx": "-"}),
    (["s", "(m)", "-"], {"Sway": "m", "Fx": "-"}),
])
def test_binary_units_accept_bare_wrapped_and_empty(tmp_path, file_id, units, expected):
    content, _ = binary_fixture(file_id, names=["Time", "Sway", "Fx"], units=units)
    path = tmp_path / "units.outb"
    path.write_bytes(content)
    assert read_openfast_outb(path)[1] == expected
    assert main(["ingest", str(path), "--dataset", str(tmp_path / "data")]) == 0
    assert {c.name: c.unit for c in load_record(tmp_path / "data", "units")[1].channels} == expected


@pytest.mark.parametrize("position,dtype,value,message", [
    (2, "<i4", -1, "counts"), (6, "<i4", 0, "counts"),
    (42, "<i4", -1, "negative length"), (10, "<f8", 0, "time scale"),
    (26, "<f4", 0, "channel scale"), (34, "<f4", np.inf, "channel scale"),
])
def test_binary_invalid_header(tmp_path, position, dtype, value, message):
    content, _ = binary_fixture(1)
    content = bytearray(content)
    replacement = np.array([value], dtype=dtype).tobytes()
    content[position:position + len(replacement)] = replacement
    path = tmp_path / "bad.outb"
    path.write_bytes(content)
    with pytest.raises(ValueError, match=message):
        read_openfast_outb(path)


def test_binary_nan_scale_and_offset_represent_constant(tmp_path):
    content, expected = binary_fixture(2)
    content = bytearray(content)
    for position in (26, 34):
        content[position:position + 4] = np.array([np.nan], dtype="<f4").tobytes()
    path = tmp_path / "constant.outb"
    path.write_bytes(content)
    frame, _ = read_openfast_outb(path)
    expected["Sway"] = 0.0
    pd.testing.assert_frame_equal(frame, expected)


def test_binary_invalid_extended_name_width(tmp_path):
    content, _ = binary_fixture(4)
    path = tmp_path / "bad.outb"
    path.write_bytes(content[:2] + b"\0\0" + content[4:])
    with pytest.raises(ValueError, match="channel width"):
        read_openfast_outb(path)


@pytest.mark.parametrize("file_id", [1, 2, 3])
def test_binary_truncated_declared_large_sample_count(tmp_path, file_id):
    content, _ = binary_fixture(file_id)
    path = tmp_path / "truncated.outb"
    path.write_bytes(content[:6] + np.array([2_000_000_000], dtype="<i4").tobytes() + content[10:])
    with pytest.raises(ValueError, match="truncated OpenFAST binary file"):
        read_openfast_outb(path)
