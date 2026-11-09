import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import (Column, Double, ForeignKey, Index, Integer, MetaData,
                        String, Table, Text, create_engine, func, inspect, select)
from sqlalchemy.engine import Connection, Engine, make_url


class _TargetError(ValueError):
    pass


def _record_id(primary_key: bool = False) -> Column:
    return Column("record_id", String(64), ForeignKey("records.record_id"), primary_key=primary_key)


def _schema() -> MetaData:
    metadata = MetaData()
    Table("records", metadata, Column("record_id", String(64), primary_key=True),
          Column("n_samples", Integer), Column("duration_s", Double),
          Column("sample_rate_hz", Double), Column("sha256", String(64)), Column("source", String(255)))
    Table("channels", metadata, _record_id(True), Column("name", String(128), primary_key=True),
          Column("unit", String(64)))
    attrs = Table("attrs", metadata, _record_id(True),
                  Column("key", String(128), primary_key=True), Column("value_num", Double),
                  Column("value_text", Text))
    Table("checks", metadata, Column("check_id", Integer, primary_key=True, autoincrement=True),
          _record_id(), Column("check_name", String(128)), Column("channel", String(128)),
          Column("status", String(32)), Column("value", Double), Column("threshold", Double),
          Column("message", Text))
    segments = Table("segments", metadata, Column("segment_id", Integer, primary_key=True),
                     _record_id(), Column("channel", String(128)), Column("start_s", Double),
                     Column("end_s", Double), Column("tag", String(32)), Column("method", String(128)),
                     Column("method_version", Integer), Column("rms", Double), Column("peak_freq_hz", Double))
    Index("segments_tag", segments.c.tag)
    Index("attrs_key_num", attrs.c.key, attrs.c.value_num)
    return metadata


def _copy(source: sqlite3.Connection, target: Connection, metadata: MetaData) -> dict[str, int]:
    counts = {}
    for table in metadata.sorted_tables:
        counts[table.name] = source.execute(f"SELECT COUNT(*) FROM {table.name}").fetchone()[0]
        cursor = source.execute(f"SELECT * FROM {table.name}")
        while batch := cursor.fetchmany(500):
            target.execute(table.insert(), [dict(row) for row in batch])
    for table in metadata.sorted_tables:
        actual = target.scalar(select(func.count()).select_from(table))
        if actual != counts[table.name]:
            raise RuntimeError(f"Row count mismatch for {table.name}")
    return counts


def _export(dataset: str | Path, engine: Engine, replace: bool) -> dict[str, int]:
    source_path = (Path(dataset) / "catalog.sqlite").resolve()
    if engine.dialect.name == "sqlite" and engine.url.database:
        if Path(engine.url.database).resolve() == source_path:
            raise _TargetError("Target must differ from the source catalog")
    metadata = _schema()
    with closing(sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)) as source:
        source.row_factory = sqlite3.Row
        source.execute("BEGIN")
        with engine.begin() as target:
            existing = set(inspect(target).get_table_names()) & set(metadata.tables)
            if existing and not replace:
                raise _TargetError("Target catalog tables exist; use replace=True or --replace")
            if replace:
                metadata.drop_all(target)
            metadata.create_all(target)
            return _copy(source, target, metadata)


def export_catalog(dataset: str | Path, url: str, replace: bool = False) -> dict[str, int]:
    """Copy the local catalog to a SQL database and verify table row counts."""
    try:
        parsed = make_url(url)
        safe_url = parsed.set(query={}).render_as_string(hide_password=True)
    except Exception:
        raise ValueError("Invalid database URL (password hidden)") from None
    engine = None
    try:
        engine = create_engine(parsed, hide_parameters=True)
        return _export(dataset, engine, replace)
    except _TargetError as exc:
        raise ValueError(f"{exc}: {safe_url}") from None
    except Exception as exc:
        message = str(exc)
        if parsed.password:
            message = message.replace(quote(parsed.password, safe=""), "***")
            message = message.replace(parsed.password, "***")
        raise RuntimeError(f"Catalog export failed for {safe_url}: {type(exc).__name__}: {message}") from None
    finally:
        if engine is not None:
            engine.dispose()
