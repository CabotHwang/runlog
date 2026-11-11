# Reference

See the [README](../README.md) for installation instructions.
See the [controlled example](oscillator_example.md) for a complete data procedure.

## Dataset layout

```text
dataset/
  records/<record_id>.parquet
  records/<record_id>.json
  checks/<record_id>.json
  segments/<record_id>.json
  catalog.sqlite
```

Each Parquet file contains time in seconds and numeric channels.
A sidecar is a JSON file that accompanies a record.
The sidecars contain this information:

| Sidecar | Contents |
|---|---|
| Record | Units, scalar attributes, sample count, source basename, schema version, and SHA-256 |
| Checks | `record_sha256`, `runlog_version`, `config`, and `checks` |
| Segments | `record_sha256`, plus `status`, `message`, `segments`, `runlog_version`, and `config` for each channel |

Each configuration contains all the fields for that analysis.
The tag command replaces only the report for the selected channel.
If a channel is missing, its result is `not_testable` with no segments.
The message gives the reason. The reader also accepts older sidecars without this message.

The record loader compares the record id, Parquet hash, sample count, and channel order with the sidecar.
The `verify` and `index` commands reject analysis sidecars with stale hashes or missing version or configuration fields.
The `verify` command also reports missing files, extra files, and invalid sidecars. It ignores hidden files.
If the data changes, rebuild the catalog.

Record ids must match `[A-Za-z0-9][A-Za-z0-9_.-]{0,63}`.
Channel names must be unique. Each channel must have a non-empty unit.
Attribute keys must be strings. Attribute values can be numbers, strings, or booleans.

### Import logs

For CSV files, supply a JSON map of channels to units with `--units`.
OpenFAST `.out` and `.outb` files supply units in their headers.
The binary reader supports FileIDs 1–4. It rejects unsupported formats and incomplete files.

| Option | Function |
|---|---|
| `--time-column` | Select the CSV time column. The default is `time`. |
| `--id-from stem` | Use the file stem as the record id. This is the default. |
| `--id-from parent` | Use the parent directory name as the record id. |
| `--attrs` | Supply a JSON map of record ids or filenames to attributes. The record id takes priority. |
| `--overwrite` | The option replaces the record. It deletes the old check and tag sidecars. |

Duplicate input ids cause an error.
The import procedure keeps time errors for subsequent checks.
It does not sort, resample, or impute samples.

## Quality checks

Each result has the status `pass`, `fail`, or `not_testable`.
The default rules are:

| Check | Rule |
|---|---|
| `time_monotonic` | The timestamps must be finite and strictly increasing. |
| `sample_rate` | Non-gap steps must be within 1% of the median, with a bounded allowance for clock rounding. An expected rate must also agree within 1%. |
| `gaps` | No step can exceed three times the median step. |
| `duration` | The duration must be at least 10 s. |
| `non_finite` | The channel cannot contain NaN or infinite values. |
| `flatline` | No run of identical values can exceed 2 s. |
| `clipping` | Runs at channel extrema can contain at most 1% of samples. The check counts runs of at least three samples. |
| `spikes` | The curvature-residual score cannot exceed 8. Consecutive exceedances count as one event. |
| `derivative_pair` | The position-change and velocity-integral discrepancy cannot exceed 0.05. This check needs a configured pair. |

### Spike score

The spike check uses this calculation:

```text
d2[i] = x[i-1] - 2*x[i] + x[i+1]
r = d2 - rolling_median(d2, spike_detrend_window)
m = rolling_median(r, spike_window)
MAD = rolling_median(abs(r - m), spike_window)
scale = max(1.4826*MAD, IQR(d2)/1.349, 8*quantum/sqrt(2))
score = abs(r)/scale
```

The default trend window has seven samples. The default scale window has 101 samples.

The algorithm centers each window. Each absolute deviation uses the median at its own sample.
The IQR calculation uses `spike_window`. Its lower bound prevents a zero scale on smooth curves.
Consecutive scores above `spike_z` form one event.

The check does not score the first or last `spike_detrend_window // 2` second differences.
At each record end, the scale uses the nearest complete window.
For a shorter record, the scale uses the center value throughout.
If no complete trend window exists, the result is `not_testable`.

With zero scale, a zero residual gives score zero. A nonzero residual gives infinity.
If all scale and residual values are zero, the result is `not_testable`.

The rounding calculation uses variance `quantum²/12` and second-difference noise SD `quantum/sqrt(2)`, with safety factor 8.
The quantum calculation fits sorted unique values to a lattice with float32 tolerance.
It tests up to 32 subdivisions of the smallest spacing. It needs at least three distinct values.

### Clock check

The check excludes gap steps from the spacing and rate calculations.
The timestamp resolution is the smallest nonzero deviation from the median step that occurs in a sufficient fraction of regular steps.
The fraction is `resolution_min_fraction`, with default 5%. Floating-point roundoff does not contribute.

The resolution allowance applies only if the cumulative regular steps stay near one uniform clock.
The residual range from the endpoint-based uniform grid cannot exceed twice the resolution plus roundoff.
A small set of step sizes does not satisfy this rule by itself. A sustained rate change fails the check.

If the configuration specifies `expected_rate_hz`, this additional condition applies:

```text
abs(mean_non_gap_step * expected_rate_hz - 1) <= sample_rate_rel_tol
```

The timestamp resolution does not increase this tolerance.
The result message gives the expected and measured rates.

### Position–velocity check

This check needs approximately uniform time steps with no gaps.
It compares position changes with composite Simpson integrals of velocity:

```text
d[i] = x[i+m] - x[i]
I[i] = (dt/3) * sum(weights * velocity[i:i+m+1])
weights = [1, 4, 2, 4, ..., 2, 4, 1]
value = RMS(d - I) / std(x)
```

The symbol `dt` is the mean time step. The symbol `m` is the span in steps.
The default span is one quarter of the dominant position period.
The period calculation removes the mean and applies a Hann window.
It then selects the largest positive-frequency FFT bin.

To set a different span, use `derivative_pair_span_s`.
The span rounds to the nearest even step count, with a minimum of two. Ties round up.
Messages give the span in steps and seconds.

Invalid time spacing, constant position, or fewer than four spans give `not_testable`.
See [Limits](#limits) for offset sensitivity and harmonic blind spots.

### Data requirements

Time-spacing and channel checks usually need ten samples.
Monotonicity needs two samples. Duration fails with fewer than two samples.
Duration gives `not_testable` if time is non-finite or not strictly increasing.
The other channel checks need finite values. The clipping check cannot test a constant channel.

### Configuration and commands

To set `CheckConfig` fields, use `check --config checks.json`.
To override the channel selection, use `--channels a,b,c`. Time checks always apply.
To set `SegmentConfig` fields, use `tag --config segments.json`.
The mandatory `--noise-floor` value overrides the file value.

The `CheckConfig` constructor rejects values outside these limits:

| Field | Limit |
|---|---|
| All numeric thresholds | Finite real numbers. Booleans and numeric strings are invalid. |
| `sample_rate_rel_tol`, `min_duration_s`, `max_flatline_s`, `derivative_pair_rel_tol` | Non-negative |
| `spike_z`, optional `expected_rate_hz`, optional `derivative_pair_span_s` | Positive |
| `gap_factor` | Greater than one |
| `non_finite_fraction`, `clipping_fraction` | `[0, 1]` |
| `resolution_min_fraction` | `(0, 1]` |
| `clipping_min_run` | Positive integer |
| Spike windows | Odd integers of at least three |

Selected channel names must be unique and non-empty.
Each derivative pair must contain two non-empty channel names.
Neither selection can use `time` as a signal channel.
The constructor converts JSON lists to tuples. An empty channel selection gives only time checks.

| Exit code | Meaning |
|---|---|
| 0 | The command completed. The `check` command found no failures, but results can include `not_testable`. |
| 1 | A check failed or verification found an error. |
| 2 | A usage or data error occurred. |

The check summary counts each status.
The tag summary counts processed records, taggable records (`status="ok"`), untestable records, and segments.
A taggable record can have no segments if no interval satisfies a rule.

## Segment tags

The envelope is the centered rolling standard deviation, or RMS about the window mean.
At record ends, the window uses the available samples.
The default window is 10 s. The positive `noise_floor` value has channel units.

| Tag | Rule |
|---|---|
| `quiet` | The envelope is below the noise floor. |
| `steady` | Flat windows form a candidate. Each window has at least `min_steady_s` (default 30 s). Reported boundaries reach `transition_high` times its level. |
| `buildup` | The envelope increases from below `transition_low` to at least `transition_high` times the next steady level. |
| `decay` | The envelope follows the reverse buildup rule after a steady interval. |

A flat window has a range at most `2*rel_tol*median`. Its median is at least the noise floor.
The default `rel_tol` is 0.05.
The steady level is the median envelope of the merged candidate.

The transition limits have defaults 0.3 and 0.9. They must satisfy `0 < transition_low < transition_high <= 1`.
Buildup and decay permit dips of at most `rel_tol` times the steady level.
Other intervals have no tag.

Each segment contains these fields:

```text
record_id, channel, start_s, end_s, tag, rms, peak_freq_hz, method, method_version
```

The method is `rolling_std`, version 4.
Segment RMS is the RMS about the segment mean.
The frequency calculation uses a Hann-window FFT and log-parabolic interpolation around the peak.
A peak at the end of the spectrum uses its bin frequency.
Constant segments or spans shorter than the window have no peak frequency.

The tag command needs finite channels, increasing time, approximately uniform spacing, no gaps, and at least two envelope windows.
It applies the default `gaps` and `sample_rate` rules, including the clock-rounding allowance.
Window lengths and frequencies use the mean step. This prevents median-step bias on rounded clocks.

Each interval includes its start and excludes its end.
The last sample interval ends one mean step after its timestamp.
The catalog duration excludes this final interval.
The `steady_coverage` query adds that interval when the rate is known.

## Catalog

These SQL examples use the fault-injection dataset from `examples/quickstart.sh`.
Its `vr` values are artificial test attributes.

The `index` command builds the SQLite catalog in one transaction.
It then replaces the catalog file with the completed file in one atomic operation.
Foreign keys connect child tables to `records`.
Indexes cover `segments(tag)`, `attrs(key, value_num)`, and `checks(record_id, status)`.

The sample-rate calculation uses the mean non-gap step.
Invalid or detectably non-uniform time gives null.
With fewer than ten samples, the rate is an untested estimate.

| Table | Columns |
|---|---|
| `records` | `record_id`, `n_samples`, `duration_s`, `sample_rate_hz`, `sha256`, `source` |
| `channels` | `record_id`, `name`, `unit` |
| `attrs` | `record_id`, `key`, `value_num`, `value_text` |
| `checks` | `record_id`, `check_name`, `channel`, `status`, `value`, `threshold`, `message` |
| `segments` | `segment_id`, `record_id`, `channel`, `start_s`, `end_s`, `tag`, `method`, `method_version`, `rms`, `peak_freq_hz` |

Numbers and booleans use `value_num`. Boolean values are 1 or 0. Strings use `value_text`.
The query command opens SQLite in read-only mode.
An authorizer blocks writes and database attachment.
The `--format` option selects table, CSV, or JSON output.

To list steady RMS by `vr`, use this command. The query excludes records with failed checks.

```bash
.venv/bin/python -m runlog query --dataset examples/output/dataset \
  "SELECT s.record_id, ROUND(a.value_num, 3) AS vr, ROUND(s.rms, 5) AS steady_rms_m FROM segments s JOIN attrs a ON a.record_id = s.record_id AND a.key = 'vr' WHERE s.tag = 'steady' AND NOT EXISTS (SELECT 1 FROM checks c WHERE c.record_id = s.record_id AND c.status = 'fail') ORDER BY a.value_num" \
  --format csv
```

## SQL export

The local SQLite catalog needs no server.
To export the catalog through SQLAlchemy Core, install the `mysql` extra.
Save connection credentials in the environment:

```bash
export RUNLOG_DB_URL='mysql+pymysql://runlog@db.example/runlog'
.venv/bin/python -m runlog export --dataset examples/output/dataset
```

The export command reports row counts.
The `--replace` option drops and recreates existing tables.
MySQL DDL statements commit immediately. Thus, a failed replacement can leave empty tables.
All row inserts occur in one transaction.

The six queries in `examples/queries.sql` support SQLite 3.35+ and MySQL 8.4.
CI compares their results on both databases.
To get failure rates, use this command:

```bash
.venv/bin/python -m runlog query --dataset examples/output/dataset \
  --file examples/queries.sql --name check_failure_rates --format csv
```

The query counts failures and divides by all results. The denominator includes `not_testable` results.

```sql
SELECT check_name,
       SUM(CASE WHEN status = 'fail' THEN 1 ELSE 0 END) AS failure_count,
       1e0 * SUM(CASE WHEN status = 'fail' THEN 1 ELSE 0 END) / COUNT(*) AS failure_rate
FROM checks
GROUP BY check_name
ORDER BY check_name;
```

The expected output is:

```text
check_name,failure_count,failure_rate
clipping,1,0.015625
duration,0,0.0
flatline,1,0.015625
gaps,1,0.0625
non_finite,1,0.015625
sample_rate,0,0.0
spikes,3,0.046875
time_monotonic,0,0.0
```

## Python API

The dataset functions save sidecars. They return results by record id.

```python
import numpy as np
import pandas as pd

from runlog import SegmentConfig, build_catalog, check_dataset, query, tag_dataset, write_record

time = np.arange(0, 300, 0.05)
frame = pd.DataFrame({"time": time, "sway": 0.1 * np.sin(2 * np.pi * 1.0044 * time)})
dataset = "research_dataset"
write_record(frame, dataset, "run_01", {"sway": "m"}, source="synthetic")
checks = check_dataset(dataset)
reports = tag_dataset(dataset, "sway", SegmentConfig(noise_floor=0.005))
build_catalog(dataset)
rows = query(
    dataset,
    "SELECT record_id, rms, peak_freq_hz FROM segments WHERE tag = ?",
    ("steady",),
)
```

The record functions return analysis results. They do not save analysis sidecars.

```python
from runlog import CheckConfig, SegmentConfig, load_record, run_checks, tag_segments

frame, meta = load_record("examples/output/dataset", "run_01")
checks = run_checks(frame, meta.record_id, CheckConfig())
report = tag_segments(
    frame.time, frame.sway, meta.record_id, "sway", SegmentConfig(noise_floor=0.005)
)
```

## Validation

The [report](validation/README.md) and [JSON results](validation/check_characteristics.json) contain the inputs, test procedures, and measured results.
To make the report again, use this command:

```bash
.venv/bin/python examples/validate_checks.py
```

## Limits

The checks find rule violations. They do not prove physical invalidity.
Select settings for the channels. One check configuration applies to all selected channels.

### Time

Bounded clock rounding does not prove the true hardware sample times.
The tag command rejects gaps and non-uniform spacing.

### Channel checks

An intentionally held value can fail the flatline or clipping check.
The clipping check cannot test a fully constant channel.
To handle these channels, exclude them or change the thresholds.
Identical extrema in rounded or simulated data can cause clipping failures.

### Spikes

The rule assumes a Gaussian-like noise core.
Heavy tails, steps, angle wraps, and blade tower passages can produce events.
Wide glitches reduce sensitivity.
A low ratio of sample rate to signal frequency also reduces sensitivity.
Select applicable channels or change `spike_z`.
The check does not score incomplete trend windows at the record ends.

### Tags

The `steady` tag means approximately constant amplitude. It does not prove stationarity or dynamical stability.

Random responses have fluctuating envelopes and are sensitive to `rel_tol`.
Measurement noise biases RMS. High noise levels can prevent tags.
Slow ramps can extend steady intervals and bias RMS.
Mean drift can leave transitions without tags.

### Derivative pairs

Multiple peaks, drift, or noise can select an unsuitable span.
A constant velocity offset `b` gives score `m*dt*abs(b)/std(x)`.
For a sine and a quarter-period span, the scale-error score is approximately `sqrt(2)*abs(scale_error)`.
Harmonic errors can cancel if the span contains whole harmonic periods.
To select the component of interest, set `derivative_pair_span_s`.

The fault-injection dataset does not configure derivative pairs.
Its fixed 0.5 mm position noise can cause small responses to exceed the default tolerance.
The validation report contains the measured noise, detection, and blind-spot results.
