#!/bin/bash
# Chain the ladder after Run C so it trains unattended overnight.
# Usage: nohup ./ladder.sh <pid_of_run_c> > checkpoints/ladder.out 2>&1 &
set -u
cd "$(dirname "$0")"

wait_pid() {
    while kill -0 "$1" 2>/dev/null; do sleep 60; done
}

run_ref() {
    name=$1
    echo "[$(date)] === $name started ===" >> checkpoints/ladder.log
    mkdir -p "checkpoints/$name"
    ../memeGen_ai/.venv/bin/python -u train.py \
        --out "checkpoints/$name" --subsample 200000 --max-steps 6250 \
        --encoder "${ENC}" --decoder "${DEC}" \
        >> "checkpoints/$name/run.log" 2>&1
    rc=$?
    echo "[$(date)] === $name finished rc=$rc ===" >> checkpoints/ladder.log
    return $rc
}

RUN_C_PID="${1:?pass the PID of the running Run C}"
echo "[$(date)] ladder waiting for Run C (pid $RUN_C_PID) ..." >> checkpoints/ladder.log
wait_pid "$RUN_C_PID"

ENC=clip
DEC=lstm
run_ref clip_lstm

ENC=resnet50
DEC=lstm
run_ref resnet50_lstm

echo "[$(date)] ladder complete" >> checkpoints/ladder.log