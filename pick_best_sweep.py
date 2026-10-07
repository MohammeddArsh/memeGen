"""Pick the best 6k-step screening run for the confirmation run.

The six screening runs are one-knob-at-a-time changes to the base
CLIP+Transformer config. Each saved best.pt holds its best val_loss. The
winner gets a full-budget confirmation run with the same extra args.

Screening rows are NOT comparable to the full-budget (1-epoch) ladder rows --
they only rank the knobs. The confirmation is what enters the headline
results table.
"""
import json
import sys
from pathlib import Path

import torch

BASE = Path("checkpoints/sweep")

# name -> extra train.py args applied on top of the base config
RUNS = {
    "lr_1e-4": ["--lr", "1e-4"],
    "lr_1e-3": ["--lr", "1e-3"],
    "emb_256": ["--embed-dim", "256"],
    "emb_768": ["--embed-dim", "768"],
    "layers_4": ["--layers", "4"],
    "maxlen_40": ["--max-length", "40"],
}


def best_loss(name):
    ck = torch.load(BASE / name / "best.pt", map_location="cpu",
                    weights_only=False)
    return ck["val_loss"]


def main():
    results = []
    for name, extra in RUNS.items():
        bp = BASE / name / "best.pt"
        if not bp.exists():
            print(f"MISSING best.pt for {name}", file=sys.stderr)
            continue
        results.append((best_loss(name), name, extra))

    if not results:
        sys.exit("no screening best.pt files found - aborting confirmation")

    results.sort()
    val, winner, extra = results[0]

    summary = {
        "winner": winner,
        "val_loss": round(val, 4),
        "extra": extra,
        "ranking": [{"name": n, "val_loss": round(v, 4)} for v, n, _ in results],
    }
    out = BASE / "best.json"
    out.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()