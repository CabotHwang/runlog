import sqlite3
import traceback
from urllib.parse import quote
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.schema import CreateTable

from runlog.catalog import query
from runlog.export import _schema, export_catalog


def test_export_rows_schema_and_source_unchanged(demo_dataset, tmp_path):
    before = (demo_dataset / "catalog.sqlite").read_bytes()
    url = f"sqlite:///{tmp_path / 'target.sqlite'}"
    counts = export_catalog(demo_dataset, url)
    assert counts == {"records": 16, "attrs": 48, "channels": 64, "checks": 320, "segments": 78}
    engine = create_engine(url)
    with engine.connect() as connection:
        inspector = inspect(connection)
        for name, count in counts.items():
            rows = [
                dict(row) for row in connection.execute(text(f"SELECT * FROM {name}")).mappings()
            ]
            assert len(rows) == count
            for row in rows:
                row.pop("check_id", None)
            assert rows == query(demo_dataset, f"SELECT * FROM {name}")
            columns = {column["name"] for column in inspector.get_columns(name)}
            assert columns == set(rows[0]) | ({"check_id"} if name == "checks" else set())
            if name != "records":
                assert inspector.get_foreign_keys(name)[0]["referred_table"] == "records"
        assert inspector.get_pk_constraint("checks")["constrained_columns"] == ["check_id"]
        assert inspector.get_pk_constraint("channels")["constrained_columns"] == [
            "record_id",
            "name",
        ]
        assert inspector.get_indexes("segments")[0]["column_names"] == ["tag"]
        checks_index = inspector.get_indexes("checks")[0]
        assert checks_index["name"] == "checks_record_status"
        assert checks_index["column_names"] == ["record_id", "status"]
        assert inspector.get_indexes("attrs")[0]["column_names"] == ["key", "value_num"]
    engine.dispose()
    assert (demo_dataset / "catalog.sqlite").read_bytes() == before


def test_replace_and_partial_target(demo_dataset, tmp_path):
    url = f"sqlite:///{tmp_path / 'target.sqlite'}"
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE records (obsolete INTEGER)"))
        connection.execute(text("CREATE TABLE unrelated (keep INTEGER)"))
    with pytest.raises(ValueError, match="exist"):
        export_catalog(demo_dataset, url)
    counts = export_catalog(demo_dataset, url, replace=True)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM checks"))
    assert export_catalog(demo_dataset, url, replace=True) == counts
    assert "unrelated" in inspect(engine).get_table_names()
    engine.dispose()


def test_read_only_source_and_same_target(demo_dataset, tmp_path):
    with pytest.raises(RuntimeError):
        export_catalog(tmp_path, f"sqlite:///{tmp_path / 'target.sqlite'}")
    assert not (tmp_path / "catalog.sqlite").exists()
    before = (demo_dataset / "catalog.sqlite").read_bytes()
    with pytest.raises(ValueError, match="differ"):
        export_catalog(demo_dataset, f"sqlite:///{demo_dataset / 'catalog.sqlite'}", replace=True)
    assert (demo_dataset / "catalog.sqlite").read_bytes() == before


def test_batches_and_null_values(demo_dataset, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    with sqlite3.connect(demo_dataset / "catalog.sqlite") as original:
        with sqlite3.connect(source / "catalog.sqlite") as copied:
            original.backup(copied)
            copied.executemany(
                "INSERT INTO checks(record_id, check_name) VALUES (?, ?)",
                [("run_01", "extra")] * 1201,
            )
    url = f"sqlite:///{tmp_path / 'target.sqlite'}"
    assert export_catalog(source, url)["checks"] == 1521
    engine = create_engine(url)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM checks WHERE status IS NULL")) == 1201
    engine.dispose()


@pytest.mark.parametrize("failure", ["mismatch", "insert"])
def test_failed_copy_rolls_back(demo_dataset, tmp_path, monkeypatch, failure):
    import runlog.export as module

    url = f"sqlite:///{tmp_path / 'target.sqlite'}"
    engine = create_engine(url)
    _schema().create_all(engine)

    def alter(connection, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO checks"):
            if failure == "insert":
                raise SQLAlchemyError("injected failure")
            connection.exec_driver_sql("DELETE FROM records")

    event.listen(engine, "after_cursor_execute", alter)
    monkeypatch.setattr(module, "create_engine", lambda *args, **kwargs: engine)
    with pytest.raises(RuntimeError, match="export failed"):
        export_catalog(demo_dataset, url, replace=True)
    with engine.connect() as connection:
        for name in _schema().tables:
            assert connection.scalar(text(f"SELECT COUNT(*) FROM {name}")) == 0
    engine.dispose()


def test_password_masked_in_errors(demo_dataset, monkeypatch, caplog):
    import runlog.export as module

    secret = uuid4().hex + "/@:"
    url = f"mysql+pymysql://root:{quote(secret, safe='')}@localhost/runlog"

    def fail(*args, **kwargs):
        raise SQLAlchemyError(f"connection refused: {url} {secret}")

    monkeypatch.setattr(module, "create_engine", fail)
    with pytest.raises(RuntimeError) as error:
        export_catalog(demo_dataset, url)
    rendered = "".join(traceback.format_exception(error.value)) + caplog.text
    assert "***@localhost" in str(error.value)
    assert "SQLAlchemyError: connection refused:" in str(error.value)
    assert error.value.__suppress_context__
    assert secret not in rendered and quote(secret, safe="") not in rendered
    with pytest.raises(ValueError) as error:
        export_catalog(demo_dataset, secret)
    assert secret not in str(error.value)


def test_mysql_schema_compiles():
    metadata = _schema()
    expected = {
        "record_id": 64,
        "name": 128,
        "unit": 64,
        "key": 128,
        "channel": 128,
        "check_name": 128,
        "tag": 32,
        "status": 32,
        "sha256": 64,
        "source": 255,
        "method": 128,
    }
    for table in metadata.tables.values():
        ddl = str(CreateTable(table).compile(dialect=mysql.dialect()))
        for column in table.columns:
            if column.name in expected:
                assert column.type.length == expected[column.name]
        if table.name == "checks":
            assert "AUTO_INCREMENT" in ddl and "message TEXT" in ddl
        if table.name in {"records", "attrs", "checks", "segments"}:
            assert "DOUBLE" in ddl
