#!/bin/bash
# One-command demo for graders: render a caption on a template.
#   ./demo.sh                       # random template, best checkpoint
#   ./demo.sh <image> [checkpoint]  # explicit
# Default checkpoint is the best extended-training run (3 epochs, embed 768).
set -eu
cd "$(dirname "$0")"
PY=../memeGen_ai/.venv/bin/python
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

CKPT="${2:-checkpoints/long_clip_transformer_emb768/best.pt}"
IMG="${1:-$(ls memes900k/images/*.jpg | sort -R | head -1)}"
OUT="demo_out/$(basename "${IMG%.*}").jpg"
mkdir -p demo_out

echo "checkpoint: $CKPT"
echo "image:      $IMG"
"$PY" caption.py --image "$IMG" --checkpoint "$CKPT" \
    --strategy sample --seed -1 --overlay "$OUT"
echo "saved -> $OUT"
