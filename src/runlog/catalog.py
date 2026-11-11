import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

import numpy as np

from .check_resolution import _sample_step
from .checks import sample_rate
from .ingest import load_record
from .manifest import read_analysis, verify_dataset

_SCHEMA = """
CREATE TABLE records(record_id TEXT PRIMARY KEY, n_samples INTEGER, duration_s REAL,
 sample_rate_hz REAL, sha256 TEXT, source TEXT);
CREATE TABLE channels(record_id TEXT REFERENCES records, name TEXT, unit TEXT,
 PRIMARY KEY(record_id, name));
CREATE TABLE attrs(record_id TEXT REFERENCES records, key TEXT, value_num REAL,
 value_text TEXT, PRIMARY KEY(record_id, key));
CREATE TABLE checks(record_id TEXT REFERENCES records, check_name TEXT, channel TEXT,
 status TEXT, value REAL, threshold REAL, message TEXT);
CREATE TABLE segments(segment_id INTEGER PRIMARY KEY, record_id TEXT REFERENCES records,
 channel TEXT, start_s REAL, end_s REAL, tag TEXT, method TEXT, method_version INTEGER,
 rms REAL, peak_freq_hz REAL);
CREATE INDEX checks_record_status ON checks(record_id, status);
CREATE INDEX segments_tag ON segments(tag);
CREATE INDEX attrs_key_num ON attrs(key, value_num);
"""


def _insert_record(connection: sqlite3.Connection, dataset: Path, record_id: str) -> None:
    frame, meta = load_record(dataset, record_id)
    time = frame["time"].to_numpy(dtype=float)
    valid = len(time) > 1 and np.isfinite(time).all() and np.all(np.diff(time) > 0)
    duration = float(time[-1] - time[0]) if valid else None
    valid_spacing = valid and (len(time) < 10 or sample_rate(time, record_id).status == "pass")
    rate = 1 / _sample_step(time) if valid_spacing else None
    connection.execute(
        "INSERT INTO records VALUES (?, ?, ?, ?, ?, ?)",
        (record_id, meta.n_samples, duration, rate, meta.sha256, meta.source),
    )
    connection.executemany(
        "INSERT INTO channels VALUES (?, ?, ?)",
        [(record_id, c.name, c.unit) for c in meta.channels],
    )
    connection.executemany(
        "INSERT INTO attrs VALUES (?, ?, ?, ?)",
        [
            (
                record_id,
                key,
                None if isinstance(value, str) else value,
                value if isinstance(value, str) else None,
            )
            for key, value in meta.attrs.items()
        ],
    )
    checks = dataset / "checks" / f"{record_id}.json"
    if checks.exists():
        for row in read_analysis(checks, meta.sha256)["checks"]:
            connection.execute(
                "INSERT INTO checks VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record_id,
                    row["check"],
                    row["channel"],
                    row["status"],
                    row["value"],
                    row["threshold"],
                    row["message"],
                ),
            )
    segments = dataset / "segments" / f"{record_id}.json"
    if segments.exists():
        for report in read_analysis(segments, meta.sha256)["channels"].values():
            for row in report["segments"]:
                connection.execute(
                    "INSERT INTO segments VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        record_id,
                        row["channel"],
                        row["start_s"],
                        row["end_s"],
                        row["tag"],
                        row["method"],
                        row["method_version"],
                        row["rms"],
                        row["peak_freq_hz"],
                    ),
                )


def build_catalog(dataset: str | Path) -> Path:
    """Rebuild the catalog in one transaction and replace the previous catalog."""
    dataset = Path(dataset)
    errors = verify_dataset(dataset)
    if errors:
        raise ValueError("; ".join(errors))
    with tempfile.NamedTemporaryFile(
        dir=dataset, prefix=".catalog-", suffix=".sqlite", delete=False
    ) as file:
        temporary = Path(file.name)
    try:
        with closing(sqlite3.connect(temporary)) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript("BEGIN;\n" + _SCHEMA)
            for sidecar in sorted((dataset / "records").glob("*.json")):
                if not sidecar.name.startswith("."):
                    _insert_record(connection, dataset, sidecar.stem)
            connection.commit()
        destination = dataset / "catalog.sqlite"
        temporary.replace(destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def query(dataset: str | Path, sql: str, params: tuple = ()) -> list[dict]:
    """Run SQL through a read-only connection and return rows by column name."""
    uri = (Path(dataset) / "catalog.sqlite").resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        allowed = {
            sqlite3.SQLITE_SELECT,
            sqlite3.SQLITE_READ,
            sqlite3.SQLITE_FUNCTION,
            sqlite3.SQLITE_RECURSIVE,
        }
        connection.set_authorizer(
            lambda action, *_: sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY
        )
        return [dict(row) for row in connection.execute(sql, params)]


def named_queries(path: str | Path) -> dict[str, str]:
    """Read SQL statements separated by named comment headers."""
    queries, lines, name = {}, [], None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("-- name:"):
            if name is not None:
                queries[name] = "\n".join(lines).strip()
            name, lines = line.removeprefix("-- name:").strip(), []
            if not name or name in queries:
                raise ValueError("query names must be non-empty and unique")
        elif name is not None:
            lines.append(line)
    if name is not None:
        queries[name] = "\n".join(lines).strip()
    if not queries or not all(queries.values()):
        raise ValueError("query file must contain non-empty named queries")
    return queries
