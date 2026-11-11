import json
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .checks import CheckConfig, CheckResult, run_checks
from .ingest import load_record
from .manifest import read_analysis
from .segments import SegmentConfig, SegmentReport, tag_segments


def _record_sidecars(dataset: Path) -> list[Path]:
    if not (dataset / "records").is_dir():
        raise ValueError("missing directory: records")
    return [
        path
        for path in sorted((dataset / "records").glob("*.json"))
        if not path.name.startswith(".")
    ]


def check_dataset(
    dataset: str | Path, config: CheckConfig = CheckConfig()
) -> dict[str, list[CheckResult]]:
    """Check every record and write its check sidecar."""
    dataset = Path(dataset)
    sidecars = _record_sidecars(dataset)
    folder = dataset / "checks"
    folder.mkdir(parents=True, exist_ok=True)
    reports = {}
    for sidecar in sidecars:
        frame, meta = load_record(dataset, sidecar.stem)
        results = run_checks(frame, meta.record_id, config)
        data = {
            "record_sha256": meta.sha256,
            "runlog_version": __version__,
            "config": asdict(config),
            "checks": [asdict(result) for result in results],
        }
        (folder / sidecar.name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        reports[meta.record_id] = results
    return reports


def tag_dataset(
    dataset: str | Path, channel: str, config: SegmentConfig
) -> dict[str, SegmentReport]:
    """Tag one channel in every record and keep other channel reports."""
    dataset = Path(dataset)
    sidecars = _record_sidecars(dataset)
    folder = dataset / "segments"
    folder.mkdir(parents=True, exist_ok=True)
    reports = {}
    for sidecar in sidecars:
        frame, meta = load_record(dataset, sidecar.stem)
        path = folder / sidecar.name
        data = (
            read_analysis(path, meta.sha256)
            if path.exists()
            else {"record_sha256": meta.sha256, "channels": {}}
        )
        report = SegmentReport("not_testable", ())
        if channel in frame and channel != "time":
            report = tag_segments(frame["time"], frame[channel], meta.record_id, channel, config)
        data["channels"][channel] = {
            **asdict(report),
            "runlog_version": __version__,
            "config": asdict(config),
        }
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        reports[meta.record_id] = report
    return reports
