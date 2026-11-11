import argparse
import csv
import json
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from pyarrow import ArrowException

from .catalog import build_catalog, named_queries, query
from .checks import CheckConfig
from .ingest import read_csv, read_openfast_out, read_openfast_outb, write_record
from .manifest import verify_dataset
from .pipeline import check_dataset, tag_dataset
from .segments import SegmentConfig


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="runlog", description="Check and tag time-series test logs."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser(
        "ingest", help="Read CSV or OpenFAST .out/.outb files into the dataset."
    )
    ingest.add_argument("files", nargs="+", help="CSV or OpenFAST .out/.outb files to read.")
    ingest.add_argument(
        "--time-column", default="time", help="CSV time column name (default: time)."
    )
    ingest.add_argument(
        "--units", type=Path, help="JSON file that maps CSV channel names to units."
    )
    ingest.add_argument(
        "--attrs",
        type=Path,
        help="JSON file that maps record ids or input file names to attributes.",
    )
    ingest.add_argument(
        "--id-from",
        choices=("stem", "parent"),
        default="stem",
        help="Record id source (default: stem).",
    )
    ingest.add_argument("--overwrite", action="store_true", help="Replace existing records.")
    check = commands.add_parser("check", help="Check record quality.")
    check.add_argument("--config", type=Path, help="JSON file with CheckConfig fields.")
    check.add_argument(
        "--channels", help="Comma-separated channel names; overrides the config file."
    )
    tag = commands.add_parser("tag", help="Tag signal intervals.")
    tag.add_argument("--channel", required=True, help="Channel to tag.")
    tag.add_argument(
        "--noise-floor",
        required=True,
        type=float,
        help="Positive noise floor in channel units; overrides the config file.",
    )
    tag.add_argument("--config", type=Path, help="JSON file with SegmentConfig fields.")
    commands.add_parser("index", help="Rebuild the local catalog.")
    commands.add_parser("verify", help="Check dataset files and sidecars.")
    export = commands.add_parser("export", help="Copy the catalog to a SQL database.")
    export.add_argument("--url", help="Target database URL (default: RUNLOG_DB_URL).")
    export.add_argument(
        "--replace", action="store_true", help="Drop and recreate existing catalog tables."
    )
    sql = commands.add_parser("query", help="Read rows from the local catalog.")
    sql.add_argument("sql", nargs="?", help="SQL query to run.")
    sql.add_argument("--file", type=Path, help="SQL file with named queries.")
    sql.add_argument("--name", help="Query name from the SQL file.")
    sql.add_argument(
        "--format",
        choices=("table", "csv", "json"),
        default="table",
        help="Output format (default: table).",
    )
    for command in commands.choices.values():
        command.add_argument("--dataset", required=True, type=Path, help="Dataset directory.")
    return parser


def _json(path: Path | None) -> dict:
    data = json.loads(path.read_text(encoding="utf-8")) if path else {}
    if not isinstance(data, dict):
        raise ValueError("invalid JSON input: expected an object")
    return data


def _query_sql(args: argparse.Namespace) -> str:
    if args.sql is not None and args.file is None and args.name is None:
        return args.sql
    if args.sql is not None or args.file is None or args.name is None:
        raise ValueError("use inline SQL or both --file and --name")
    queries = named_queries(args.file)
    if args.name not in queries:
        raise ValueError("query name not found")
    return queries[args.name]


def _export_catalog(args: argparse.Namespace) -> None:
    url = args.url or os.environ.get("RUNLOG_DB_URL")
    if not url:
        raise ValueError("set --url or RUNLOG_DB_URL")
    try:
        from .export import export_catalog
    except ImportError:
        raise ValueError("install runlog with the mysql extra to export") from None
    _print_rows([export_catalog(args.dataset, url, args.replace)], "table")


def _ingest_inputs(args: argparse.Namespace) -> tuple[list[str], dict, dict]:
    ids = [
        Path(name).resolve().parent.name if args.id_from == "parent" else Path(name).stem
        for name in args.files
    ]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate record ids in input files")
    if args.units is None and any(
        Path(name).suffix.lower() not in (".out", ".outb") for name in args.files
    ):
        raise ValueError("--units is required for CSV inputs")
    units, attrs = _json(args.units), _json(args.attrs)
    return ids, units, attrs


def _ingest(args: argparse.Namespace) -> int:
    written, name = 0, ", ".join(args.files)
    try:
        ids, units, attrs = _ingest_inputs(args)
        for name, record_id in zip(args.files, ids, strict=True):
            path = Path(name)
            readers = {".out": read_openfast_out, ".outb": read_openfast_outb}
            if path.suffix.lower() in readers:
                frame, file_units = readers[path.suffix.lower()](path)
            else:
                frame, file_units = read_csv(path, args.time_column), units
            write_record(
                frame,
                args.dataset,
                record_id,
                file_units,
                path,
                attrs.get(record_id, attrs.get(path.name, {})),
                args.overwrite,
            )
            written += 1
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        OverflowError,
        RuntimeError,
        ArrowException,
    ) as exc:
        raise ValueError(f"{name}: {exc}; records written before error: {written}") from exc
    print(f"Records ingested: {len(args.files)}.")
    return 0


def _analyze(args: argparse.Namespace) -> int:
    if not (args.dataset / "records").is_dir():
        raise ValueError("missing directory: records")
    options = _json(args.config)
    if args.command == "check":
        if args.channels is not None:
            options["channels"] = tuple(name.strip() for name in args.channels.split(","))
        reports = check_dataset(args.dataset, CheckConfig(**options))
        counts = Counter(result.status for results in reports.values() for result in results)
        print(
            f"Records checked: {len(reports)}. Checks: {counts['pass']} pass, "
            f"{counts['fail']} fail, {counts['not_testable']} not testable."
        )
        return int(counts["fail"] > 0)
    config = SegmentConfig(**(options | {"noise_floor": args.noise_floor}))
    reports = tag_dataset(args.dataset, args.channel, config)
    taggable = sum(report.status == "ok" for report in reports.values())
    print(
        f"Records processed: {len(reports)}. Taggable: {taggable}. "
        f"Not testable: {len(reports) - taggable}."
    )
    print(f"Segments written: {sum(len(report.segments) for report in reports.values())}.")
    return 0


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
                print(
                    "  ".join(
                        value.ljust(width) for value, width in zip(row, widths, strict=True)
                    ).rstrip()
                )


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
        elif args.command == "export":
            _export_catalog(args)
        else:
            _print_rows(query(args.dataset, _query_sql(args)), args.format)
        return 0
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        OverflowError,
        RuntimeError,
        ArrowException,
        sqlite3.Error,
    ) as exc:
        print(f"runlog: {exc}", file=sys.stderr)
        return 2
