#!/usr/bin/env bash
# Reproducible provisioning for CHIMERA offline training (B1).
#
# Codifies the ad-hoc build-check/ setup into one idempotent script. It ONLY fetches and
# verifies inputs; it never trains, never downloads at runtime, and never commits artifacts.
# Datasets and model weights stay gitignored (raw/, artifacts/, build-check/).
#
# Sources are operator-configurable. HF/GitHub sources are fetched automatically; Kaggle
# sources (creditcard.csv, PaySim) require manual placement because they need auth.
# Every provisioned file is hashed into PROVISION_MANIFEST.json for reproducibility.
#
# Usage:
#   MODEL_ID=google/bert_uncased_L-2_H-128_A-2 \
#   SPML_SRC=/path/to/spml/train.jsonl \
#   CREDITCARD_CSV=/path/to/creditcard.csv \
#   PAYSIM_CSV=/path/to/paysim.csv \
#   bash provision.sh [--force]
#
# Set MODEL_ID to the SAME base encoder used for v4/v5 so numbers stay comparable.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRAIN="$ROOT/fraud-gate/training"
RAW="$TRAIN/raw"
BUILD="$ROOT/build-check"
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

MODEL_ID="${MODEL_ID:-google/bert_uncased_L-2_H-128_A-2}"
JBB_REPO="${JBB_REPO:-https://github.com/JailbreakBench/jailbreakbench}"
ITW_DATASET="${ITW_DATASET:-TrustAIRLab/in-the-wild-jailbreak-prompts}"
SPML_SRC="${SPML_SRC:-}"
CREDITCARD_CSV="${CREDITCARD_CSV:-}"
PAYSIM_CSV="${PAYSIM_CSV:-}"

mkdir -p "$RAW/spml" "$RAW/jailbreakbench" "$RAW/in_the_wild_jailbreaks" "$BUILD/l4_base" "$TRAIN/artifacts"

manifest="$BUILD/PROVISION_MANIFEST.json"
hash_file() { python -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$1"; }
record() { python - "$manifest" "$1" "$2" <<'PY'
import json,sys,os
path,key,val=sys.argv[1],sys.argv[2],sys.argv[3]
data=json.load(open(path)) if os.path.exists(path) else {}
data[key]=val
json.dump(data,open(path,'w'),indent=2,sort_keys=True)
PY
}
have() { [ -e "$1" ] && [ "$FORCE" -eq 0 ]; }

echo "== 1/5 base encoder ($MODEL_ID) -> build-check/l4_base =="
if have "$BUILD/l4_base/config.json"; then
  echo "   present; skip (use --force to refetch)"
else
  python - "$MODEL_ID" "$BUILD/l4_base" <<'PY'
import sys
from huggingface_hub import snapshot_download
snapshot_download(repo_id=sys.argv[1], local_dir=sys.argv[2],
                  allow_patterns=["*.json","*.txt","*.model","*.safetensors","*.bin"])
PY
fi
record base_encoder "$MODEL_ID"

echo "== 2/5 JailbreakBench behaviors -> raw/jailbreakbench =="
if have "$RAW/jailbreakbench/harmful-behaviors.csv"; then
  echo "   present; skip"
else
  tmp="$BUILD/jbb-src"
  [ -d "$tmp" ] || git clone --depth 1 "$JBB_REPO" "$tmp"
  # Locate the CSVs without assuming an internal path.
  find "$tmp" -name 'harmful-behaviors.csv' -exec cp {} "$RAW/jailbreakbench/" \;
  find "$tmp" -name 'benign-behaviors.csv' -exec cp {} "$RAW/jailbreakbench/" \;
fi
for f in harmful-behaviors.csv benign-behaviors.csv; do
  [ -f "$RAW/jailbreakbench/$f" ] && record "jbb/$f" "$(hash_file "$RAW/jailbreakbench/$f")"
done

echo "== 3/5 in-the-wild jailbreak prompts -> raw/in_the_wild_jailbreaks =="
if have "$RAW/in_the_wild_jailbreaks"; then
  if ls "$RAW/in_the_wild_jailbreaks"/*.parquet >/dev/null 2>&1; then
    echo "   present; skip"
  else
    python - "$ITW_DATASET" "$RAW/in_the_wild_jailbreaks" <<'PY'
import sys
from huggingface_hub import snapshot_download
snapshot_download(repo_id=sys.argv[1], repo_type="dataset", local_dir=sys.argv[2],
                  allow_patterns=["*.parquet"])
PY
  fi
fi
for f in "$RAW/in_the_wild_jailbreaks"/*.parquet; do
  [ -f "$f" ] && record "itw/$(basename "$f")" "$(hash_file "$f")"
done

echo "== 4/5 SPML external corpus -> raw/spml/train.jsonl =="
if have "$RAW/spml/train.jsonl"; then
  echo "   present; skip"
elif [ -n "$SPML_SRC" ] && [ -f "$SPML_SRC" ]; then
  cp "$SPML_SRC" "$RAW/spml/train.jsonl"
else
  echo "   MANUAL: set SPML_SRC=/path/to/spml/train.jsonl (source is operator-supplied)." >&2
fi
[ -f "$RAW/spml/train.jsonl" ] && record "spml/train.jsonl" "$(hash_file "$RAW/spml/train.jsonl")"

echo "== 5/5 Kaggle card + wire CSVs (manual; auth required) =="
if [ -n "$CREDITCARD_CSV" ] && [ -f "$CREDITCARD_CSV" ]; then
  cp "$CREDITCARD_CSV" "$RAW/creditcard.csv"; record "creditcard.csv" "$(hash_file "$RAW/creditcard.csv")"
else
  echo "   MANUAL: place creditcard.csv (Kaggle 'Credit Card Fraud Detection') at $RAW/creditcard.csv" >&2
fi
if [ -n "$PAYSIM_CSV" ] && [ -f "$PAYSIM_CSV" ]; then
  cp "$PAYSIM_CSV" "$RAW/paysim.csv"; record "paysim.csv" "$(hash_file "$RAW/paysim.csv")"
else
  echo "   MANUAL: place PaySim CSV (Kaggle 'PaySim1') at $RAW/paysim.csv" >&2
fi

echo
echo "Provision manifest: $manifest"
echo "Next (offline, never auto-run here):"
echo "  python $TRAIN/prepare_l4_v5_data.py --splits-dir <splits> --output-dir $TRAIN/artifacts/l4_v5 \\"
echo "    --spml $RAW/spml/train.jsonl --jbb-dir $RAW/jailbreakbench --itw-dir $RAW/in_the_wild_jailbreaks"
echo "  python $TRAIN/augment_l4_persona.py --input <v5_train> --eval <v5_test> --output <v5_train_aug>"
echo "  python $TRAIN/train_l4_semantic_guard.py --data <v5_train_aug> --base-model $BUILD/l4_base ..."
echo "  python $TRAIN/calibrate_l4_v5.py --model <int8.onnx> --tokenizer <encoder> \\"
echo "    --in-domain-calib <calib> --external-calib <ext_calib> --in-domain-test <test> --external-test <ext_test>"
echo "  python $TRAIN/train_creditcard_hgb.py --data $RAW/creditcard.csv --output <artifact> --version <v>"
echo "  python $TRAIN/train_paysim_wire.py --data $RAW/paysim.csv --output <artifact> --version <v>"