#!/bin/bash
# Overnight queue: waits for the ladder (C->B->A) to finish, then runs the
# 6k-step hyperparameter screening and one full-budget confirmation.
# Usage: nohup ./overnight.sh > checkpoints/overnight.out 2>&1 &
set -u
cd "$(dirname "$0")"
PY=../memeGen_ai/.venv/bin/python

log() { echo "[$(date)] $*" >> checkpoints/sweep.log; }

wait_for_ladder() {
    log "waiting for ladder to complete ..."
    while ! grep -q "ladder complete" checkpoints/ladder.log 2>/dev/null; do
        sleep 60
    done
    log "ladder complete - starting sweep"
}

run_screen() {
    name=$1; shift
    mkdir -p "checkpoints/sweep/$name"
    log "=== screening $name started ==="
    $PY -u train.py --encoder clip --decoder transformer \
        --subsample 200000 --max-steps 6000 \
        --out "checkpoints/sweep/$name" "$@" \
        >> "checkpoints/sweep/$name/run.log" 2>&1
    log "=== screening $name finished rc=$? ==="
}

wait_for_ladder

run_screen lr_1e-4   --lr 1e-4
run_screen lr_1e-3   --lr 1e-3
run_screen emb_256   --embed-dim 256
run_screen emb_768   --embed-dim 768
run_screen layers_4  --layers 4
run_screen maxlen_40 --max-length 40

log "picking best screening config ..."
$PY pick_best_sweep.py >> checkpoints/sweep.log 2>&1
[ -f checkpoints/sweep/best.json ] || { log "FATAL: best.json missing"; exit 1; }

read -r -a EXTRA < <($PY -c "import json;print(' '.join(json.load(open('checkpoints/sweep/best.json'))['extra']))")
log "confirmation run with args: ${EXTRA[*]}"

mkdir -p "checkpoints/sweep/best_confirm"
$PY -u train.py --encoder clip --decoder transformer \
    --subsample 200000 --max-steps 6250 \
    --out "checkpoints/sweep/best_confirm" "${EXTRA[@]}" \
    >> "checkpoints/sweep/best_confirm/run.log" 2>&1
log "confirmation finished rc=$? - overnight queue complete"