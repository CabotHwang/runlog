# runlog

Convert time-series logs into a dataset with quality checks, segment tags, and SQL queries.

[![CI](https://github.com/CabotHwang/runlog/actions/workflows/ci.yml/badge.svg)](https://github.com/CabotHwang/runlog/actions/workflows/ci.yml)

I use runlog for data quality checks and cataloging in my master's research on vortex-induced motion (VIM) of floating offshore wind turbines.

```text
Log files → Parquet + metadata → quality checks → segment tags → SQL queries
```

![Controlled oscillator: input force and calculated displacement with segment tags](https://raw.githubusercontent.com/CabotHwang/runlog/main/docs/figures/record_timeline.png)

## Installation

Use Python 3.11 or later. Use these commands at the root of the repository:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
```

For plots, install `'.[plot]'`. For MySQL export, install `'.[mysql]'`.
See [CONTRIBUTING](https://github.com/CabotHwang/runlog/blob/main/CONTRIBUTING.md) for development instructions.

## Controlled example

Use this command:

```bash
.venv/bin/python examples/run_oscillator_case.py
```

The example script starts a harmonic force at 60 s and stops it at 240 s.
It solves the motion equation and saves the response in a CSV file.

Runlog imports this file. It does the quality checks. Then it assigns segment tags and queries the catalog.
All 13 checks pass. The tag sequence is `quiet → buildup → steady → decay → quiet`.

The figure shows the input force and the displacement from the same record.
The tag command uses time and displacement. It does not use the force schedule.

To make the figure, install the `plot` extra. Then use this command:

```bash
.venv/bin/python examples/plot_record.py
```

See the [example description](https://github.com/CabotHwang/runlog/blob/main/docs/oscillator_example.md) for the model, settings, and numerical tests.

## Fault-injection example

Use this command:

```bash
bash examples/quickstart.sh
```

Sixteen synthetic records contain gaps, frozen sensor values, spikes, clipping, and NaN values.
These faults cause seven check failures. The record with a gap receives no segment tags.

## Data and results

- Import CSV or OpenFAST `.out` and `.outb` files into Parquet files.
- Keep the original sample order and values. No sorting, resampling, or imputation occurs.
- Save units, record attributes, hashes, and analysis settings in JSON sidecars.
- Get quality results with the status `pass`, `fail`, or `not_testable`.
- Get segment tags, RMS values, and peak frequencies.
- Query the SQLite catalog or export it to MySQL.

The record loader compares each Parquet file with its metadata.
If records or analysis sidecars change, rebuild the catalog.

## Interpretation

A check failure shows a rule violation. It does not prove a physical fault.
The `steady` tag means approximately constant amplitude in a moving window.
It does not prove statistical stationarity or dynamical stability.
The tag command needs approximately uniform time steps with no gaps.
Select thresholds for each channel and its acquisition conditions.

See the [reference](https://github.com/CabotHwang/runlog/blob/main/docs/reference.md) for algorithms, commands, the Python API, and failure conditions.
The [validation report](https://github.com/CabotHwang/runlog/blob/main/docs/validation/README.md) and [JSON results](https://github.com/CabotHwang/runlog/blob/main/docs/validation/check_characteristics.json) contain the measured results.
To make the report again, use this command:

```bash
.venv/bin/python examples/validate_checks.py
```

## License

[MIT](https://github.com/CabotHwang/runlog/blob/main/LICENSE).
