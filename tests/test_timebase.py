import numpy as np
import pandas as pd
import pytest

from runlog import (
    CheckConfig,
    SegmentConfig,
    build_catalog,
    derivative_pair,
    query,
    sample_rate,
    tag_dataset,
    tag_segments,
    write_record,
)
from runlog.catalog import named_queries


def changing_clock():
    return np.r_[np.arange(3001) / 10, 300 + np.arange(1, 3000) / 5]


def test_sustained_rate_change_is_not_timestamp_rounding():
    result = sample_rate(changing_clock(), "r")
    assert result.status == "fail"


def test_changed_rate_cannot_be_tagged_or_integrated():
    time = changing_clock()
    omega = 2 * np.pi * 0.2
    position = np.sin(omega * time)
    report = tag_segments(time, position, "r", "x", SegmentConfig(0.005))
    assert report.status == "not_testable"
    assert not report.segments
    result = derivative_pair(time, position, omega * np.cos(omega * time), "r", "x")
    assert result.status == "not_testable"


def test_expected_rate_uses_the_full_rounded_clock():
    time = np.round(np.arange(2560) / 128, 3)
    assert sample_rate(time, "r", CheckConfig(expected_rate_hz=128)).status == "pass"


def test_rounded_clock_frequency_and_catalog_rate(tmp_path):
    time = np.round(np.arange(18000) / 30, 3)
    values = np.sin(2 * np.pi * 0.2 * time)
    report = tag_segments(time, values, "r", "x", SegmentConfig(0.005))
    assert report.status == "ok"
    steady = [segment for segment in report.segments if segment.tag == "steady"]
    assert len(steady) == 1
    assert steady[0].peak_freq_hz == pytest.approx(0.2, rel=0.001)
    write_record(pd.DataFrame({"time": time, "x": values}), tmp_path, "r", {"x": "m"}, "r.csv")
    build_catalog(tmp_path)
    rate = query(tmp_path, "SELECT sample_rate_hz FROM records")[0]["sample_rate_hz"]
    assert rate == pytest.approx(30, rel=0.001)


def test_changed_rate_has_no_single_catalog_rate(tmp_path):
    time = changing_clock()
    write_record(
        pd.DataFrame({"time": time, "x": np.sin(time)}), tmp_path, "r", {"x": "m"}, "r.csv"
    )
    build_catalog(tmp_path)
    assert query(tmp_path, "SELECT sample_rate_hz FROM records") == [{"sample_rate_hz": None}]


def test_exact_minimum_steady_duration_is_not_rounded_up_one_sample():
    from runlog.segments import _steady_intervals

    edges = np.arange(301) / 10
    intervals = _steady_intervals(np.ones(300), edges, SegmentConfig(0.005))
    assert intervals == [(0, 300)]


def test_full_record_steady_coverage_does_not_exceed_one(tmp_path):
    time = np.arange(600) / 10
    write_record(
        pd.DataFrame({"time": time, "x": np.sin(2 * np.pi * 0.2 * time)}),
        tmp_path,
        "r",
        {"x": "m"},
        "r.csv",
    )
    tag_dataset(tmp_path, "x", SegmentConfig(0.005))
    build_catalog(tmp_path)
    sql = named_queries("examples/queries.sql")["steady_coverage"]
    assert query(tmp_path, sql)[0]["steady_share"] == pytest.approx(1.0)
