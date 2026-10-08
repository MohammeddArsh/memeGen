#!/bin/bash
# Evaluate the 6 checkpoints from long_ladder.sh on the test split.
# Offline-safe, sequential, per-eval logs. Writes metrics + gold/pred pairs.
# Usage: nohup ./eval_long.sh > checkpoints/eval_long.out 2>&1 &
set -u
cd "$(dirname "$0")"
PY=../memeGen_ai/.venv/bin/python
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

log() { echo "[$(date)] $*" >> checkpoints/eval_long.log; }

run_eval() {
    name=$1
    log "=== eval $name started ==="
    $PY -u eval.py --checkpoint "checkpoints/$name/best.pt" --split test \
        --out "results/$name.json" \
        --samples-out "results/samples_$name.json" \
        >> "checkpoints/${name}_eval.log" 2>&1
    log "=== eval $name finished rc=$? ==="
}

log "eval chain starting (offline mode, 6 runs)"
run_eval resnet50_transformer
run_eval long_resnet50_lstm
run_eval long_clip_lstm
run_eval long_clip_transformer
run_eval long_resnet50_transformer
run_eval long_clip_transformer_emb768
log "eval chain complete"
