import sqlite3
import pytest

from runlog.catalog import _SCHEMA, named_queries, query

QUERIES = named_queries("examples/queries.sql")
CLEAN = [1, 2, 4, 5, 7, 8, 10, 11, 13, 14, 16]
RMS = [
    0.01642,
    0.02147,
    0.05486,
    0.08587,
    0.13897,
    0.13688,
    0.08088,
    0.05109,
    0.02044,
    0.01603,
    0.01425,
]
STARTS = [65.2, 65.8, 66.3, 66.1, 65.8, 66.4, 66.4, 65.7,
          195.1, 65.7, 65.9, 60.4, 66.0, 65.5, 66.1, 66.3]
ENDS = [234.5, 234.0, 236.1, 234.0, 233.8, 234.4, 234.3, 234.5,
        234.2, 234.6, 234.0, 239.7, 234.1, 234.6, 234.1, 234.3]


def test_named_queries_demo(demo_dataset):
    assert list(QUERIES) == [
        "steady_rms_vs_vr",
        "check_failure_rates",
        "longest_steady_segment",
        "clean_rms_rank",
        "steady_coverage",
        "segment_tag_shares",
    ]
    rows = query(demo_dataset, QUERIES["steady_rms_vs_vr"])
    assert rows == [
        {
            "record_id": f"run_{i:02d}",
            "vr": round(3 + (i - 1) * 7 / 15, 3),
            "steady_rms_m": rms,
        }
        for i, rms in zip(CLEAN, RMS)
    ]


def test_demo_failure_rates(demo_dataset):
    rows = query(demo_dataset, QUERIES["check_failure_rates"])
    failures = {
        "clipping": (1, 64),
        "flatline": (1, 64),
        "gaps": (1, 16),
        "non_finite": (1, 64),
        "spikes": (3, 64),
    }
    assert rows == [
        {
            "check_name": name,
            "failure_count": failures.get(name, (0, 1))[0],
            "failure_rate": failures[name][0] / failures[name][1] if name in failures else 0.0,
        }
        for name in [
            "clipping",
            "duration",
            "flatline",
            "gaps",
            "non_finite",
            "sample_rate",
            "spikes",
            "time_monotonic",
        ]
    ]


def test_demo_longest_and_rank(demo_dataset):
    rows = query(demo_dataset, QUERIES["longest_steady_segment"])
    assert len(rows) == 15
    assert "run_03" not in {row["record_id"] for row in rows}
    for row in rows:
        i = int(row["record_id"][-2:]) - 1
        assert row["record_id"] == f"run_{i + 1:02d}" and row["channel"] == "sway"
        assert row["start_s"] == pytest.approx(STARTS[i])
        assert row["end_s"] == pytest.approx(ENDS[i])
        assert row["duration_s"] == pytest.approx(ENDS[i] - STARTS[i])
    rows = query(demo_dataset, QUERIES["clean_rms_rank"])
    order = sorted(zip(CLEAN, RMS), key=lambda item: -item[1])
    assert len(rows) == len(order)
    for rank, (row, (i, rms)) in enumerate(zip(rows, order), 1):
        assert row["record_id"] == f"run_{i:02d}" and row["channel"] == "sway"
        assert row["rms_rank"] == rank and row["rms"] == pytest.approx(
            rms, abs=0.000005
        )


def test_demo_coverage_and_shares(demo_dataset):
    rows = query(demo_dataset, QUERIES["steady_coverage"])
    assert [r["record_id"] for r in rows] == [
        f"run_{i:02d}" for i in range(1, 17) if i not in (3, 9)
    ]
    for row in rows:
        i = int(row["record_id"][-2:]) - 1
        duration = 299.9
        assert row["channel"] == "sway"
        assert row["steady_s"] == pytest.approx(ENDS[i] - STARTS[i])
        assert row["steady_share"] == pytest.approx((ENDS[i] - STARTS[i]) / duration)
    rows = query(demo_dataset, QUERIES["segment_tag_shares"])
    totals = {"buildup": 382.1, "decay": 381.7, "quiet": 1000.8, "steady": 2445.4}
    assert [row["tag"] for row in rows] == list(totals)
    for row in rows:
        assert row["channel"] == "sway" and row["total_s"] == pytest.approx(
            totals[row["tag"]]
        )
        assert row["time_share"] == pytest.approx(
            totals[row["tag"]] / sum(totals.values())
        )


def test_windows_coverage_boundary_and_channel_shares(tmp_path):
    with sqlite3.connect(tmp_path / "catalog.sqlite") as connection:
        connection.executescript(_SCHEMA)
        connection.executemany(
            "INSERT INTO records(record_id, duration_s) VALUES (?, ?)",
            [("a", 10), ("b", 10), ("c", 10), ("d", 0)],
        )
        connection.executemany(
            "INSERT INTO segments(record_id, channel, start_s, end_s, tag, rms) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("a", "x", 0, 2.5, "steady", 2),
                ("a", "x", 2.5, 5, "steady", 2),
                ("a", "x", 5, 10, "quiet", 0),
                ("b", "x", 0, 4, "steady", 1),
                ("c", "x", 0, 4, "steady", 3),
                ("c", "y", 0, 4, "steady", 3),
                ("d", "x", 0, 1, "steady", 0),
            ],
        )
        connection.execute("INSERT INTO checks(record_id, status) VALUES ('c', 'fail')")
    rows = query(tmp_path, QUERIES["longest_steady_segment"])
    assert len(rows) == 4 and rows[0]["start_s"] == 0 and rows[0]["end_s"] == 2.5
    rows = query(tmp_path, QUERIES["clean_rms_rank"])
    assert [(r["record_id"], r["rms_rank"]) for r in rows] == [
        ("a", 1),
        ("a", 1),
        ("b", 3),
        ("d", 4),
    ]
    assert query(tmp_path, QUERIES["steady_coverage"]) == [
        {"record_id": "a", "channel": "x", "steady_s": 5.0, "steady_share": 0.5}
    ]
    rows = query(tmp_path, QUERIES["segment_tag_shares"])
    assert [(r["channel"], r["tag"]) for r in rows] == [
        ("x", "quiet"),
        ("x", "steady"),
        ("y", "steady"),
    ]
    assert [r["time_share"] for r in rows] == pytest.approx([5 / 19, 14 / 19, 1])


@pytest.mark.parametrize(
    "content",
    [
        "SELECT 1;",
        "-- name: \nSELECT 1;",
        "-- name: a\n",
        "-- name: a\nSELECT 1;\n-- name: a\nSELECT 2;",
    ],
)
def test_invalid_named_queries(tmp_path, content):
    path = tmp_path / "queries.sql"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        named_queries(path)


def test_named_query_comments_and_utf8(tmp_path):
    path = tmp_path / "queries.sql"
    path.write_text(
        "-- Notes\n-- name: first\nSELECT '海';\n-- name: second\nSELECT 2;\n",
        encoding="utf-8",
    )
    assert named_queries(path) == {"first": "SELECT '海';", "second": "SELECT 2;"}
