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
        raise ValueError("OpenFAST log must contain a Time header and units")
    names = lines[header].split()
    units = lines[header + 1].split()
    if len(names) != len(set(names)) or len(units) != len(names):
        raise ValueError("OpenFAST channel names and units must match")
    if any(not unit.startswith("(") or not unit.endswith(")") for unit in units):
        raise ValueError("OpenFAST units must be in parentheses")
    try:
        rows = [[float(value) for value in line.split()]
                for line in lines[header + 2:] if line.strip()]
        if any(len(row) != len(names) for row in rows):
            raise ValueError("row width does not match header")
        frame = pd.DataFrame(rows, columns=names, dtype=np.float64)
    except ValueError as exc:
        raise ValueError("invalid OpenFAST numeric rows") from exc
    return _normalize_time(frame, "Time"), dict(zip(names[1:], (unit[1:-1] for unit in units[1:])))


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
    if overwrite:
        for folder in ("checks", "segments"):
            (Path(dataset) / folder / f"{record_id}.json").unlink(missing_ok=True)
    return meta


def load_record(dataset: str | Path, record_id: str) -> tuple[pd.DataFrame, RecordMeta]:
    """Read a Parquet record and its validated JSON sidecar."""
    validate_record_id(record_id)
    records = Path(dataset) / "records"
    meta = RecordMeta.from_json(records / f"{record_id}.json")
    return pd.read_parquet(records / f"{record_id}.parquet"), meta
