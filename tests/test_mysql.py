import os
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text

from runlog.catalog import named_queries, query
from runlog.export import export_catalog

MYSQL_URL = os.environ.get("RUNLOG_TEST_MYSQL_URL")
pytestmark = pytest.mark.skipif(not MYSQL_URL, reason="RUNLOG_TEST_MYSQL_URL is not set")


def test_mysql_export_and_named_queries(demo_dataset):
    counts = export_catalog(demo_dataset, MYSQL_URL, replace=True)
    assert counts == {"records": 16, "attrs": 48, "channels": 64, "checks": 320, "segments": 81}
    engine = create_engine(MYSQL_URL, hide_parameters=True)
    try:
        with engine.connect() as connection:
            for sql in named_queries("examples/queries.sql").values():
                expected = query(demo_dataset, sql)
                actual = list(connection.execute(text(sql)).mappings())
                assert len(actual) == len(expected)
                for result, reference in zip(actual, expected):
                    assert result.keys() == reference.keys()
                    for key, value in reference.items():
                        if isinstance(value, (int, float, Decimal)):
                            assert float(result[key]) == pytest.approx(float(value), rel=1e-8, abs=1e-10)
                        else:
                            assert result[key] == value
    finally:
        engine.dispose()
