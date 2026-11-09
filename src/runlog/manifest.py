import hashlib
from pathlib import Path

from .schema import RecordMeta


def sha256_file(path: str | Path) -> str:
    """Compute the file hash in 1 MiB chunks."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
