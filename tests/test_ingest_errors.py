import pytest

from runlog import load_record
from runlog.cli import main


@pytest.mark.parametrize("kind", ["csv", "out", "outb", "missing", "write"])
@pytest.mark.parametrize("written", [0, 1])
def test_ingest_error_names_file_and_completed_count(tmp_path, capsys, kind, written):
    good = tmp_path / "good.out"
    good.write_text("Time X\ns m\n0 1\n1 2\n")
    bad = tmp_path / f"bad.{kind}"
    if kind == "write":
        bad.write_text("time,x\n0,not_numeric\n")
    elif kind != "missing":
        bad.write_bytes(b"invalid")
    units = tmp_path / "units.json"
    units.write_text('{"x":"m"}')
    dataset = tmp_path / "dataset"
    inputs = ([str(good)] if written else []) + [str(bad)]
    assert main(["ingest", *inputs, "--dataset", str(dataset), "--units", str(units)]) == 2
    message = capsys.readouterr().err
    assert str(bad) in message
    assert f"records written before error: {written}" in message
    assert len(list((dataset / "records").glob("*.json"))) == written
    if written:
        assert load_record(dataset, "good")[1].n_samples == 2


@pytest.mark.parametrize("error", ["units", "duplicate", "json"])
def test_ingest_preflight_error_has_files_and_zero_writes(tmp_path, capsys, error):
    source = tmp_path / "bad.csv"
    source.write_text("time,x\n0,1\n")
    args = ["ingest", str(source), "--dataset", str(tmp_path / "dataset")]
    if error == "duplicate":
        args.insert(2, str(source))
    elif error == "json":
        units = tmp_path / "units.json"
        units.write_text("invalid")
        args += ["--units", str(units)]
    assert main(args) == 2
    message = capsys.readouterr().err
    assert str(source) in message
    assert "records written before error: 0" in message
