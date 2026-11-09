#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH=src
PYTHON=.venv/bin/python
DATASET=examples/output/dataset
"$PYTHON" examples/make_demo_data.py
"$PYTHON" -m runlog ingest examples/output/raw/run_*.csv --dataset "$DATASET" --units examples/output/raw/units.json --attrs examples/output/raw/attrs.json --overwrite
# The demo contains five faulty runs. Exit code 1 is expected.
if "$PYTHON" -m runlog check --dataset "$DATASET"; then
    echo "Expected injected faults were not found." >&2
    exit 1
else
    status=$?
    if [ "$status" -ne 1 ]; then exit "$status"; fi
fi
"$PYTHON" -m runlog tag --dataset "$DATASET" --channel sway --noise-floor 0.005
"$PYTHON" -m runlog verify --dataset "$DATASET"
"$PYTHON" -m runlog index --dataset "$DATASET"
"$PYTHON" -m runlog query --dataset "$DATASET" "SELECT s.record_id, ROUND(a.value_num, 3) AS vr, ROUND(s.rms, 5) AS steady_rms_m FROM segments s JOIN attrs a ON a.record_id = s.record_id AND a.key = 'vr' WHERE s.tag = 'steady' AND NOT EXISTS (SELECT 1 FROM checks c WHERE c.record_id = s.record_id AND c.status = 'fail') ORDER BY a.value_num" --format csv
