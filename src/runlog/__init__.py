__version__ = "0.2.3"

from .catalog import build_catalog, query
from .checks import (
    CheckConfig,
    CheckResult,
    clipping,
    derivative_pair,
    duration,
    flatline,
    gaps,
    non_finite,
    run_checks,
    sample_rate,
    spikes,
    time_monotonic,
)
from .ingest import load_record, read_csv, read_openfast_out, read_openfast_outb, write_record
from .manifest import sha256_file, verify_dataset
from .pipeline import check_dataset, tag_dataset
from .schema import SCHEMA_VERSION, Channel, RecordMeta
from .segments import Segment, SegmentConfig, SegmentReport, tag_segments

__all__ = [
    "build_catalog", "query", "__version__", "SCHEMA_VERSION", "Channel", "RecordMeta", "CheckConfig", "CheckResult",
    "Segment", "SegmentConfig", "SegmentReport", "read_csv", "read_openfast_out", "read_openfast_outb",
    "write_record", "load_record", "sha256_file", "verify_dataset", "run_checks",
    "time_monotonic", "sample_rate", "gaps", "duration", "non_finite", "flatline",
    "clipping", "spikes", "derivative_pair", "tag_segments", "check_dataset", "tag_dataset",
]
