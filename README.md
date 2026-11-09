# runlog

Convert time-series test logs into a checked, tagged, and searchable dataset.

[![CI](https://github.com/CabotHwang/runlog/actions/workflows/ci.yml/badge.svg)](https://github.com/CabotHwang/runlog/actions/workflows/ci.yml)

This library is part of my master's research on vortex-induced motion (VIM) of floating offshore wind turbines.

![Synthetic sway response with quality check results and segment tags](docs/figures/record_timeline.png)

## Install

Use Python 3.10 or later.
Create a virtual environment.
Install the library with the test and plot dependencies.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

## Quickstart

Run the example pipeline from the repository root.
The script creates 16 synthetic records with a fixed random seed.
Five records each contain one fault: a gap, a flatline, spikes, clipping, or NaNs.
The script accepts exit code 1 from the check command because these faults are present.

```bash
bash examples/quickstart.sh
.venv/bin/python examples/plot_record.py
```

The script ends with the catalog query shown below.
This output comes from a run of `bash examples/quickstart.sh` on 2026-11-09:

```text
Ingested 16 records.
Checked 16 records: 5 failed checks.
Tagged 16 records.
Dataset verified.
Catalog rebuilt.
record_id,vr,steady_rms_m
run_01,3.0,0.01641
run_02,3.467,0.0214
run_04,4.4,0.05486
run_05,4.867,0.08568
run_07,5.8,0.13896
run_08,6.267,0.13687
run_10,7.2,0.08114
run_11,7.667,0.0511
run_13,8.6,0.02042
run_14,9.067,0.01603
run_16,10.0,0.0142
```

## Dataset layout

```text
dataset/
  records/<record_id>.parquet
  records/<record_id>.json
  checks/<record_id>.json
  segments/<record_id>.json
  catalog.sqlite
```

Each Parquet file contains `time` in seconds and numeric channel columns.
Each record sidecar contains channel units, scalar attributes, sample count, source file name, schema version, and SHA-256 hash.
The source contains only the file name.
The check sidecar stores `record_sha256`, `runlog_version`, `config`, and a `checks` list.
The segment sidecar stores `record_sha256` and a `channels` object.
Each channel entry contains `status`, `segments`, `runlog_version`, and `config`.
Each `config` object stores all fields of the configuration used for that analysis.
Tagging updates only the selected channel.
A missing channel gives `not_testable` and an empty segment list.
Verification and catalog builds reject analysis sidecars with a different record hash or missing version or configuration fields.
The catalog is a derived index.
Rebuild it after changes to records or sidecars.

Record identifiers start with a letter or digit.
They contain 1–64 letters, digits, underscores, dots, or hyphens.
Channel names are unique.
Each channel has a non-empty unit.
Attribute values are numbers, strings, or booleans.

Ingest accepts CSV and text OpenFAST `.out` files.
Use `--units` with a JSON mapping from channel names to units for CSV inputs.
OpenFAST inputs use units from the file header.
Use `--time-column` to select the CSV time column.
Use `--attrs` with a JSON mapping from file names to attribute dictionaries.
Use `--overwrite` to replace an existing record.
Each record write removes its previous check and segment sidecars.

The verify command reports missing files, extra files, hash errors, and invalid sidecars.
It ignores hidden files.

## Checks

Each result has status `pass`, `fail`, or `not_testable`.
The default rules follow.

| Check | Rule |
|---|---|
| `time_monotonic` | Timestamps are finite. Each time step is positive. |
| `sample_rate` | Exclude gaps. Step error is at most the larger of 1% of the median step and repeated timestamp resolution. Check the expected rate if set. |
| `gaps` | No step exceeds three times the median step. |
| `duration` | Record duration is at least 10 s. |
| `non_finite` | Each channel has no NaN or infinite values. |
| `flatline` | Each run of identical values lasts at most 2 s. |
| `clipping` | Runs at channel limits contain at most 1% of samples. Each counted run has at least three samples. |
| `spikes` | No spike score exceeds 8. Use a centered 101-sample window and a global scale floor. |
| `derivative_pair` | Normalized RMS error between position gradient and velocity is at most 0.05. Pairs require configuration. |

The Hampel residual is the value minus its rolling median.
The scale is 1.4826 times the larger of the local median absolute deviation (MAD) and the global residual MAD.
The local MAD uses the same window.
The scale is at least 1.4826 times the smallest nonzero absolute channel step that occurs in at least `resolution_min_fraction` of all channel steps (5% by default).
This step estimates the channel quantum.
An entirely zero scale and residual gives `not_testable`.
Use an odd `spike_window` of at least three samples.
Timestamp resolution is the smallest nonzero absolute deviation from the median step that occurs in at least 5% of regular steps.
Exclude gaps and roundoff.
Set `resolution_min_fraction` to change this fraction.
Set `expected_rate_hz` to require `abs(median_step * expected_rate_hz - 1) <= sample_rate_rel_tol`.
This rate limit does not increase with timestamp resolution.
The result message gives the expected and measured rates.

Checks return `not_testable` when required data are insufficient or invalid.
Examples include fewer than 10 samples, constant channels for clipping, and invalid time for checks that require increasing time.
Time monotonicity requires at least two samples.
Duration requires at least two finite, increasing timestamps.
Zero or one sample fails duration.
Non-finite values prevent other channel checks.

Use `check --config checks.json` to set `CheckConfig` fields.
Use `tag --config segments.json` to set segment fields.
The CLI `--noise-floor` value sets the segment noise floor.

| Exit code | Meaning |
|---|---|
| 0 | Command completes without reported failures. |
| 1 | The check command finds failed checks, or verification finds errors. |
| 2 | A usage or data error occurs. |

## Segment tags

The envelope is a rolling RMS after subtraction of the channel median.
The default RMS window is 10 s.
Set a positive noise floor in channel units.
Intervals include their start and exclude their end.

| Tag | Rule |
|---|---|
| `quiet` | The envelope is below the noise floor. |
| `steady` | Flat windows form the interval. Each window lasts at least 30 s. |
| `buildup` | Before steady, the envelope rises from below 30% to at least 90% of the steady level. |
| `decay` | After steady, the envelope follows the reverse buildup rule. |

A flat window has a range at most twice `rel_tol` times its median.
Its median is at least the noise floor.
The default `rel_tol` is 0.05.
The steady level is the median envelope inside the merged interval.
Slow transitions can satisfy the flatness rule and extend the steady interval.
Buildup and decay permit dips up to 5% of the steady level.
Other intervals have no tag.

Each segment stores its record, channel, boundaries, tag, RMS, peak frequency, method, and method version.
The method is `rolling_rms`, version 1.
Peak frequency uses a Hann-window FFT.
Constant segments and segments shorter than the RMS window have no peak frequency.
Records shorter than twice that window give `not_testable`.

## Catalog

The index command rebuilds the SQLite catalog in one transaction.
An atomic file replacement installs the completed catalog.
Foreign keys link each child table to `records`.
Indexes cover `segments(tag)`, `attrs(key, value_num)`, and `checks(record_id, status)`.

| Table | Columns |
|---|---|
| `records` | `record_id`, `n_samples`, `duration_s`, `sample_rate_hz`, `sha256`, `source` |
| `channels` | `record_id`, `name`, `unit` |
| `attrs` | `record_id`, `key`, `value_num`, `value_text` |
| `checks` | `record_id`, `check_name`, `channel`, `status`, `value`, `threshold`, `message` |
| `segments` | `segment_id`, `record_id`, `channel`, `start_s`, `end_s`, `tag`, `method`, `method_version`, `rms`, `peak_freq_hz` |

Numeric attributes use `value_num`.
String attributes use `value_text`.
The query command opens the catalog in read-only mode.
An SQLite authorizer blocks writes and database attachment.
Select table, CSV, or JSON output with `--format`.

Use this query to list steady RMS against reduced velocity for records with no failed checks:

```bash
.venv/bin/python -m runlog query --dataset examples/output/dataset \
  "SELECT s.record_id, ROUND(a.value_num, 3) AS vr, ROUND(s.rms, 5) AS steady_rms_m FROM segments s JOIN attrs a ON a.record_id = s.record_id AND a.key = 'vr' WHERE s.tag = 'steady' AND NOT EXISTS (SELECT 1 FROM checks c WHERE c.record_id = s.record_id AND c.status = 'fail') ORDER BY a.value_num" \
  --format csv
```

## SQL

SQLite is the default catalog. It stores a local file and needs no server.
Export the catalog when users need a shared database.
The export uses SQLAlchemy Core and supports MySQL 8.
Install the `mysql` extra to use export.

Set the database URL in the environment. Keep credentials outside code and SQL files.

```bash
export RUNLOG_DB_URL='mysql+pymysql://runlog@db.example/runlog'
.venv/bin/python -m runlog export --dataset examples/output/dataset
```

Export prints the row count for each table.
Use `--replace` to drop and recreate existing catalog tables.
MySQL commits table changes before it inserts rows. All inserts use one transaction.

The six named queries in `examples/queries.sql` support SQLite 3.35 or later and MySQL 8.
Run a named query on the local catalog:

```bash
.venv/bin/python -m runlog query --dataset examples/output/dataset \
  --file examples/queries.sql --name check_failure_rates --format csv
```

This query counts failed results and calculates their share of all check results:

```sql
SELECT check_name,
       SUM(CASE WHEN status = 'fail' THEN 1 ELSE 0 END) AS failure_count,
       1e0 * SUM(CASE WHEN status = 'fail' THEN 1 ELSE 0 END) / COUNT(*) AS failure_rate
FROM checks
GROUP BY check_name
ORDER BY check_name;
```

The demo returns this output:

```text
check_name,failure_count,failure_rate
clipping,1,0.015625
duration,0,0.0
flatline,1,0.015625
gaps,1,0.0625
non_finite,1,0.015625
sample_rate,0,0.0
spikes,1,0.015625
time_monotonic,0,0.0
```

CI runs all named queries on MySQL 8.4 and compares their results with SQLite.

## Python API

```python
from runlog import CheckConfig, SegmentConfig, load_record, run_checks, tag_segments

frame, meta = load_record("examples/output/dataset", "run_01")
checks = run_checks(frame, meta.record_id, CheckConfig())
report = tag_segments(
    frame.time, frame.sway, meta.record_id, "sway", SegmentConfig(noise_floor=0.005)
)
```

## Limits

The library does not read binary OpenFAST `.outb` files.
Ingest preserves time errors for later checks.
Segment tagging assumes uniform sample spacing and uses the median time step.
Check the time results before you use segment tags.
A passed check does not establish physical validity.
A stopped vehicle or another signal with a constant level can fail the flatline and clipping checks with the default thresholds.
Set thresholds for each data type with `--config`.
In a record with mostly strong oscillation, the global spike scale floor makes spike detection less sensitive in quiet parts.
Rounded or simulated data with repeated extrema can fail the clipping check.
A slow ramp between plateaus can extend a steady interval and bias its RMS.
The demo uses synthetic data.

## License

See [LICENSE](LICENSE) for the MIT license.
