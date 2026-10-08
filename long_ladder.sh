#!/bin/bash
# Long-training chain: Run D at 1 epoch (completes the 1-epoch 2x2 table),
# then A/B/C/D/E at 3 epochs = 18,750 steps (the extended-training tier).
# Runs fully offline (HF_HUB_OFFLINE=1) - needs power and an awake machine,
# not internet. Chain survives sleep: waits are marker/log driven.
# Usage: nohup ./long_ladder.sh > checkpoints/long_ladder.out 2>&1 &
set -u
cd "$(dirname "$0")"
PY=../memeGen_ai/.venv/bin/python
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

log() { echo "[$(date)] $*" >> checkpoints/long_ladder.log; }

run_long() {
    name=$1; epochs=$2; save=$3; shift 3
    mkdir -p "checkpoints/$name"
    log "=== $name started (epochs=$epochs) ==="
    $PY -u train.py --out "checkpoints/$name" --subsample 200000 --seed 42 \
        --epochs "$epochs" --save-every "$save" "$@" \
        >> "checkpoints/$name/run.log" 2>&1
    log "=== $name finished rc=$? ==="
}

log "long ladder starting (offline mode, 6 runs)"

# 1. Run D at 1 epoch -> completes the existing 1-epoch table
run_long resnet50_transformer 1 1000 \
    --encoder resnet50 --decoder transformer

# 2-6. 3-epoch tier (18,750 steps each, save every 3000 = 6 ckpts)
run_long long_resnet50_lstm        3 3000 \
    --encoder resnet50 --decoder lstm
run_long long_clip_lstm            3 3000 \
    --encoder clip     --decoder lstm
run_long long_clip_transformer     3 3000 \
    --encoder clip     --decoder transformer
run_long long_resnet50_transformer 3 3000 \
    --encoder resnet50 --decoder transformer
run_long long_clip_transformer_emb768 3 3000 \
    --encoder clip --decoder transformer --embed-dim 768

log "long ladder complete"
