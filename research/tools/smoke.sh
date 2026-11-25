#!/usr/bin/env bash
# End-to-end smoke test on SYNTHETIC data (tools/synthetic.py). Everything goes to a temp directory;
# research/results/ and store/ are not touched. Usage: tools/smoke.sh [workdir]
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
W=${1:-$(mktemp -d)}
export RESEARCH_HASH_SALT=smoke-test-salt-not-secret-0123456789
echo "workdir: $W"

$PY -m tools.synthetic --out "$W"
$PY -m pii.redact "$W/raw.jsonl" --out "$W/redacted.jsonl"
$PY -m annotate.export "$W/redacted.jsonl" --out "$W/batches" --batch-size 500 --annotators a1,a2 --overlap 0.25
$PY -m annotate.importer "$W/ls_export.json" --out "$W/annotations" --annotator-map 1=a1,2=a2
$PY -m annotate.agreement "$W/annotations/annotations.jsonl" --results-dir "$W/results"
$PY -m data.splits --posts "$W/redacted.jsonl" --gold "$W/annotations/gold.jsonl" --out "$W/splits" \
    --results-dir "$W/results"
for s in time channel time_channel; do
  $PY -m models.run --config models/configs/tfidf_lr.yaml --split $s --splits-dir "$W/splits" \
      --results-dir "$W/results"
done
$PY -m robustness.attacks --config models/configs/tfidf_lr.yaml --split time_channel --splits-dir "$W/splits" \
    --attacks char,translit,emoji --results-dir "$W/results"
$PY -m graph.build "$W/redacted.jsonl" --labels "$W/annotations/gold.jsonl" --out "$W/graph" \
    --results-dir "$W/results"
echo "results: $W/results"
ls "$W/results"
