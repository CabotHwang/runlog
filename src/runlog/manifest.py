import hashlib
import json
from dataclasses import fields
from pathlib import Path

from .checks import CheckConfig, CheckResult
from .schema import RecordMeta
from .segments import Segment, SegmentConfig


def sha256_file(path: str | Path) -> str:
    """Compute the file hash in 1 MiB chunks."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_provenance(report: dict, config_type: type[CheckConfig] | type[SegmentConfig]) -> None:
    version = report["runlog_version"]
    if not isinstance(version, str) or not version.strip():
        raise ValueError("runlog_version must be a non-empty string")
    config = report["config"]
    if not isinstance(config, dict) or set(config) != {field.name for field in fields(config_type)}:
        raise ValueError("config must contain all configuration fields")
    config_type(**config)


def read_analysis(path: Path, record_sha256: str) -> dict:
    """Read an analysis sidecar and check its record hash and structure."""
    label = f"{path.parent.name}/{path.name}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
        if data.get("record_sha256") != record_sha256:
            raise ValueError("record hash mismatch")
        if path.parent.name == "checks":
            _validate_provenance(data, CheckConfig)
            if not isinstance(data["checks"], list):
                raise ValueError("checks must be a list")
            for row in data["checks"]:
                result = CheckResult(**row)
                if result.record_id != path.stem or result.status not in ("pass", "fail", "not_testable"):
                    raise ValueError("invalid check result")
        else:
            for channel, report in data["channels"].items():
                _validate_provenance(report, SegmentConfig)
                if report["status"] not in ("ok", "not_testable") or not isinstance(report["segments"], list):
                    raise ValueError("invalid channel report")
                for row in report["segments"]:
                    segment = Segment(**row)
                    if segment.record_id != path.stem or segment.channel != channel:
                        raise ValueError("segment identity mismatch")
        return data
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ValueError(f"invalid analysis sidecar: {label}: schema error: {exc}") from exc


def _verify_pair(sidecar: Path, parquet: Path) -> list[str]:
    errors = []
    if not sidecar.is_file():
        errors.append(f"missing file: records/{sidecar.name}")
    else:
        try:
            meta = RecordMeta.from_json(sidecar)
            if meta.record_id != sidecar.stem:
                errors.append(f"sidecar schema error: records/{sidecar.name}: record_id mismatch")
            if parquet.is_file() and sha256_file(parquet) != meta.sha256:
                errors.append(f"hash mismatch: records/{parquet.name}")
            for folder in ("checks", "segments"):
                report = sidecar.parent.parent / folder / sidecar.name
                if report.is_file():
                    try:
                        read_analysis(report, meta.sha256)
                    except ValueError as exc:
                        errors.append(str(exc))
        except ValueError as exc:
            errors.append(f"sidecar schema error: records/{sidecar.name}: {exc}")
    if not parquet.is_file():
        errors.append(f"missing file: records/{parquet.name}")
    return errors


def verify_dataset(dataset: str | Path) -> list[str]:
    """Report missing files, extra files, invalid sidecars and hash mismatches."""
    dataset = Path(dataset)
    records = dataset / "records"
    if not records.is_dir():
        return ["missing directory: records"]
    ids = {path.stem for path in records.iterdir() if not path.name.startswith(".") and path.suffix in (".json", ".parquet")}
    errors = []
    for record_id in sorted(ids):
        errors.extend(_verify_pair(records / f"{record_id}.json", records / f"{record_id}.parquet"))
    expected = {f"records/{record_id}{suffix}" for record_id in ids for suffix in (".json", ".parquet")}
    expected.update(f"{folder}/{record_id}.json" for folder in ("checks", "segments") for record_id in ids)
    expected.add("catalog.sqlite")
    for path in sorted(dataset.rglob("*")):
        relative = path.relative_to(dataset).as_posix()
        if any(part.startswith(".") for part in path.relative_to(dataset).parts):
            continue
        if path.is_file() and relative not in expected:
            errors.append(f"extra file: {relative}")
    return errors
