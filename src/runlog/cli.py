import argparse
import csv
import json
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path

from .catalog import build_catalog, query
from .checks import CheckConfig, run_checks
from .ingest import load_record, read_csv, read_openfast_out, write_record
from .manifest import verify_dataset
from .segments import SegmentConfig, tag_segments


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="runlog", description="Check and tag time-series test logs.")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest")
    ingest.add_argument("files", nargs="+")
    ingest.add_argument("--time-column", default="time")
    ingest.add_argument("--units", required=True, type=Path)
    ingest.add_argument("--attrs", type=Path)
    ingest.add_argument("--overwrite", action="store_true")
    check = commands.add_parser("check")
    check.add_argument("--config", type=Path)
    tag = commands.add_parser("tag")
    tag.add_argument("--channel", required=True)
    tag.add_argument("--noise-floor", required=True, type=float)
    tag.add_argument("--config", type=Path)
    commands.add_parser("index")
    commands.add_parser("verify")
    sql = commands.add_parser("query")
    sql.add_argument("sql")
    sql.add_argument("--format", choices=("table", "csv", "json"), default="table")
    for command in commands.choices.values():
        command.add_argument("--dataset", required=True, type=Path)
    return parser


def _json(path: Path | None) -> dict:
    return json.loads(path.read_text()) if path else {}


def _ingest(args: argparse.Namespace) -> int:
    units, attrs = _json(args.units), _json(args.attrs)
    for name in args.files:
        path = Path(name)
        if path.suffix.lower() == ".out":
            frame, file_units = read_openfast_out(path)
        else:
            frame, file_units = read_csv(path, args.time_column), units
        write_record(frame, args.dataset, path.stem, file_units, path,
                     attrs.get(path.name, {}), args.overwrite)
    print(f"Ingested {len(args.files)} records.")
    return 0


def _analyze(args: argparse.Namespace) -> int:
    if not (args.dataset / "records").is_dir():
        raise ValueError("missing directory: records")
    options = _json(args.config)
    config = (CheckConfig(**options) if args.command == "check" else
              SegmentConfig(**(options | {"noise_floor": args.noise_floor})))
    folder = args.dataset / ("checks" if args.command == "check" else "segments")
    folder.mkdir(parents=True, exist_ok=True)
    failures, count = 0, 0
    for sidecar in sorted((args.dataset / "records").glob("*.json")):
        if sidecar.name.startswith("."):
            continue
        frame, meta = load_record(args.dataset, sidecar.stem)
        if args.command == "check":
            results = run_checks(frame, meta.record_id, config)
            failures += sum(result.status == "fail" for result in results)
            data = [asdict(result) for result in results]
        else:
            if args.channel not in frame or args.channel == "time":
                raise ValueError(f"missing channel: {args.channel}")
            data = asdict(tag_segments(frame.time, frame[args.channel], meta.record_id, args.channel, config))
        (folder / sidecar.name).write_text(json.dumps(data, indent=2) + "\n")
        count += 1
    if args.command == "check":
        print(f"Checked {count} records: {failures} failed checks.")
    else:
        print(f"Tagged {count} records.")
    return int(failures > 0)


def _print_rows(rows: list[dict], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(rows, indent=2))
    elif rows:
        names = list(rows[0])
        if output_format == "csv":
            writer = csv.DictWriter(sys.stdout, fieldnames=names, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        else:
            lines = [names] + [[str(row[name]) for name in names] for row in rows]
            widths = [max(len(row[i]) for row in lines) for i in range(len(names))]
            for row in lines:
                print("  ".join(value.ljust(width) for value, width in zip(row, widths)).rstrip())


def main(argv: list[str] | None = None) -> int:
    """Run a CLI command and return its exit code."""
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    try:
        if args.command == "ingest":
            return _ingest(args)
        if args.command in ("check", "tag"):
            return _analyze(args)
        if args.command == "index":
            build_catalog(args.dataset)
            print("Catalog rebuilt.")
        elif args.command == "verify":
            errors = verify_dataset(args.dataset)
            for error in errors:
                print(error)
            if errors:
                return 1
            print("Dataset verified.")
        else:
            _print_rows(query(args.dataset, args.sql), args.format)
        return 0
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error) as exc:
        print(f"runlog: {exc}", file=sys.stderr)
        return 2
