"""Evaluation: perplexity on the full split, BLEU on a fixed sample.

Two numbers for two different questions.

Perplexity is teacher-forced and batched, so it runs over all 75,000 rows
cheaply -- but it is only comparable between OUR runs, because DeepHumor
builds its vocabulary from the dataset and we use GPT2 byte-pair encoding.

BLEU measures generated text and is comparable across tokenizers, so it is
the number that speaks to DeepHumor. It costs one autoregressive decode per
row, hence the fixed sample: identical rows and identical seed for every
model, which is what makes the comparison a comparison.
"""
import argparse
import json
import math
import random
from pathlib import Path

import sacrebleu
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader

import data
from encoders import precompute_features, features_to_tensor, ENCODER_DIMS
from model import build_model, generate_batch

DATA_DIR = Path(__file__).parent / "memes900k"


def load_checkpoint(path, device):
    ckpt = torch.load(path, map_location="cpu", weights_only=False)
    a = dict(ckpt["args"])
    tok = data.build_tokenizer()
    model = build_model(a["decoder"], len(tok), data.PAD_ID,
                        ENCODER_DIMS[a["encoder"]], a).to(device)
    model.load_state_dict(ckpt["model"])
    model.eval()
    return model, a, ckpt, tok


def perplexity(model, rows, image_files, feat_tensor, tok, args, max_length, device):
    """Teacher-forced NLL over every row -> exp(mean NLL)."""
    ds = data.MemeDataset(rows, tok, image_files, max_length)
    dl = DataLoader(ds, batch_size=args.batch_size, shuffle=False, num_workers=0,
                    collate_fn=lambda b: data.collate(b, max_length))
    total, count = 0.0, 0
    with torch.no_grad():
        for img_idx, padded, _ in dl:
            img_idx, padded = img_idx.to(device), padded.to(device)
            logits = model(feat_tensor[img_idx], padded[:, :-1])
            loss = F.cross_entropy(
                logits.reshape(-1, logits.size(-1)),
                padded[:, 1:].reshape(-1),
                ignore_index=data.PAD_ID,
            )
            total += loss.item() * img_idx.size(0)
            count += img_idx.size(0)
    return math.exp(total / max(count, 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--split", default="test", choices=list(data.SPLITS))
    ap.add_argument("--num-examples", type=int, default=5000,
                    help="rows to decode for BLEU; 0 = every row")
    ap.add_argument("--max-ppl-rows", type=int, default=0,
                    help="cap teacher-forced perplexity rows; 0 = full split")
    ap.add_argument("--gen-batch", type=int, default=32,
                    help="rows decoded per batch; the biggest eval speed-up")
    ap.add_argument("--strategy", default="greedy",
                    choices=["greedy", "sample"],
                    help="greedy for all reported numbers")
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--top-k", type=int, default=0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--out", type=Path, default=None,
                    help="write metrics here as JSON")
    ap.add_argument("--samples-out", type=Path, default=None,
                    help="write gold/predicted pairs here as JSON; feeds the "
                         "report gallery")
    ap.add_argument("--show", type=int, default=8, help="samples to print")
    ap.add_argument("--device", default=None)
    args = ap.parse_args()

    device = args.device or ("mps" if torch.backends.mps.is_available() else "cpu")
    model, a, ckpt, tok = load_checkpoint(args.checkpoint, device)
    image_files = data.list_images()
    cache = DATA_DIR / f"{a['encoder']}_features.npz"
    feats = precompute_features(DATA_DIR / "images", cache, a["encoder"], device)
    feat_tensor = features_to_tensor(feats, image_files, device)

    mapping = data.load_template_map()
    rows = data.parse_captions(DATA_DIR / f"captions_{args.split}.txt")
    for r in rows:
        r["image"] = mapping[r["template"]]

    ppl_rows = rows if not args.max_ppl_rows else rows[: args.max_ppl_rows]
    print(f"[{args.split}] perplexity over {len(ppl_rows):,} rows ...", flush=True)
    ppl = perplexity(model, ppl_rows, image_files, feat_tensor, tok, args,
                     a["max_length"], device)

    # Same rows, same seed, every model -- otherwise the sample itself
    # becomes an uncontrolled variable between runs.
    idx = list(range(len(rows)))
    random.Random(args.seed).shuffle(idx)
    if args.num_examples:
        idx = idx[: args.num_examples]

    hyps, refs = [], []
    samples = []
    file_to_idx = {f: i for i, f in enumerate(image_files)}
    # Captions past ~48 tokens are outside the 99.9th percentile of the data,
    # so hard-capping generation there saves eval time without changing scores.
    max_new = min(a["max_length"], 48)
    print(f"[{args.split}] decoding {len(idx):,} rows (strategy={args.strategy}, "
          f"gen_batch={args.gen_batch}) ...", flush=True)
    import time
    start = time.time()
    with torch.no_grad():
        for n0 in range(0, len(idx), args.gen_batch):
            chunk = idx[n0:n0 + args.gen_batch]
            mem = torch.stack([feat_tensor[file_to_idx[rows[j]["image"]]] for j in chunk])
            outs = generate_batch(model, mem.to(device), tok, max_new=max_new,
                                  strategy=args.strategy, temperature=args.temperature,
                                  top_k=args.top_k or None, device=device,
                                  seed=args.seed)
            for (top, bottom), j in zip(outs, chunk):
                hyps.append(f"{top} <sep> {bottom}" if bottom else top)
                refs.append(rows[j]["caption"])
                samples.append({
                    "template": rows[j]["template"],
                    "image": rows[j]["image"],
                    "gold": rows[j]["caption"],
                    "pred": hyps[-1],
                })
            n_done = n0 + len(chunk)
            if n_done % (args.gen_batch * 4) == 0 or n_done >= len(idx):
                rate = n_done / (time.time() - start)
                print(f"  decoded {n_done}/{len(idx)}  ({rate:.1f} rows/s)", flush=True)

    print("\n--- sample generations (gold -> predicted) ---")
    for g, p in list(zip(refs, hyps))[: args.show]:
        print(f"  G: {g}\n  P: {p}\n")

    bleu = sacrebleu.corpus_bleu(hyps, [refs])
    metrics = {
        "split": args.split,
        "checkpoint": str(args.checkpoint),
        "step": ckpt.get("step"),
        "encoder": a["encoder"],
        "decoder": a["decoder"],
        "perplexity": round(ppl, 4),
        "bleu": round(bleu.score, 2),
        "n_ppl_rows": len(ppl_rows),
        "n_bleu_rows": len(hyps),
        "strategy": args.strategy,
        "sample_seed": args.seed,
        "val_loss": ckpt.get("val_loss"),
        "hyperparams": {k: a[k] for k in
                        ("embed_dim", "layers", "heads", "hidden_size",
                         "max_length", "lr")},
    }
    print(f"[{args.split}] {json.dumps(metrics, indent=2)}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(metrics, indent=2))
        print(f"-> {args.out}")

    if args.samples_out:
        args.samples_out.parent.mkdir(parents=True, exist_ok=True)
        args.samples_out.write_text(json.dumps(samples, indent=2))
        print(f"-> {args.samples_out} ({len(samples)} pairs)")


if __name__ == "__main__":
    main()
