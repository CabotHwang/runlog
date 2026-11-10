from pathlib import Path

import numpy as np
import pandas as pd

from .manifest import sha256_file
from .schema import Channel, RecordMeta, validate_record_id


def _normalize_time(frame: pd.DataFrame, time_column: str) -> pd.DataFrame:
    if time_column not in frame:
        raise ValueError(f"missing time column: {time_column}")
    if time_column != "time" and "time" in frame:
        raise ValueError("time column name conflicts with an existing channel")
    try:
        time = pd.to_numeric(frame[time_column], errors="raise").astype("float64")
    except (TypeError, ValueError) as exc:
        raise ValueError("time column must be numeric") from exc
    result = frame.drop(columns=time_column).copy()
    result.insert(0, "time", time)
    return result


def read_csv(path: str | Path, time_column: str = "time") -> pd.DataFrame:
    """Read a CSV log and normalize its numeric time column."""
    return _normalize_time(pd.read_csv(path), time_column)


def read_openfast_out(path: str | Path) -> tuple[pd.DataFrame, dict[str, str]]:
    """Read a text OpenFAST log and its channel units."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    header = next((index for index, line in enumerate(lines)
                   if line.split() and line.split()[0] == "Time"), None)
    if header is None or header + 1 >= len(lines):
        raise ValueError("missing OpenFAST Time header or units")
    names = lines[header].split()
    units = lines[header + 1].split()
    if len(names) != len(set(names)) or len(units) != len(names):
        raise ValueError("invalid OpenFAST header: channel names must be unique and match the units row")
    if any(not unit.startswith("(") or not unit.endswith(")") for unit in units):
        raise ValueError("invalid OpenFAST units: expected parentheses")
    try:
        rows = [[float(value) for value in line.split()]
                for line in lines[header + 2:] if line.strip()]
        if any(len(row) != len(names) for row in rows):
            raise ValueError("row width does not match header")
        frame = pd.DataFrame(rows, columns=names, dtype=np.float64)
    except ValueError as exc:
        raise ValueError("invalid OpenFAST numeric rows") from exc
    return _normalize_time(frame, "Time"), dict(zip(names[1:], (unit[1:-1] for unit in units[1:])))


def _read_binary(stream, count: int, dtype: str) -> np.ndarray:
    dtype = np.dtype(dtype)
    if count < 0:
        raise ValueError("invalid OpenFAST binary header: negative length")
    offset = stream.tell()
    remaining = stream.seek(0, 2) - offset
    stream.seek(offset)
    if count * dtype.itemsize > remaining:
        raise ValueError("truncated OpenFAST binary file")
    return np.fromfile(stream, dtype=dtype, count=count)


def _binary_labels(stream, channels: int, width: int) -> tuple[list[str], dict[str, str]]:
    names = [value.decode("ascii").strip() for value in
             _read_binary(stream, channels + 1, f"S{width}")]
    units = [value.decode("ascii").strip() for value in
             _read_binary(stream, channels + 1, f"S{width}")]
    if names[0] != "Time" or len(names) != len(set(names)) or "time" in names:
        raise ValueError("invalid OpenFAST binary channel names")
    if any(not unit.startswith("(") or not unit.endswith(")") for unit in units):
        raise ValueError("invalid OpenFAST binary units: expected parentheses")
    return names, dict(zip(names[1:], (unit[1:-1] for unit in units[1:])))


def read_openfast_outb(path: str | Path) -> tuple[pd.DataFrame, dict[str, str]]:
    """Read OpenFAST binary FileIDs 1, 2, 3 and 4 with NumPy."""
    with Path(path).open("rb") as stream:
        file_id = int(_read_binary(stream, 1, "<i2")[0])
        if file_id not in (1, 2, 3, 4):
            raise ValueError(f"unsupported OpenFAST binary FileID: {file_id}; expected 1, 2, 3 or 4")
        width = int(_read_binary(stream, 1, "<i2")[0]) if file_id == 4 else 10
        if width < 1:
            raise ValueError("invalid OpenFAST binary channel width")
        channels, samples = map(int, _read_binary(stream, 2, "<i4"))
        if channels < 1 or samples < 1:
            raise ValueError("invalid OpenFAST binary header: counts must be positive")
        time_scale, time_offset = _read_binary(stream, 2, "<f8")
        scale = np.ones(channels) if file_id == 3 else _read_binary(stream, channels, "<f4")
        offset = np.zeros(channels) if file_id == 3 else _read_binary(stream, channels, "<f4")
        description_length = int(_read_binary(stream, 1, "<i4")[0])
        _read_binary(stream, description_length, "u1")
        names, units = _binary_labels(stream, channels, width)
        if file_id == 1:
            if not np.isfinite(time_scale) or time_scale == 0:
                raise ValueError("invalid OpenFAST binary time scale")
            time = (_read_binary(stream, samples, "<i4").astype(float) - time_offset) / time_scale
        dtype = "<f8" if file_id == 3 else "<i2"
        values = _read_binary(stream, samples * channels, dtype).reshape(samples, channels)
        if file_id != 1:
            time = time_scale + time_offset * np.arange(samples)
    constant = np.isnan(scale) & np.isnan(offset)
    if np.any((~np.isfinite(scale) | (scale == 0) | ~np.isfinite(offset)) & ~constant):
        raise ValueError("invalid OpenFAST binary channel scale or offset")
    values = (values.astype(float) - np.where(constant, 0, offset)) / np.where(constant, 1, scale)
    values[:, constant] = 0
    frame = pd.DataFrame(values, columns=names[1:])
    frame.insert(0, "time", time)
    return frame, units


def write_record(
    frame: pd.DataFrame, dataset: str | Path, record_id: str,
    units: dict[str, str], source: str | Path,
    attrs: dict[str, int | float | str | bool] | None = None,
    overwrite: bool = False,
) -> RecordMeta:
    """Write a Parquet record and its validated JSON sidecar."""
    validate_record_id(record_id)
    frame = _normalize_time(frame, "time")
    if not frame.columns.is_unique:
        raise ValueError("channel names must be unique")
    try:
        channels = tuple(Channel(name, units[name]) for name in frame.columns if name != "time")
    except KeyError as exc:
        raise ValueError(f"missing unit for channel: {exc.args[0]}") from exc
    for channel in frame.columns.drop("time"):
        try:
            frame[channel] = pd.to_numeric(frame[channel], errors="raise")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"channel must be numeric: {channel}") from exc
    source_name = str(source).replace("\\", "/").rsplit("/", 1)[-1]
    meta = RecordMeta(record_id, channels, dict(attrs or {}), source_name, len(frame), "0" * 64)
    records = Path(dataset) / "records"
    parquet, sidecar = records / f"{record_id}.parquet", records / f"{record_id}.json"
    if not overwrite and (parquet.exists() or sidecar.exists()):
        raise ValueError(f"record already exists: {record_id}")
    records.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(parquet, index=False)
    meta = RecordMeta(record_id, channels, meta.attrs, source_name, len(frame), sha256_file(parquet))
    meta.to_json(sidecar)
    for folder in ("checks", "segments"):
        (Path(dataset) / folder / f"{record_id}.json").unlink(missing_ok=True)
    return meta


def load_record(dataset: str | Path, record_id: str) -> tuple[pd.DataFrame, RecordMeta]:
    """Read a Parquet record and its validated JSON sidecar."""
    validate_record_id(record_id)
    records = Path(dataset) / "records"
    meta = RecordMeta.from_json(records / f"{record_id}.json")
    return pd.read_parquet(records / f"{record_id}.parquet"), meta
